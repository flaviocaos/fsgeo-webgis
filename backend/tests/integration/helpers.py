import math

import psycopg

from tests.conftest import TEST_DB


def area_m2(layer_id: str, srid: int = 31983) -> list[float]:
    """Áreas (m²) das feições da camada medidas em UTM 23S, direto no banco."""
    with psycopg.connect(TEST_DB) as conn:
        table = conn.execute("SELECT table_name FROM app.layers WHERE id=%s", (layer_id,)).fetchone()[0]
        rows = conn.execute(f"SELECT ST_Area(ST_Transform(geom, {srid})) FROM layerdata.{table} ORDER BY fid").fetchall()
    return [r[0] for r in rows]


def scalar(query: str, *params):
    with psycopg.connect(TEST_DB) as conn:
        return conn.execute(query, params).fetchone()[0]


def table_of(layer_id: str) -> str:
    return scalar("SELECT table_name FROM app.layers WHERE id=%s", layer_id)


def tile_xyz(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, x, y
