"""Criação e manutenção das tabelas de camadas vetoriais no schema layerdata.

Cada camada vetorial é uma tabela própria:
    fid  bigserial PRIMARY KEY
    geom geometry(<Tipo>, <srid>)  (índice GiST)
    f_1, f_2, ...                  (atributos; nomes exibidos em app.layer_fields)
Nomes de tabelas e colunas são sempre gerados aqui, nunca vindos do usuário.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from psycopg import sql

GEOM_TYPES = ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon")
FIELD_SQL = {
    "text": "text", "integer": "bigint", "real": "double precision",
    "boolean": "boolean", "date": "date", "datetime": "timestamptz",
}
RESERVED = {"fid", "geom", "geometry", "id_feicao"}


class LayerStoreError(ValueError):
    pass


@dataclass
class Field:
    name: str
    type: str
    column_name: str = ""


def table_ident(table_name: str) -> sql.Composed:
    return sql.Identifier("layerdata", table_name)


def clean_field_name(name: str) -> str:
    n = " ".join(str(name).split())[:100]
    if not n:
        raise LayerStoreError("Nome de campo vazio.")
    if n.lower() in RESERVED:
        raise LayerStoreError(f"O nome de campo '{n}' é reservado pelo sistema.")
    return n


def dedupe_names(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for raw in names:
        n = str(raw).strip()[:100] or "campo"
        if n.lower() in RESERVED:
            n = f"{n}_orig"
        base, k = n, 1
        while n.lower() in seen:
            k += 1
            n = f"{base}_{k}"[:100]
        seen[n.lower()] = 1
        out.append(n)
    return out


def multi_of(geom_type: str) -> str:
    return geom_type if geom_type.startswith("Multi") else f"Multi{geom_type}"


def dimension(geom_type: str) -> int:
    base = geom_type.replace("Multi", "")
    return {"Point": 1, "LineString": 2, "Polygon": 3}[base]


def create_vector_layer(conn, *, project_id, name: str, srid: int, geom_type: str,
                        fields: list[Field], user_id, dataset_id=None, source_job_id=None,
                        editable: bool = True, add_to_project: bool = True,
                        create_table: bool = True, layer_id: uuid.UUID | None = None) -> dict[str, Any]:
    if geom_type not in GEOM_TYPES:
        raise LayerStoreError(f"Tipo de geometria não suportado: {geom_type}")
    layer_id = layer_id or uuid.uuid4()
    table = f"l_{layer_id.hex}"
    for i, f in enumerate(fields, start=1):
        if f.type not in FIELD_SQL:
            raise LayerStoreError(f"Tipo de campo não suportado: {f.type}")
        f.column_name = f"f_{i}"
    names = [f.name for f in fields]
    if len({n.lower() for n in names}) != len(names):
        raise LayerStoreError("Há campos com nomes repetidos.")

    if create_table:
        cols = [sql.SQL("fid bigserial PRIMARY KEY"),
                sql.SQL("geom geometry({}, {})").format(sql.SQL(geom_type), sql.Literal(int(srid)))]
        cols += [sql.SQL("{} {}").format(sql.Identifier(f.column_name), sql.SQL(FIELD_SQL[f.type]))
                 for f in fields]
        conn.execute(sql.SQL("CREATE TABLE {} ({})").format(table_ident(table), sql.SQL(", ").join(cols)))
        conn.execute(sql.SQL("CREATE INDEX {} ON {} USING gist (geom)").format(
            sql.Identifier(f"{table}_geom_idx"), table_ident(table)))

    conn.execute(
        """INSERT INTO app.layers (id, project_id, dataset_id, source_job_id, kind, name, srid, geom_type,
                                   table_name, next_field, editable, created_by)
           VALUES (%s,%s,%s,%s,'vector',%s,%s,%s,%s,%s,%s,%s)""",
        (layer_id, project_id, dataset_id, source_job_id, name[:200], srid, geom_type, table,
         len(fields) + 1, editable, user_id),
    )
    for pos, f in enumerate(fields):
        conn.execute("INSERT INTO app.layer_fields (layer_id, name, column_name, type, position) VALUES (%s,%s,%s,%s,%s)",
                     (layer_id, f.name, f.column_name, f.type, pos))
    if add_to_project:
        add_to_project_top(conn, project_id, layer_id)
    return get_layer(conn, layer_id)


def add_to_project_top(conn, project_id, layer_id, style: dict | None = None) -> None:
    from psycopg.types.json import Jsonb
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM app.project_layers WHERE project_id=%s",
                       (project_id,)).fetchone()["p"]
    conn.execute("INSERT INTO app.project_layers (project_id, layer_id, position, style) VALUES (%s,%s,%s,%s)",
                 (project_id, layer_id, pos, Jsonb(style or {})))


def get_layer(conn, layer_id) -> dict[str, Any]:
    return conn.execute("SELECT * FROM app.layers WHERE id=%s", (layer_id,)).fetchone()


def get_fields(conn, layer_id) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT name, column_name, type, position FROM app.layer_fields WHERE layer_id=%s ORDER BY position",
        (layer_id,),
    ).fetchall()


def field_map(conn, layer_id) -> dict[str, dict[str, Any]]:
    """nome exibido -> {column_name, type}"""
    return {f["name"]: f for f in get_fields(conn, layer_id)}


def refresh_stats(conn, layer: dict[str, Any], bump_version: bool = False) -> dict[str, Any]:
    t = table_ident(layer["table_name"])
    count = conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(t)).fetchone()["n"]
    bbox = None
    if layer["srid"]:
        row = conn.execute(sql.SQL(
            """WITH e AS (SELECT ST_Transform(ST_SetSRID(ST_Extent(geom)::geometry, %s), 4326) AS g FROM {})
               SELECT CASE WHEN g IS NULL THEN NULL ELSE
                 ST_MakeEnvelope(ST_XMin(g), ST_YMin(g), GREATEST(ST_XMax(g), ST_XMin(g) + 1e-9),
                                 GREATEST(ST_YMax(g), ST_YMin(g) + 1e-9), 4326) END AS b FROM e""").format(t),
            (layer["srid"],)).fetchone()
        bbox = row["b"]
    conn.execute(
        """UPDATE app.layers SET feature_count=%s, bbox_4326=%s::geometry, updated_at=now(),
                  version = version + %s WHERE id=%s""",
        (count, bbox, 1 if bump_version else 0, layer["id"]),
    )
    return get_layer(conn, layer["id"])


def drop_layer_table(conn, table_name: str) -> None:
    conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table_ident(table_name)))


def layer_center_lonlat(conn, layer: dict[str, Any]) -> tuple[float, float] | None:
    if layer.get("bbox_4326") is None:
        return None
    r = conn.execute("SELECT ST_X(ST_Centroid(%s::geometry)) AS x, ST_Y(ST_Centroid(%s::geometry)) AS y",
                     (layer["bbox_4326"], layer["bbox_4326"])).fetchone()
    return (r["x"], r["y"])


def add_field(conn, layer: dict[str, Any], name: str, ftype: str) -> dict[str, Any]:
    name = clean_field_name(name)
    if ftype not in FIELD_SQL:
        raise LayerStoreError(f"Tipo de campo não suportado: {ftype}")
    if name.lower() in {f["name"].lower() for f in get_fields(conn, layer["id"])}:
        raise LayerStoreError(f"Já existe um campo chamado '{name}'.")
    nxt = conn.execute("UPDATE app.layers SET next_field = next_field + 1 WHERE id=%s RETURNING next_field - 1 AS n",
                       (layer["id"],)).fetchone()["n"]
    col = f"f_{nxt}"
    conn.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
        table_ident(layer["table_name"]), sql.Identifier(col), sql.SQL(FIELD_SQL[ftype])))
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM app.layer_fields WHERE layer_id=%s",
                       (layer["id"],)).fetchone()["p"]
    conn.execute("INSERT INTO app.layer_fields (layer_id, name, column_name, type, position) VALUES (%s,%s,%s,%s,%s)",
                 (layer["id"], name, col, ftype, pos))
    conn.execute("UPDATE app.layers SET version = version + 1, updated_at = now() WHERE id=%s", (layer["id"],))
    return {"name": name, "column_name": col, "type": ftype, "position": pos}


def drop_field(conn, layer: dict[str, Any], name: str) -> None:
    f = field_map(conn, layer["id"]).get(name)
    if not f:
        raise LayerStoreError(f"Campo '{name}' não existe.")
    conn.execute(sql.SQL("ALTER TABLE {} DROP COLUMN {}").format(
        table_ident(layer["table_name"]), sql.Identifier(f["column_name"])))
    conn.execute("DELETE FROM app.layer_fields WHERE layer_id=%s AND column_name=%s", (layer["id"], f["column_name"]))
    conn.execute("UPDATE app.layers SET version = version + 1, updated_at = now() WHERE id=%s", (layer["id"],))


def rename_field(conn, layer: dict[str, Any], old: str, new: str) -> None:
    new = clean_field_name(new)
    fm = field_map(conn, layer["id"])
    if old not in fm:
        raise LayerStoreError(f"Campo '{old}' não existe.")
    if new.lower() != old.lower() and new.lower() in {n.lower() for n in fm}:
        raise LayerStoreError(f"Já existe um campo chamado '{new}'.")
    conn.execute("UPDATE app.layer_fields SET name=%s WHERE layer_id=%s AND name=%s", (new, layer["id"], old))
    conn.execute("UPDATE app.layers SET version = version + 1, updated_at = now() WHERE id=%s", (layer["id"],))
