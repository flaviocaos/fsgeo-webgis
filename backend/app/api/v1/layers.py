"""Camadas: metadados, feições, seleção, identificação, campos e edição transacional."""
from __future__ import annotations

import json
import uuid
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field as PField

from app.api.v1.common import LAYER_COLUMNS, jsonable, public_layer
from app.core.config import get_settings
from app.core.deps import CurrentUser, UserDep, audit, require_layer, require_project
from app.core.errors import APIError, bad_request
from app.db.pool import connection
from app.storage import gdal_env, get_storage
from geo import crs as crsmod
from geo.raster.tiles import sample_point
from geo.filters import FilterError, build_where, coerce
from geo.layerstore import (Field, LayerStoreError, add_field, clean_field_name, create_vector_layer,
                            drop_field, drop_layer_table, field_map, get_fields, refresh_stats, rename_field,
                            table_ident)

router = APIRouter(tags=["camadas"])


# ------------------------------------------------------------------ modelos

class NewField(BaseModel):
    nome: str = PField(min_length=1, max_length=100)
    tipo: Literal["text", "integer", "real", "boolean", "date", "datetime"]


class NewLayer(BaseModel):
    nome: str = PField(min_length=1, max_length=200)
    geometria: Literal["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]
    crs: str | None = None
    campos: list[NewField] = []


class LayerPatch(BaseModel):
    nome: str = PField(min_length=1, max_length=200)


class DefineCRS(BaseModel):
    crs: str


class RenameField(BaseModel):
    novo_nome: str = PField(min_length=1, max_length=100)


class Filter(BaseModel):
    condicoes: list[dict[str, Any]] = []
    combinar: Literal["todas", "qualquer"] = "todas"


class SelectRequest(BaseModel):
    bbox: list[float] | None = PField(default=None, min_length=4, max_length=4)
    geometria: dict[str, Any] | None = None     # GeoJSON em EPSG:4326 (seleção por polígono)
    filtro: Filter | None = None
    limite: int = PField(default=100000, ge=1, le=500000)


class CreateOp(BaseModel):
    ref: str = PField(min_length=1, max_length=64)       # id temporário do cliente
    geometria: dict[str, Any] | None
    atributos: dict[str, Any] = {}


class UpdateOp(BaseModel):
    fid: int
    geometria: dict[str, Any] | None = None
    atributos: dict[str, Any] | None = None
    remover_geometria: bool = False


class EditBatch(BaseModel):
    versao_base: int | None = None
    criar: list[CreateOp] = []
    atualizar: list[UpdateOp] = []
    excluir: list[int] = []
    corrigir_invalidas: bool = False


# ------------------------------------------------------------------ helpers

def _vector(layer: dict) -> None:
    if layer["kind"] != "vector":
        raise bad_request("Operação disponível apenas para camadas vetoriais.")


def _need_crs(layer: dict) -> None:
    if not layer["srid"]:
        raise APIError(409, "crs_indefinido", "Defina o sistema de referência da camada primeiro.")


def _envelope_in_layer(bbox: list[float], layer: dict) -> tuple[sql.Composable, list]:
    """Envelope 4326 recortado à extensão da camada e levado ao CRS dela (evita transformações fora do domínio)."""
    w, s, e, n = bbox
    if not (w < e and s < n):
        raise bad_request("Retângulo inválido.")
    expr = sql.SQL(
        "ST_Transform(ST_Intersection(ST_MakeEnvelope(%s,%s,%s,%s,4326), "
        "COALESCE((SELECT ST_Buffer(bbox_4326, 1e-6) FROM app.layers WHERE id=%s), "
        "ST_MakeEnvelope(-180,-90,180,90,4326))), %s)")
    return expr, [max(w, -180), max(s, -90), min(e, 180), min(n, 90), layer["id"], layer["srid"]]


def _props(row: dict, fields: list[dict]) -> dict:
    return {f["name"]: jsonable(row[f["column_name"]]) for f in fields}


def _parse_filter(raw: str | None) -> Filter | None:
    if not raw:
        return None
    try:
        return Filter.model_validate(json.loads(raw))
    except (ValueError, TypeError):
        raise bad_request("Filtro inválido.")


def _layer_full(conn, layer_id) -> dict:
    row = conn.execute(f"SELECT {LAYER_COLUMNS} FROM app.layers l LEFT JOIN app.project_layers pl "
                       "ON pl.layer_id = l.id AND pl.project_id = l.project_id WHERE l.id=%s", (layer_id,)).fetchone()
    return public_layer(row, get_fields(conn, layer_id) if row["kind"] == "vector" else None)


# ------------------------------------------------------------------ metadados

@router.post("/projects/{project_id}/layers", status_code=201)
def create_empty_layer(project_id: UUID, body: NewLayer, user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user, "editor")
        crs_text = body.crs or conn.execute("SELECT crs FROM app.projects WHERE id=%s", (project_id,)).fetchone()["crs"]
        try:
            srid = crsmod.srid_for_crs(conn, crsmod.parse_crs(crs_text))
            fields = [Field(name=clean_field_name(f.nome), type=f.tipo) for f in body.campos]
            layer = create_vector_layer(conn, project_id=project_id, name=body.nome.strip(), srid=srid,
                                        geom_type=body.geometria, fields=fields, user_id=user.id)
        except (crsmod.CRSInputError, LayerStoreError) as exc:
            raise bad_request(str(exc))
        audit(conn, user, "criar", "camada", layer["id"], {"geometria": body.geometria})
        return _layer_full(conn, layer["id"])


@router.get("/layers/{layer_id}")
def get_layer_info(layer_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        out = _layer_full(conn, layer["id"])
        crs = crsmod.crs_from_srid(conn, layer["srid"]) if layer["srid"] else None
        out["crs_info"] = crsmod.describe(crs) if crs else None
        return out


@router.patch("/layers/{layer_id}")
def rename_layer(layer_id: UUID, body: LayerPatch, user: CurrentUser = UserDep):
    with connection() as conn:
        require_layer(conn, layer_id, user, "editor")
        conn.execute("UPDATE app.layers SET name=%s, updated_at=now() WHERE id=%s", (body.nome.strip(), layer_id))
        return _layer_full(conn, layer_id)


@router.delete("/layers/{layer_id}", status_code=204)
def delete_layer(layer_id: UUID, user: CurrentUser = UserDep):
    cog_to_delete = None
    with connection() as conn:
        layer = require_layer(conn, layer_id, user, "editor")
        if layer["kind"] == "vector":
            drop_layer_table(conn, layer["table_name"])
        else:
            other = conn.execute("SELECT 1 FROM app.layers WHERE cog_key=%s AND id<>%s LIMIT 1",
                                 (layer["cog_key"], layer_id)).fetchone()
            cog_to_delete = None if other else layer["cog_key"]
        conn.execute("DELETE FROM app.layers WHERE id=%s", (layer_id,))
        audit(conn, user, "excluir", "camada", layer_id, {"nome": layer["name"]})
    if cog_to_delete:
        get_storage().delete(cog_to_delete)


@router.post("/layers/{layer_id}/crs")
def define_crs(layer_id: UUID, body: DefineCRS, user: CurrentUser = UserDep):
    """Define (não reprojeta) o CRS de uma camada cujo sistema estava indefinido ou errado."""
    with connection() as conn:
        layer = require_layer(conn, layer_id, user, "editor")
        _vector(layer)
        try:
            srid = crsmod.srid_for_crs(conn, crsmod.parse_crs(body.crs))
        except crsmod.CRSInputError as exc:
            raise bad_request(str(exc))
        t = table_ident(layer["table_name"])
        conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN geom TYPE geometry({}, {}) USING ST_SetSRID(geom, {})")
                     .format(t, sql.SQL(layer["geom_type"]), sql.Literal(srid), sql.Literal(srid)))
        conn.execute("UPDATE app.layers SET srid=%s WHERE id=%s", (srid, layer_id))
        layer = conn.execute("SELECT * FROM app.layers WHERE id=%s", (layer_id,)).fetchone()
        try:
            refresh_stats(conn, layer, bump_version=True)
        except Exception:
            raise bad_request("As coordenadas da camada não são compatíveis com o CRS informado.")
        audit(conn, user, "definir_crs", "camada", layer_id, {"crs": body.crs})
        return _layer_full(conn, layer_id)


# ------------------------------------------------------------------ campos

@router.post("/layers/{layer_id}/fields", status_code=201)
def create_field(layer_id: UUID, body: NewField, user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user, "editor")
        _vector(layer)
        try:
            add_field(conn, layer, body.nome, body.tipo)
        except LayerStoreError as exc:
            raise bad_request(str(exc))
        return _layer_full(conn, layer_id)


@router.delete("/layers/{layer_id}/fields/{name}")
def delete_field(layer_id: UUID, name: str, user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user, "editor")
        _vector(layer)
        try:
            drop_field(conn, layer, name)
        except LayerStoreError as exc:
            raise bad_request(str(exc))
        return _layer_full(conn, layer_id)


@router.patch("/layers/{layer_id}/fields/{name}")
def patch_field(layer_id: UUID, name: str, body: RenameField, user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user, "editor")
        _vector(layer)
        try:
            rename_field(conn, layer, name, body.novo_nome)
        except LayerStoreError as exc:
            raise bad_request(str(exc))
        return _layer_full(conn, layer_id)


@router.get("/layers/{layer_id}/fields/{name}/stats")
def field_stats(layer_id: UUID, name: str, filtro: str | None = None, user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        _vector(layer)
        fm = field_map(conn, layer_id)
        if name not in fm:
            raise bad_request(f"Campo '{name}' não existe.")
        f = fm[name]
        col = sql.Identifier(f["column_name"])
        flt = _parse_filter(filtro)
        try:
            where, params = build_where(flt.condicoes if flt else [], flt.combinar if flt else "todas", fm)
        except FilterError as exc:
            raise bad_request(str(exc))
        t = table_ident(layer["table_name"])
        base = conn.execute(sql.SQL("SELECT count(*) AS total, count({c}) AS preenchidos, count(DISTINCT {c}) AS distintos "
                                    "FROM {t} WHERE {w}").format(c=col, t=t, w=where), params).fetchone()
        out: dict[str, Any] = {"campo": name, "tipo": f["type"], **base}
        if f["type"] in ("integer", "real"):
            r = conn.execute(sql.SQL("SELECT min({c}) AS min, max({c}) AS max, avg({c})::float AS media, "
                                     "sum({c})::float AS soma, stddev_samp({c})::float AS desvio, "
                                     "percentile_cont(0.5) WITHIN GROUP (ORDER BY {c}) AS mediana "
                                     "FROM {t} WHERE {w}").format(c=col, t=t, w=where), params).fetchone()
            out.update({k: jsonable(v) for k, v in r.items()})
        elif f["type"] in ("date", "datetime"):
            r = conn.execute(sql.SQL("SELECT min({c}) AS min, max({c}) AS max FROM {t} WHERE {w}")
                             .format(c=col, t=t, w=where), params).fetchone()
            out.update({k: jsonable(v) for k, v in r.items()})
        top = conn.execute(sql.SQL("SELECT {c} AS valor, count(*) AS n FROM {t} WHERE {w} GROUP BY 1 "
                                   "ORDER BY 2 DESC, 1 LIMIT 10").format(c=col, t=t, w=where), params).fetchall()
        out["mais_frequentes"] = [{"valor": jsonable(r["valor"]), "n": r["n"]} for r in top]
        return out


# ------------------------------------------------------------------ feições

@router.get("/layers/{layer_id}/features")
def list_features(
    layer_id: UUID,
    bbox: str | None = Query(default=None, description="oeste,sul,leste,norte em EPSG:4326"),
    fids: str | None = Query(default=None, description="lista de fid separada por vírgula"),
    filtro: str | None = Query(default=None, description="JSON {condicoes:[{campo,operador,valor}], combinar}"),
    ordenar: str | None = None,
    direcao: Literal["asc", "desc"] = "asc",
    limite: int = Query(default=100, ge=1),
    deslocamento: int = Query(default=0, ge=0),
    geometria: bool = True,
    contar: bool = True,
    user: CurrentUser = UserDep,
):
    s = get_settings()
    limite = min(limite, s.max_features_per_request)
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        _vector(layer)
        fields = get_fields(conn, layer_id)
        fm = {f["name"]: f for f in fields}
        conds: list[sql.Composable] = []
        params: list[Any] = []
        flt = _parse_filter(filtro)
        if flt and flt.condicoes:
            try:
                w, p = build_where(flt.condicoes, flt.combinar, fm)
            except FilterError as exc:
                raise bad_request(str(exc))
            conds.append(w); params += p
        if bbox:
            _need_crs(layer)
            try:
                bb = [float(v) for v in bbox.split(",")]
            except ValueError:
                raise bad_request("bbox inválido.")
            if len(bb) != 4:
                raise bad_request("bbox deve ter 4 números.")
            env, p = _envelope_in_layer(bb, layer)
            conds.append(sql.SQL("geom && {}").format(env)); params += p
        if fids:
            try:
                ids = [int(v) for v in fids.split(",") if v.strip()]
            except ValueError:
                raise bad_request("Lista de fid inválida.")
            conds.append(sql.SQL("fid = ANY(%s)")); params.append(ids[:s.max_features_per_request])
        where = sql.SQL(" AND ").join(conds) if conds else sql.SQL("TRUE")
        if ordenar and ordenar != "fid":
            if ordenar not in fm:
                raise bad_request(f"Campo '{ordenar}' não existe.")
            order = sql.SQL("{} {} NULLS LAST, fid").format(sql.Identifier(fm[ordenar]["column_name"]),
                                                            sql.SQL(direcao.upper()))
        else:
            order = sql.SQL("fid {}").format(sql.SQL(direcao.upper()))
        t = table_ident(layer["table_name"])
        geom_sel = (sql.SQL(", ST_AsGeoJSON(ST_Transform(geom, 4326), 9) AS gj") if geometria and layer["srid"]
                    else sql.SQL(""))
        cols = sql.SQL("").join(sql.SQL(", {}").format(sql.Identifier(f["column_name"])) for f in fields)
        rows = conn.execute(sql.SQL("SELECT fid{}{} FROM {} WHERE {} ORDER BY {} LIMIT %s OFFSET %s").format(
            cols, geom_sel, t, where, order), params + [limite, deslocamento]).fetchall()
        total = (conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE {}").format(t, where), params)
                 .fetchone()["n"] if contar else None)
        feats = [{"type": "Feature", "id": r["fid"],
                  "geometry": json.loads(r["gj"]) if r.get("gj") else None,
                  "properties": _props(r, fields)} for r in rows]
        return {"type": "FeatureCollection", "features": feats, "total": total, "limite": limite,
                "deslocamento": deslocamento, "versao": layer["version"]}


@router.post("/layers/{layer_id}/select")
def select_features(layer_id: UUID, body: SelectRequest, user: CurrentUser = UserDep):
    """Seleção por retângulo, polígono e/ou atributos. Devolve os fid selecionados."""
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        _vector(layer)
        fm = field_map(conn, layer_id)
        conds: list[sql.Composable] = []
        params: list[Any] = []
        if body.bbox:
            _need_crs(layer)
            env, p = _envelope_in_layer(body.bbox, layer)
            conds.append(sql.SQL("ST_Intersects(geom, {})").format(env)); params += p
        if body.geometria:
            _need_crs(layer)
            conds.append(sql.SQL("ST_Intersects(geom, ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s))"))
            params += [json.dumps(body.geometria), layer["srid"]]
        if body.filtro and body.filtro.condicoes:
            try:
                w, p = build_where(body.filtro.condicoes, body.filtro.combinar, fm)
            except FilterError as exc:
                raise bad_request(str(exc))
            conds.append(w); params += p
        if not conds:
            raise bad_request("Informe retângulo, geometria ou filtro.")
        rows = conn.execute(sql.SQL("SELECT fid FROM {} WHERE {} ORDER BY fid LIMIT %s").format(
            table_ident(layer["table_name"]), sql.SQL(" AND ").join(conds)), params + [body.limite]).fetchall()
        return {"fids": [r["fid"] for r in rows], "limite_atingido": len(rows) == body.limite}


@router.get("/layers/{layer_id}/identify")
def identify(layer_id: UUID, lon: float, lat: float, tolerancia_m: float = Query(default=5, ge=0, le=100000),
             limite: int = Query(default=10, ge=1, le=100), user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        if layer["kind"] == "raster":
            vals = sample_point(get_storage().gdal_path(layer["cog_key"]), lon, lat, gdal_env())
            if vals is None:
                return {"tipo": "raster", "valores": None}
            return {"tipo": "raster", "valores": [{"banda": i + 1, "valor": v} for i, v in enumerate(vals)]}
        _need_crs(layer)
        fields = get_fields(conn, layer_id)
        crs = crsmod.crs_from_srid(conn, layer["srid"])
        pt = sql.SQL("ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326), %s)")
        if crs and crsmod.is_metric(crs):
            cond = sql.SQL("ST_DWithin(geom, {pt}, %s)").format(pt=pt)
            dist = sql.SQL("ST_Distance(geom, {pt})").format(pt=pt)
            params_c = [lon, lat, layer["srid"], tolerancia_m]
            params_d = [lon, lat, layer["srid"]]
        else:
            cond = sql.SQL("ST_DWithin(ST_Transform(geom,4326)::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s)"
                           " AND geom && ST_Transform(ST_Expand(ST_SetSRID(ST_MakePoint(%s,%s),4326), %s), %s)")
            dist = sql.SQL("ST_Distance(ST_Transform(geom,4326)::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)")
            deg = tolerancia_m / 100000 + 1e-7
            params_c = [lon, lat, tolerancia_m, lon, lat, deg * 2, layer["srid"]]
            params_d = [lon, lat]
        cols = sql.SQL("").join(sql.SQL(", {}").format(sql.Identifier(f["column_name"])) for f in fields)
        rows = conn.execute(sql.SQL(
            "SELECT fid{c}, ST_AsGeoJSON(ST_Transform(geom,4326), 9) AS gj, {d} AS distancia FROM {t} "
            "WHERE {w} ORDER BY distancia LIMIT %s").format(c=cols, d=dist, t=table_ident(layer["table_name"]), w=cond),
            params_d + params_c + [limite]).fetchall()
        return {"tipo": "vetorial", "feicoes": [
            {"type": "Feature", "id": r["fid"], "geometry": json.loads(r["gj"]) if r["gj"] else None,
             "properties": _props(r, fields), "distancia_m": round(float(r["distancia"]), 3)} for r in rows]}


# ------------------------------------------------------------------ edição

def _geom_expr(conn, layer: dict, gj: dict, ref: str, fix: bool, errors: list) -> str | None:
    """Converte GeoJSON (4326) para EWKB no CRS e tipo da camada; valida. Devolve hex EWKB ou None se erro."""
    target = layer["geom_type"]
    try:
        row = conn.execute(
            """WITH g AS (SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s) AS g)
               SELECT GeometryType(g) AS t, ST_NumGeometries(g) AS n, ST_IsValid(g) AS ok,
                      ST_IsValidReason(g) AS motivo, g FROM g""",
            (json.dumps(gj), layer["srid"])).fetchone()
    except Exception:
        errors.append({"ref": ref, "erro": "Geometria GeoJSON inválida ou fora do domínio do CRS da camada."})
        return None
    gtype = {"POINT": "Point", "LINESTRING": "LineString", "POLYGON": "Polygon", "MULTIPOINT": "MultiPoint",
             "MULTILINESTRING": "MultiLineString", "MULTIPOLYGON": "MultiPolygon"}.get(row["t"])
    if gtype is None or gtype.replace("Multi", "") != target.replace("Multi", ""):
        errors.append({"ref": ref, "erro": f"Tipo {row['t']} incompatível com a camada ({target})."})
        return None
    expr, args = "%s::geometry", [row["g"]]
    if target.startswith("Multi") and not gtype.startswith("Multi"):
        expr = f"ST_Multi({expr})"
    elif not target.startswith("Multi") and gtype.startswith("Multi"):
        if row["n"] != 1:
            errors.append({"ref": ref, "erro": "A camada aceita geometrias de parte única; esta tem várias partes."})
            return None
        expr = f"ST_GeometryN({expr}, 1)"
    if not row["ok"]:
        if not fix:
            errors.append({"ref": ref, "erro": f"Geometria inválida: {row['motivo']}", "corrigivel": True})
            return None
        dim = {"Point": 1, "LineString": 2, "Polygon": 3}[target.replace("Multi", "")]
        expr = f"ST_CollectionExtract(ST_MakeValid({expr}), {dim})"
        if target.startswith("Multi"):
            expr = f"ST_Multi({expr})"
        fixed = conn.execute(f"SELECT {expr} AS g, GeometryType({expr}) AS t, ST_IsEmpty({expr}) AS vazia",
                             args * 3).fetchone()
        if fixed["vazia"] or fixed["t"] not in (target.upper(),):
            errors.append({"ref": ref, "erro": "A correção automática não produziu uma geometria do tipo da camada."})
            return None
        return fixed["g"]
    return conn.execute(f"SELECT {expr} AS g", args).fetchone()["g"]


def _attr_values(attrs: dict[str, Any], fm: dict[str, dict], ref: str, errors: list) -> dict[str, Any] | None:
    out = {}
    for name, value in attrs.items():
        f = fm.get(name)
        if f is None:
            errors.append({"ref": ref, "erro": f"Campo '{name}' não existe."})
            return None
        try:
            out[f["column_name"]] = coerce(value, f["type"]) if value not in ("", None) or f["type"] == "text" else None
        except FilterError as exc:
            errors.append({"ref": ref, "erro": f"{name}: {exc}"})
            return None
    return out


def _snapshot(conn, layer: dict, fields: list[dict], fid: int) -> dict | None:
    cols = sql.SQL("").join(sql.SQL(", {}").format(sql.Identifier(f["column_name"])) for f in fields)
    r = conn.execute(sql.SQL("SELECT fid{}, ST_AsGeoJSON(ST_Transform(geom,4326), 9) AS gj FROM {} WHERE fid=%s").format(
        cols, table_ident(layer["table_name"])), (fid,)).fetchone()
    if not r:
        return None
    return {"geometria": json.loads(r["gj"]) if r["gj"] else None, "atributos": _props(r, fields)}


@router.post("/layers/{layer_id}/edits")
def apply_edits(layer_id: UUID, body: EditBatch, user: CurrentUser = UserDep):
    """Aplica criações, alterações e exclusões numa única transação (tudo ou nada)."""
    total_ops = len(body.criar) + len(body.atualizar) + len(body.excluir)
    if total_ops == 0:
        raise bad_request("Nenhuma alteração enviada.")
    if total_ops > 10000:
        raise bad_request("Lote grande demais (máximo de 10.000 operações).")
    with connection() as conn:
        layer = require_layer(conn, layer_id, user, "editor")
        _vector(layer)
        _need_crs(layer)
        if not layer["editable"]:
            raise APIError(409, "nao_editavel", "Esta camada é somente leitura.")
        current = conn.execute("SELECT version FROM app.layers WHERE id=%s FOR UPDATE", (layer_id,)).fetchone()["version"]
        if body.versao_base is not None and body.versao_base != current:
            raise APIError(409, "conflito_versao",
                           "A camada foi alterada por outra pessoa desde que você começou a editar. "
                           "Recarregue a camada para ver a versão atual.", {"versao_atual": current})
        fields = get_fields(conn, layer_id)
        fm = {f["name"]: f for f in fields}
        t = table_ident(layer["table_name"])
        errors: list[dict] = []
        batch_id = uuid.uuid4()
        new_version = current + 1
        log_rows: list[tuple] = []
        created: dict[str, int] = {}

        for op in body.criar:
            g = _geom_expr(conn, layer, op.geometria, op.ref, body.corrigir_invalidas, errors) if op.geometria else None
            vals = _attr_values(op.atributos, fm, op.ref, errors)
            if (op.geometria and g is None) or vals is None:
                continue
            cols = [sql.Identifier("geom")] + [sql.Identifier(c) for c in vals]
            fid = conn.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING fid").format(
                t, sql.SQL(", ").join(cols), sql.SQL(", ").join([sql.SQL("%s::geometry")] + [sql.SQL("%s")] * len(vals))),
                [g, *vals.values()]).fetchone()["fid"]
            created[op.ref] = fid
            log_rows.append((fid, "insert", None, _snapshot(conn, layer, fields, fid)))

        updated = 0
        for op in body.atualizar:
            ref = f"fid:{op.fid}"
            before = _snapshot(conn, layer, fields, op.fid)
            if before is None:
                errors.append({"ref": ref, "erro": "Feição não existe (pode ter sido excluída)."})
                continue
            sets: list[sql.Composable] = []
            args: list[Any] = []
            if op.remover_geometria:
                sets.append(sql.SQL("geom = NULL"))
            elif op.geometria is not None:
                g = _geom_expr(conn, layer, op.geometria, ref, body.corrigir_invalidas, errors)
                if g is None:
                    continue
                sets.append(sql.SQL("geom = %s::geometry")); args.append(g)
            if op.atributos:
                vals = _attr_values(op.atributos, fm, ref, errors)
                if vals is None:
                    continue
                for c, v in vals.items():
                    sets.append(sql.SQL("{} = %s").format(sql.Identifier(c))); args.append(v)
            if not sets:
                continue
            conn.execute(sql.SQL("UPDATE {} SET {} WHERE fid=%s").format(t, sql.SQL(", ").join(sets)), args + [op.fid])
            updated += 1
            log_rows.append((op.fid, "update", before, _snapshot(conn, layer, fields, op.fid)))

        deleted = 0
        for fid in body.excluir:
            before = _snapshot(conn, layer, fields, fid)
            if before is None:
                errors.append({"ref": f"fid:{fid}", "erro": "Feição não existe (pode ter sido excluída)."})
                continue
            conn.execute(sql.SQL("DELETE FROM {} WHERE fid=%s").format(t), (fid,))
            deleted += 1
            log_rows.append((fid, "delete", before, None))

        if errors:
            conn.rollback()
            raise APIError(422, "edicao_invalida", "Nenhuma alteração foi salva: corrija os itens indicados.", errors)

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO app.edit_log (layer_id, batch_id, fid, op, before, after, user_id, layer_version) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                [(layer_id, batch_id, fid, op, Jsonb(b) if b else None, Jsonb(a) if a else None, user.id, new_version)
                 for fid, op, b, a in log_rows])
        refresh_stats(conn, layer, bump_version=True)
        audit(conn, user, "editar", "camada", layer_id,
              {"lote": str(batch_id), "criadas": len(created), "alteradas": updated, "excluidas": deleted})
        return {"versao": new_version, "lote": str(batch_id), "criadas": created, "alteradas": updated,
                "excluidas": deleted}


@router.get("/layers/{layer_id}/edits")
def edit_history(layer_id: UUID, limite: int = Query(default=50, ge=1, le=500), user: CurrentUser = UserDep):
    with connection() as conn:
        require_layer(conn, layer_id, user)
        rows = conn.execute(
            "SELECT e.id, e.batch_id, e.fid, e.op, e.layer_version, e.created_at, u.email FROM app.edit_log e "
            "JOIN app.users u ON u.id=e.user_id WHERE e.layer_id=%s ORDER BY e.id DESC LIMIT %s",
            (layer_id, limite)).fetchall()
    return [{"id": r["id"], "lote": str(r["batch_id"]), "fid": r["fid"], "operacao": r["op"],
             "versao": r["layer_version"], "quando": r["created_at"].isoformat(), "usuario": r["email"]} for r in rows]


