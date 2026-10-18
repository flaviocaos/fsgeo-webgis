"""Ferramentas vetoriais executadas no PostGIS.

Cada ferramenta lê camadas existentes, grava o resultado numa camada nova (as entradas
nunca são alteradas) e devolve (camada, mensagens, estatísticas).
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from psycopg import sql

from geo import crs as crsmod
from geo.layerstore import (FIELD_SQL, Field, create_vector_layer, dedupe_names, dimension, get_fields,
                            get_layer, layer_center_lonlat, multi_of, refresh_stats, table_ident)

Progress = Callable[[int, str], None]


class ToolError(ValueError):
    pass


class Ctx:
    def __init__(self, conn, project_id, user_id, job_id=None, progress: Progress | None = None):
        self.conn = conn
        self.project_id = project_id
        self.user_id = user_id
        self.job_id = job_id
        self.progress = progress or (lambda p, m: None)
        self.messages: list[str] = []


# ---------------------------------------------------------------- utilidades

def _input_layer(ctx: Ctx, layer_id, label: str, allowed: list[str] | None = None) -> dict:
    try:
        lid = uuid.UUID(str(layer_id))
    except ValueError:
        raise ToolError(f"{label}: identificador inválido.")
    layer = get_layer(ctx.conn, lid)
    if not layer or str(layer["project_id"]) != str(ctx.project_id):
        raise ToolError(f"{label}: camada não encontrada neste projeto.")
    if layer["kind"] != "vector":
        raise ToolError(f"{label}: a ferramenta exige uma camada vetorial.")
    if not layer["srid"]:
        raise ToolError(f"{label}: defina o sistema de referência da camada antes de usá-la.")
    if allowed and layer["geom_type"] not in allowed:
        raise ToolError(f"{label}: tipo de geometria {layer['geom_type']} não aceito por esta ferramenta.")
    return layer


def _carry_fields(conn, layer, prefix_start: int = 1, existing: list[str] | None = None,
                  alias: str = "i") -> tuple[list[Field], list[sql.Composable]]:
    """Campos da camada copiados para a saída (renumerados f_1..)."""
    src = get_fields(conn, layer["id"])
    names = dedupe_names((existing or []) + [f["name"] for f in src])[len(existing or []):]
    fields, selects = [], []
    for k, (f, name) in enumerate(zip(src, names)):
        col = f"f_{prefix_start + k}"
        fields.append(Field(name=name, type=f["type"], column_name=col))
        selects.append(sql.SQL("{}.{} AS {}").format(sql.Identifier(alias), sql.Identifier(f["column_name"]),
                                                    sql.Identifier(col)))
    return fields, selects


def _norm(expr: sql.Composable, dim: int, multi: bool = True) -> sql.Composable:
    inner = sql.SQL("ST_CollectionExtract({}, {})").format(expr, sql.Literal(dim))
    return sql.SQL("ST_Multi({})").format(inner) if multi else inner


def _materialize(ctx: Ctx, *, name: str, geom_type: str, srid: int, fields: list[Field],
                 select: sql.Composable, params: list | tuple = ()) -> dict:
    """Cria a tabela de saída a partir de um SELECT que devolve geom + f_1..f_n."""
    conn = ctx.conn
    layer_id = uuid.uuid4()
    table = f"l_{layer_id.hex}"
    t = table_ident(table)
    cols = [sql.SQL("fid bigserial PRIMARY KEY"),
            sql.SQL("geom geometry({}, {})").format(sql.SQL(geom_type), sql.Literal(srid))]
    cols += [sql.SQL("{} {}").format(sql.Identifier(f.column_name), sql.SQL(FIELD_SQL[f.type])) for f in fields]
    conn.execute(sql.SQL("CREATE TABLE {} ({})").format(t, sql.SQL(", ").join(cols)))
    target = sql.SQL(", ").join([sql.Identifier("geom")] + [sql.Identifier(f.column_name) for f in fields])
    picked = sql.SQL(", ").join([sql.SQL("q.geom")] + [sql.SQL("q.{}").format(sql.Identifier(f.column_name))
                                                       for f in fields])
    ctx.progress(40, "Executando no PostGIS")
    conn.execute(sql.SQL("INSERT INTO {} ({}) SELECT {} FROM ({}) q WHERE q.geom IS NOT NULL AND NOT ST_IsEmpty(q.geom)")
                 .format(t, target, picked, select), params)
    ctx.progress(80, "Criando índice espacial")
    conn.execute(sql.SQL("CREATE INDEX {} ON {} USING gist (geom)").format(sql.Identifier(f"{table}_geom_idx"), t))
    conn.execute(sql.SQL("ANALYZE {}").format(t))
    layer = create_vector_layer(conn, project_id=ctx.project_id, name=name, srid=srid, geom_type=geom_type,
                                fields=fields, user_id=ctx.user_id, source_job_id=ctx.job_id,
                                create_table=False, layer_id=layer_id)
    return refresh_stats(conn, layer)


def _overlay_temp(ctx: Ctx, overlay: dict, target_srid: int, carry: bool) -> tuple[str, list[Field]]:
    """Copia a camada de sobreposição para uma tabela temporária no CRS da entrada, com índice."""
    name = f"ov_{uuid.uuid4().hex[:12]}"
    src = get_fields(ctx.conn, overlay["id"])
    cols = [sql.SQL("ST_MakeValid(ST_Transform(o.geom, %s)) AS g")]
    fields = []
    if carry:
        for k, f in enumerate(src, start=1):
            cols.append(sql.SQL("o.{} AS {}").format(sql.Identifier(f["column_name"]), sql.Identifier(f"o_{k}")))
            fields.append(Field(name=f["name"], type=f["type"], column_name=f"o_{k}"))
    ctx.conn.execute(sql.SQL("CREATE TEMP TABLE {} ON COMMIT DROP AS SELECT {} FROM {} o WHERE o.geom IS NOT NULL")
                     .format(sql.Identifier(name), sql.SQL(", ").join(cols), table_ident(overlay["table_name"])),
                     (target_srid,))
    ctx.conn.execute(sql.SQL("CREATE INDEX ON {} USING gist (g)").format(sql.Identifier(name)))
    ctx.conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(name)))
    a = crsmod.crs_from_srid(ctx.conn, target_srid)
    b = crsmod.crs_from_srid(ctx.conn, overlay["srid"])
    if a and b and (w := crsmod.datum_warning(a, b)):
        ctx.messages.append(w)
    if overlay["srid"] != target_srid:
        ctx.messages.append(f"'{overlay['name']}' foi reprojetada temporariamente para o CRS da camada de entrada.")
    return name, fields


def _metric(ctx: Ctx, layer: dict) -> int:
    crs = crsmod.crs_from_srid(ctx.conn, layer["srid"])
    m = crsmod.metric_srid(layer["srid"], crs, layer_center_lonlat(ctx.conn, layer))
    if m != layer["srid"]:
        ctx.messages.append(f"Distâncias calculadas em EPSG:{m} (UTM local), pois a camada não está em metros.")
    return m


def _in_metric(expr: sql.Composable, srid: int, metric: int, op: Callable[[sql.Composable], sql.Composable]) -> sql.Composable:
    if metric == srid:
        return op(expr)
    return sql.SQL("ST_Transform({}, {})").format(
        op(sql.SQL("ST_Transform({}, {})").format(expr, sql.Literal(metric))), sql.Literal(srid))


def _count(ctx: Ctx, layer: dict) -> int:
    return ctx.conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(table_ident(layer["table_name"]))).fetchone()["n"]


# ---------------------------------------------------------------- ferramentas

def buffer(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    try:
        dist = float(p.get("distancia"))
    except (TypeError, ValueError):
        raise ToolError("Distância inválida.")
    unit = p.get("unidade", "m")
    if unit not in ("m", "km"):
        raise ToolError("Unidade deve ser m ou km.")
    meters = dist * (1000 if unit == "km" else 1)
    if meters == 0:
        raise ToolError("A distância deve ser diferente de zero.")
    if meters < 0 and dimension(layer["geom_type"]) != 3:
        raise ToolError("Distância negativa só se aplica a polígonos.")
    segs = int(p.get("segmentos", 8))
    if not 1 <= segs <= 64:
        raise ToolError("Segmentos deve estar entre 1 e 64.")
    metric = _metric(ctx, layer)
    srid = layer["srid"]
    buf = _in_metric(sql.SQL("i.geom"), srid, metric,
                     lambda g: sql.SQL("ST_Buffer({}, {}, {})").format(g, sql.Literal(meters),
                                                                        sql.Literal(f"quad_segs={segs}")))
    name = p.get("saida") or f"{layer['name']} · buffer {dist:g} {unit}"
    if p.get("dissolver"):
        select = sql.SQL("SELECT {} AS geom FROM {} i WHERE i.geom IS NOT NULL").format(
            _norm(sql.SQL("ST_Union({})").format(buf), 3), table_ident(layer["table_name"]))
        out = _materialize(ctx, name=name, geom_type="MultiPolygon", srid=srid, fields=[], select=select)
    else:
        fields, sels = _carry_fields(ctx.conn, layer)
        select = sql.SQL("SELECT {} AS geom{} FROM {} i WHERE i.geom IS NOT NULL").format(
            _norm(buf, 3), sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]))
        out = _materialize(ctx, name=name, geom_type="MultiPolygon", srid=srid, fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"],
                                            "distancia_m": meters}}


def clip(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    clipper = _input_layer(ctx, p.get("recorte"), "Camada de recorte", ["Polygon", "MultiPolygon"])
    srid, dim = layer["srid"], dimension(layer["geom_type"])
    ov, _ = _overlay_temp(ctx, clipper, srid, carry=False)
    # Partes subdivididas aceleram a interseção com polígonos grandes.
    pieces = f"{ov}_p"
    ctx.conn.execute(sql.SQL("CREATE TEMP TABLE {} ON COMMIT DROP AS SELECT ST_Subdivide(g, 256) AS g FROM {}")
                     .format(sql.Identifier(pieces), sql.Identifier(ov)))
    ctx.conn.execute(sql.SQL("CREATE INDEX ON {} USING gist (g)").format(sql.Identifier(pieces)))
    fields, sels = _carry_fields(ctx.conn, layer)
    geom = _norm(sql.SQL("ST_Union(ST_Intersection(ST_MakeValid(i.geom), c.g))"), dim)
    select = sql.SQL("SELECT {} AS geom{} FROM {} i JOIN {} c ON ST_Intersects(i.geom, c.g) GROUP BY i.fid").format(
        geom, sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]),
        sql.Identifier(pieces))
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · recorte", geom_type=multi_of(layer["geom_type"]),
                       srid=srid, fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"]}}


def intersection(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    other = _input_layer(ctx, p.get("sobreposicao"), "Camada de sobreposição")
    srid = layer["srid"]
    dim = min(dimension(layer["geom_type"]), dimension(other["geom_type"]))
    ov, ofields = _overlay_temp(ctx, other, srid, carry=True)
    fields, sels = _carry_fields(ctx.conn, layer)
    names = dedupe_names([f.name for f in fields] + [f.name for f in ofields])
    out_fields = list(fields)
    for k, (f, n) in enumerate(zip(ofields, names[len(fields):]), start=len(fields) + 1):
        out_fields.append(Field(name=n, type=f.type, column_name=f"f_{k}"))
        sels.append(sql.SQL("o.{} AS {}").format(sql.Identifier(f.column_name), sql.Identifier(f"f_{k}")))
    geom = _norm(sql.SQL("ST_Intersection(ST_MakeValid(i.geom), o.g)"), dim)
    select = sql.SQL("SELECT {} AS geom{} FROM {} i JOIN {} o ON ST_Intersects(i.geom, o.g)").format(
        geom, sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]), sql.Identifier(ov))
    gt = {1: "MultiPoint", 2: "MultiLineString", 3: "MultiPolygon"}[dim]
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} ∩ {other['name']}", geom_type=gt,
                       srid=srid, fields=out_fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "sobreposicao": _count(ctx, other),
                                            "saida": out["feature_count"]}}


def difference(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    other = _input_layer(ctx, p.get("sobreposicao"), "Camada de sobreposição", ["Polygon", "MultiPolygon"])
    srid, dim = layer["srid"], dimension(layer["geom_type"])
    ov, _ = _overlay_temp(ctx, other, srid, carry=False)
    fields, sels = _carry_fields(ctx.conn, layer)
    sub = sql.SQL("(SELECT ST_Union(o.g) FROM {} o WHERE ST_Intersects(i.geom, o.g))").format(sql.Identifier(ov))
    geom = _norm(sql.SQL("COALESCE(ST_Difference(ST_MakeValid(i.geom), {}), ST_MakeValid(i.geom))").format(sub), dim)
    select = sql.SQL("SELECT {} AS geom{} FROM {} i WHERE i.geom IS NOT NULL").format(
        geom, sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]))
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} − {other['name']}",
                       geom_type=multi_of(layer["geom_type"]), srid=srid, fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"]}}


def dissolve(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    by = p.get("campos") or []
    if not isinstance(by, list):
        raise ToolError("Campos de agrupamento devem ser uma lista.")
    src = {f["name"]: f for f in get_fields(ctx.conn, layer["id"])}
    fields, sels, groups = [], [], []
    for k, name in enumerate(by, start=1):
        if name not in src:
            raise ToolError(f"Campo '{name}' não existe na camada.")
        col = sql.Identifier(src[name]["column_name"])
        fields.append(Field(name=name, type=src[name]["type"], column_name=f"f_{k}"))
        sels.append(sql.SQL("i.{} AS {}").format(col, sql.Identifier(f"f_{k}")))
        groups.append(sql.SQL("i.{}").format(col))
    dim = dimension(layer["geom_type"])
    geom = _norm(sql.SQL("ST_Union(ST_MakeValid(i.geom))"), dim)
    select = sql.SQL("SELECT {} AS geom{} FROM {} i WHERE i.geom IS NOT NULL{}").format(
        geom, sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]),
        (sql.SQL(" GROUP BY ") + sql.SQL(", ").join(groups)) if groups else sql.SQL(""))
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · dissolvida", geom_type=multi_of(layer["geom_type"]),
                       srid=layer["srid"], fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"]}}


def centroid(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    fn = "ST_PointOnSurface" if p.get("dentro") else "ST_Centroid"
    fields, sels = _carry_fields(ctx.conn, layer)
    select = sql.SQL("SELECT {}(i.geom) AS geom{} FROM {} i WHERE i.geom IS NOT NULL").format(
        sql.SQL(fn), sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]))
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · centroides", geom_type="Point",
                       srid=layer["srid"], fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"]}}


def simplify(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada",
                         ["LineString", "MultiLineString", "Polygon", "MultiPolygon"])
    try:
        tol = float(p.get("tolerancia"))
    except (TypeError, ValueError):
        raise ToolError("Tolerância inválida.")
    if tol <= 0:
        raise ToolError("A tolerância deve ser maior que zero.")
    metric = _metric(ctx, layer)
    srid = layer["srid"]
    g = _in_metric(sql.SQL("i.geom"), srid, metric,
                   lambda e: sql.SQL("ST_SimplifyPreserveTopology({}, {})").format(e, sql.Literal(tol)))
    multi = layer["geom_type"].startswith("Multi")
    geom = _norm(g, dimension(layer["geom_type"]), multi=multi) if multi else g
    fields, sels = _carry_fields(ctx.conn, layer)
    before = ctx.conn.execute(sql.SQL("SELECT COALESCE(sum(ST_NPoints(geom)),0) AS n FROM {}")
                              .format(table_ident(layer["table_name"]))).fetchone()["n"]
    select = sql.SQL("SELECT {} AS geom{} FROM {} i WHERE i.geom IS NOT NULL").format(
        geom, sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]))
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · simplificada {tol:g} m",
                       geom_type=layer["geom_type"], srid=srid, fields=fields, select=select)
    after = ctx.conn.execute(sql.SQL("SELECT COALESCE(sum(ST_NPoints(geom)),0) AS n FROM {}")
                             .format(table_ident(out["table_name"]))).fetchone()["n"]
    return {"camada": out, "estatisticas": {"vertices_antes": before, "vertices_depois": after}}


def multipart_to_singlepart(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    fields, sels = _carry_fields(ctx.conn, layer, alias="d")
    single = layer["geom_type"].replace("Multi", "")
    select = sql.SQL("SELECT d.g AS geom{} FROM (SELECT (ST_Dump(i.geom)).geom AS g, i.* FROM {} i "
                     "WHERE i.geom IS NOT NULL) d").format(
        sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]))
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · partes simples", geom_type=single,
                       srid=layer["srid"], fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"]}}


def reproject(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    try:
        target = crsmod.parse_crs(p.get("crs", ""))
    except crsmod.CRSInputError as exc:
        raise ToolError(str(exc))
    srid = crsmod.srid_for_crs(ctx.conn, target)
    src_crs = crsmod.crs_from_srid(ctx.conn, layer["srid"])
    if src_crs and (w := crsmod.datum_warning(src_crs, target)):
        ctx.messages.append(w)
    fields, sels = _carry_fields(ctx.conn, layer)
    select = sql.SQL("SELECT ST_Transform(i.geom, {}) AS geom{} FROM {} i WHERE i.geom IS NOT NULL").format(
        sql.Literal(srid), sql.SQL("").join(sql.SQL(", ") + s for s in sels), table_ident(layer["table_name"]))
    code = target.to_epsg() or srid
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · EPSG:{code}", geom_type=layer["geom_type"],
                       srid=srid, fields=fields, select=select)
    return {"camada": out, "estatisticas": {"entrada": _count(ctx, layer), "saida": out["feature_count"]}}


def fix_geometries(ctx: Ctx, p: dict) -> dict:
    layer = _input_layer(ctx, p.get("camada"), "Camada de entrada")
    t = table_ident(layer["table_name"])
    invalid = ctx.conn.execute(sql.SQL(
        "SELECT fid, ST_IsValidReason(geom) AS motivo FROM {} WHERE geom IS NOT NULL AND NOT ST_IsValid(geom) "
        "ORDER BY fid LIMIT 50").format(t)).fetchall()
    n_invalid = ctx.conn.execute(sql.SQL(
        "SELECT count(*) AS n FROM {} WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)").format(t)).fetchone()["n"]
    dim = dimension(layer["geom_type"])
    fields, sels = _carry_fields(ctx.conn, layer)
    select = sql.SQL("SELECT {} AS geom{} FROM {} i WHERE i.geom IS NOT NULL").format(
        _norm(sql.SQL("ST_MakeValid(i.geom, 'method=structure')") if dim == 3 else sql.SQL("ST_MakeValid(i.geom)"), dim),
        sql.SQL("").join(sql.SQL(", ") + s for s in sels), t)
    out = _materialize(ctx, name=p.get("saida") or f"{layer['name']} · corrigida",
                       geom_type=multi_of(layer["geom_type"]), srid=layer["srid"], fields=fields, select=select)
    total = _count(ctx, layer)
    dropped = total - out["feature_count"]
    if n_invalid == 0:
        ctx.messages.append("Nenhuma geometria inválida encontrada.")
    else:
        ctx.messages.append(f"{n_invalid} geometria(s) inválida(s) corrigida(s).")
    if dropped:
        ctx.messages.append(f"{dropped} feição(ões) sem geometria ou degeneradas não foram copiadas.")
    return {"camada": out, "estatisticas": {"invalidas": n_invalid, "entrada": total, "saida": out["feature_count"],
                                            "exemplos": [{"fid": r["fid"], "motivo": r["motivo"]} for r in invalid]}}


TOOLS: dict[str, Callable[[Ctx, dict], dict]] = {
    "vector.buffer": buffer, "vector.clip": clip, "vector.intersection": intersection,
    "vector.difference": difference, "vector.dissolve": dissolve, "vector.centroid": centroid,
    "vector.simplify": simplify, "vector.multipart_to_singlepart": multipart_to_singlepart,
    "vector.reproject": reproject, "vector.fix_geometries": fix_geometries,
}


def run(ctx: Ctx, tool_id: str, params: dict[str, Any]) -> dict:
    fn = TOOLS.get(tool_id)
    if fn is None:
        raise ToolError("Ferramenta indisponível.")
    ctx.progress(10, "Validando parâmetros")
    result = fn(ctx, params)
    result["mensagens"] = ctx.messages
    return result
