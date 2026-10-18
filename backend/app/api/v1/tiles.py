"""Tiles vetoriais (MVT via ST_AsMVT) e raster (PNG a partir de COG)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Response
from psycopg import sql

from app.core.deps import CurrentUser, UserDep, require_layer
from app.core.errors import bad_request
from app.db.pool import connection
from app.storage import gdal_env, get_storage
from geo.layerstore import get_fields, table_ident
from geo.raster.tiles import render_tile

router = APIRouter(tags=["tiles"])
CACHE = "private, max-age=86400"   # a URL inclui ?v=<versão da camada>, então muda a cada edição


def _check_zxy(z: int, x: int, y: int) -> None:
    if not (0 <= z <= 24 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise bad_request("Coordenadas de tile inválidas.")


@router.get("/layers/{layer_id}/tiles/{z}/{x}/{y}.pbf")
def vector_tile(layer_id: UUID, z: int, x: int, y: int, user: CurrentUser = UserDep):
    _check_zxy(z, x, y)
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        if layer["kind"] != "vector":
            raise bad_request("Camada não é vetorial.")
        if not layer["srid"] or layer["bbox_4326"] is None:
            return Response(status_code=204)
        fields = get_fields(conn, layer_id)
        attrs = sql.SQL("").join(
            sql.SQL(", t.{} AS {}").format(sql.Identifier(f["column_name"]), sql.Identifier(f["name"])) for f in fields)
        q = sql.SQL("""
            WITH env AS (SELECT ST_TileEnvelope(%s,%s,%s) AS e3857),
                 cut AS (SELECT e3857, ST_Intersection(ST_Transform(e3857, 4326),
                                    ST_Buffer(l.bbox_4326, 1e-6)) AS e4326
                         FROM env, app.layers l WHERE l.id = %s),
                 q AS (
                   SELECT ST_AsMVTGeom(ST_Transform(t.geom, 3857), cut.e3857, 4096, 64, true) AS geom,
                          t.fid{attrs}
                   FROM {tbl} t, cut
                   WHERE NOT ST_IsEmpty(cut.e4326) AND t.geom && ST_Transform(cut.e4326, %s))
            SELECT ST_AsMVT(q, 'camada', 4096, 'geom', 'fid') AS tile FROM q WHERE geom IS NOT NULL
        """).format(attrs=attrs, tbl=table_ident(layer["table_name"]))
        row = conn.execute(q, (z, x, y, layer_id, layer["srid"])).fetchone()
    tile = bytes(row["tile"]) if row and row["tile"] else b""
    if not tile:
        return Response(status_code=204, headers={"Cache-Control": CACHE})
    return Response(tile, media_type="application/vnd.mapbox-vector-tile", headers={"Cache-Control": CACHE})


@router.get("/layers/{layer_id}/raster/{z}/{x}/{y}.png")
def raster_tile(layer_id: UUID, z: int, x: int, y: int,
                bandas: str | None = Query(default=None, description="ex.: 4,3,2"),
                paleta: str = "cinza", realce: str = "percentil", user: CurrentUser = UserDep):
    _check_zxy(z, x, y)
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
    if layer["kind"] != "raster":
        raise bad_request("Camada não é raster.")
    idx = None
    if bandas:
        try:
            idx = [int(b) for b in bandas.split(",")][:3]
        except ValueError:
            raise bad_request("Bandas inválidas.")
        if len(idx) == 2:
            raise bad_request("Informe 1 banda (escala de cinza/paleta) ou 3 bandas (RGB).")
    stats = (layer["raster_stats"] or {}).get("estatisticas", [])
    try:
        png = render_tile(get_storage().gdal_path(layer["cog_key"]), z, x, y, stats, bands=idx, palette=paleta,
                          stretch=realce, env=gdal_env())
    except ValueError as exc:
        raise bad_request(str(exc))
    if png is None:
        return Response(status_code=204, headers={"Cache-Control": CACHE})
    return Response(png, media_type="image/png", headers={"Cache-Control": CACHE})
