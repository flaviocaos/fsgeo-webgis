"""Importação vetorial em fluxo: GDAL (pyogrio/Arrow) → COPY no PostGIS.

O arquivo é lido em lotes, sem carregar o conjunto inteiro na memória.
"""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Callable

import numpy as np
import pyarrow as pa
import shapely
from psycopg import sql
from pyproj import CRS

from geo import crs as crsmod
from geo.layerstore import (FIELD_SQL, Field, create_vector_layer, dedupe_names, refresh_stats,
                            table_ident)

BATCH = 20000
Progress = Callable[[int, str], None]


class ImportError_(ValueError):
    pass


def _arrow_to_field_type(t: pa.DataType) -> str:
    if pa.types.is_boolean(t):
        return "boolean"
    if pa.types.is_integer(t):
        return "integer"
    if pa.types.is_floating(t) or pa.types.is_decimal(t):
        return "real"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_timestamp(t):
        return "datetime"
    return "text"


def _py(value, ftype: str):
    if value is None:
        return None
    if ftype == "text" and not isinstance(value, str):
        return str(value)
    if ftype == "real" and isinstance(value, float) and not np.isfinite(value):
        return None
    if ftype == "datetime" and isinstance(value, dt.datetime) and value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def import_vector_layer(conn, path: Path, layer: str | None, *, project_id, user_id, name: str,
                        dataset_id=None, progress: Progress | None = None,
                        total_hint: int | None = None) -> tuple[dict, list[str]]:
    """Importa uma camada de um arquivo. Devolve (camada, mensagens)."""
    from pyogrio.raw import open_arrow

    messages: list[str] = []
    layer_id = uuid.uuid4()
    table = f"l_{layer_id.hex}"
    report = progress or (lambda p, m: None)

    with open_arrow(path, layer=layer, use_pyarrow=True, batch_size=BATCH) as (meta, reader):
        schema: pa.Schema = reader.schema
        geom_col = meta.get("geometry_name") or "wkb_geometry"
        if geom_col not in schema.names:
            raise ImportError_("A camada não tem coluna de geometria.")

        # CRS (descarta a dimensão vertical: a geometria é gravada em 2D)
        srid = 0
        if meta.get("crs"):
            c = CRS.from_user_input(meta["crs"])
            if len(c.axis_info) == 3:
                c = c.to_2d()
            srid = crsmod.srid_for_crs(conn, c)
        else:
            messages.append("Sistema de referência ausente: defina o CRS da camada para habilitar "
                            "mapa, medições e ferramentas.")

        attr_cols = [n for n in schema.names if n != geom_col]
        display = dedupe_names(attr_cols)
        fields = [Field(name=d, type=_arrow_to_field_type(schema.field(c).type))
                  for d, c in zip(display, attr_cols)]
        for i, f in enumerate(fields, start=1):
            f.column_name = f"f_{i}"

        cols = [sql.SQL("fid bigserial PRIMARY KEY"), sql.SQL("geom geometry")]
        cols += [sql.SQL("{} {}").format(sql.Identifier(f.column_name), sql.SQL(FIELD_SQL[f.type])) for f in fields]
        conn.execute(sql.SQL("CREATE TABLE {} ({})").format(table_ident(table), sql.SQL(", ").join(cols)))

        copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
            table_ident(table),
            sql.SQL(", ").join([sql.Identifier("geom")] + [sql.Identifier(f.column_name) for f in fields]))
        loaded = 0
        had_z = False
        with conn.cursor().copy(copy_sql) as cp:
            for batch in reader:
                geoms = shapely.from_wkb(batch.column(geom_col).to_numpy(zero_copy_only=False))
                if not had_z and bool(np.any(shapely.has_z(geoms))):
                    had_z = True
                geoms = shapely.force_2d(geoms)
                if srid:
                    geoms = shapely.set_srid(geoms, srid)
                hexes = shapely.to_wkb(geoms, hex=True, include_srid=bool(srid))
                attr_values = [batch.column(c).to_pylist() for c in attr_cols]
                for i in range(batch.num_rows):
                    row = [hexes[i]]
                    for f, vals in zip(fields, attr_values):
                        row.append(_py(vals[i], f.type))
                    cp.write_row(row)
                loaded += batch.num_rows
                pct = 15 + int(60 * loaded / total_hint) if total_hint else 50
                report(min(pct, 75), f"{loaded} feições lidas")
    if had_z:
        messages.append("Coordenadas Z foram descartadas: a camada é armazenada em 2D.")

    t = table_ident(table)
    types = [r["t"] for r in conn.execute(sql.SQL(
        "SELECT DISTINCT GeometryType(geom) AS t FROM {} WHERE geom IS NOT NULL").format(t)).fetchall()]
    geom_type = _resolve_type(types, meta.get("geometry_type"))
    if any(tp == "GEOMETRYCOLLECTION" for tp in types):
        raise ImportError_("A camada contém GeometryCollection, que não é suportada para edição.")
    multi = geom_type.startswith("Multi")
    conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN geom TYPE geometry({}, {}) USING {}").format(
        t, sql.SQL(geom_type), sql.Literal(srid), sql.SQL("ST_Multi(geom)" if multi else "geom")))
    report(80, "Criando índice espacial")
    conn.execute(sql.SQL("CREATE INDEX {} ON {} USING gist (geom)").format(sql.Identifier(f"{table}_geom_idx"), t))
    conn.execute(sql.SQL("ANALYZE {}").format(t))

    invalid = conn.execute(sql.SQL(
        "SELECT count(*) AS n FROM {} WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)").format(t)).fetchone()["n"]
    if invalid:
        messages.append(f"{invalid} geometria(s) inválida(s) encontrada(s). Use a ferramenta "
                        "'Validar e corrigir geometrias' antes de análises.")
    nulls = conn.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE geom IS NULL").format(t)).fetchone()["n"]
    if nulls:
        messages.append(f"{nulls} feição(ões) sem geometria (mantidas na tabela de atributos).")

    lyr = create_vector_layer(conn, project_id=project_id, name=name, srid=srid, geom_type=geom_type,
                              fields=fields, user_id=user_id, dataset_id=dataset_id,
                              create_table=False, layer_id=layer_id)
    lyr = refresh_stats(conn, lyr)
    return lyr, messages


_OGC = {"POINT": "Point", "LINESTRING": "LineString", "POLYGON": "Polygon",
        "MULTIPOINT": "MultiPoint", "MULTILINESTRING": "MultiLineString", "MULTIPOLYGON": "MultiPolygon"}


def _resolve_type(types: list[str], meta_type: str | None) -> str:
    names = {_OGC.get(t) for t in types if t in _OGC}
    if not names:
        base = (meta_type or "").replace(" Z", "").replace(" M", "").replace("25D", "").strip()
        if base in _OGC.values():
            return base
        raise ImportError_("Camada vazia e sem tipo de geometria declarado.")
    dims = {n.replace("Multi", "") for n in names}
    if len(dims) > 1:
        raise ImportError_("A camada mistura tipos de geometria (" + ", ".join(sorted(dims)) +
                           "). Separe por tipo antes de importar.")
    base = dims.pop()
    return f"Multi{base}" if any(n.startswith("Multi") for n in names) else base
