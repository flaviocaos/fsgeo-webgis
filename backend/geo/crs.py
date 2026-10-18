"""Sistemas de referência: interpretação, registro no PostGIS e projeções métricas."""
from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

CUSTOM_SRID_START = 910000


class CRSInputError(ValueError):
    pass


def parse_crs(value: str | int) -> CRS:
    """Aceita 'EPSG:31983', '31983', WKT ou string PROJ."""
    text = str(value).strip()
    if text.isdigit():
        text = f"EPSG:{text}"
    try:
        return CRS.from_user_input(text)
    except CRSError as exc:
        raise CRSInputError(f"Sistema de referência não reconhecido: {value}") from exc


def srid_for_crs(conn, crs: CRS) -> int:
    """Devolve o SRID do PostGIS para o CRS, registrando-o se for personalizado."""
    epsg = crs.to_epsg(min_confidence=70)
    if epsg:
        row = conn.execute("SELECT srid FROM spatial_ref_sys WHERE auth_name='EPSG' AND auth_srid=%s",
                           (epsg,)).fetchone()
        if row:
            return int(_first(row))
    wkt = crs.to_wkt()
    row = conn.execute("SELECT srid FROM spatial_ref_sys WHERE srtext = %s", (wkt,)).fetchone()
    if row:
        return int(_first(row))
    # Serializa a criação de SRIDs personalizados.
    conn.execute("SELECT pg_advisory_xact_lock(7300113)")
    nxt = conn.execute("SELECT GREATEST(COALESCE(MAX(srid), 0) + 1, %s) FROM spatial_ref_sys WHERE srid >= %s",
                       (CUSTOM_SRID_START, CUSTOM_SRID_START)).fetchone()
    srid = int(_first(nxt))
    conn.execute(
        "INSERT INTO spatial_ref_sys (srid, auth_name, auth_srid, srtext, proj4text) VALUES (%s,'WEBGIS',%s,%s,%s)",
        (srid, srid, wkt, crs.to_proj4()),
    )
    return srid


def crs_from_srid(conn, srid: int) -> CRS | None:
    if not srid:
        return None
    row = conn.execute("SELECT auth_name, auth_srid, srtext FROM spatial_ref_sys WHERE srid=%s", (srid,)).fetchone()
    if not row:
        return None
    r = row if isinstance(row, dict) else {"auth_name": row[0], "auth_srid": row[1], "srtext": row[2]}
    if r["auth_name"] == "EPSG":
        return CRS.from_epsg(r["auth_srid"])
    return CRS.from_wkt(r["srtext"])


def describe(crs: CRS) -> dict:
    epsg = crs.to_epsg(min_confidence=70)
    unit = crs.axis_info[0].unit_name if crs.axis_info else None
    return {
        "codigo": f"EPSG:{epsg}" if epsg else None,
        "nome": crs.name,
        "geografico": crs.is_geographic,
        "unidade": unit,
        "proj4": crs.to_proj4(),
        "wkt": crs.to_wkt(),
        "datum": crs.datum.name if crs.datum else None,
    }


def is_metric(crs: CRS) -> bool:
    if crs.is_geographic or not crs.axis_info:
        return False
    return all((a.unit_name or "").lower() in ("metre", "meter") for a in crs.axis_info[:2])


def utm_epsg(lon: float, lat: float) -> int:
    """UTM WGS 84 da posição (zonas especiais da Noruega/Svalbard ignoradas)."""
    zone = int(math.floor((lon + 180) / 6)) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


def metric_srid(srid: int, crs: CRS | None, lon_lat_center: tuple[float, float] | None) -> int:
    """SRID em metros para operar distâncias: o da camada se já for métrico, senão o UTM local."""
    if crs is not None and is_metric(crs):
        return srid
    if lon_lat_center is None:
        raise CRSInputError("Não foi possível escolher uma projeção métrica: camada sem extensão.")
    return utm_epsg(*lon_lat_center)


@lru_cache(maxsize=256)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(src), CRS.from_user_input(dst), always_xy=True)


def transform_points(src: str, dst: str, coords: list[list[float]]) -> list[list[float]]:
    t = _transformer(parse_crs(src).to_wkt(), parse_crs(dst).to_wkt())
    out = []
    for c in coords:
        x, y = t.transform(c[0], c[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise CRSInputError(f"Coordenada fora do domínio da projeção: {c}")
        out.append([x, y])
    return out


def datum_warning(a: CRS, b: CRS) -> str | None:
    """Aviso quando duas camadas usam datums diferentes (ex.: SAD69 x SIRGAS 2000)."""
    da = a.datum.name if a.datum else None
    db = b.datum.name if b.datum else None
    if da and db and da != db:
        pair = {da, db}
        # WGS 84 e SIRGAS 2000 coincidem dentro de ~1 m para a maioria dos usos.
        def _is(name: str, *keys: str) -> bool:
            return any(k.lower() in name.lower() for k in keys)
        if any(_is(x, "WGS", "World Geodetic System 1984") for x in pair) and \
                any(_is(x, "SIRGAS", "Geocentrico para las AmericaS") for x in pair):
            return (f"Datums diferentes ({da} e {db}); a diferença costuma ser inferior a 1 m, "
                    "mas verifique se a precisão do trabalho exige transformação rigorosa.")
        return f"Datums diferentes ({da} e {db}); a reprojeção aplica a transformação padrão do PROJ."
    return None


def _first(row):
    return next(iter(row.values())) if isinstance(row, dict) else row[0]
