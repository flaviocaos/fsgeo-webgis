"""Exportação de camadas vetoriais (GeoJSON, GeoPackage, Shapefile, CSV) a partir do PostGIS."""
from __future__ import annotations

import re
import unicodedata
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from psycopg import sql

from geo import crs as crsmod
from geo.layerstore import get_fields, table_ident

FORMATS = {
    "geojson": {"rotulo": "GeoJSON", "ext": ".geojson", "driver": "GeoJSON"},
    "gpkg": {"rotulo": "GeoPackage", "ext": ".gpkg", "driver": "GPKG"},
    "shp": {"rotulo": "Shapefile (zip)", "ext": ".zip", "driver": "ESRI Shapefile"},
    "csv": {"rotulo": "CSV com WKT", "ext": ".csv", "driver": "CSV"},
}


class ExportError(ValueError):
    pass


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")
    return s[:60] or "camada"


def _shp_names(names: list[str]) -> list[str]:
    out, used = [], set()
    for n in names:
        base = slug(n)[:10] or "campo"
        cand, k = base, 1
        while cand.lower() in used:
            k += 1
            suf = str(k)
            cand = base[: 10 - len(suf)] + suf
        used.add(cand.lower())
        out.append(cand)
    return out


def export_vector(conn, layer: dict, fmt: str, out_dir: Path) -> tuple[Path, list[str]]:
    if fmt not in FORMATS:
        raise ExportError(f"Formato de exportação '{fmt}' não suportado.")
    if not layer["srid"] and fmt != "csv":
        raise ExportError("Defina o sistema de referência da camada antes de exportar neste formato.")
    messages: list[str] = []
    fields = get_fields(conn, layer["id"])
    to4326 = fmt == "geojson" and layer["srid"] not in (0, 4326)
    geom_expr = sql.SQL("ST_AsBinary(ST_Transform(geom, 4326))") if to4326 else sql.SQL("ST_AsBinary(geom)")
    cols = [sql.SQL("{} AS {}").format(sql.Identifier(f["column_name"]), sql.Identifier(f["column_name"])) for f in fields]
    rows = conn.execute(sql.SQL("SELECT fid, {} AS wkb{} FROM {} ORDER BY fid").format(
        geom_expr, sql.SQL("").join(sql.SQL(", ") + c for c in cols), table_ident(layer["table_name"]))).fetchall()

    data = {f["name"]: [r[f["column_name"]] for r in rows] for f in fields}
    geoms = shapely.from_wkb([bytes(r["wkb"]) if r["wkb"] is not None else None for r in rows])
    if to4326:
        crs = "EPSG:4326"
        messages.append("GeoJSON exportado em WGS 84 (EPSG:4326), conforme a especificação RFC 7946.")
    else:
        c = crsmod.crs_from_srid(conn, layer["srid"]) if layer["srid"] else None
        crs = c.to_wkt() if c else None
    df = pd.DataFrame(data)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.GeoSeries(geoms, crs=crs), crs=crs)

    base = slug(layer["name"])
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = FORMATS[fmt]
    if fmt == "shp":
        new = _shp_names([f["name"] for f in fields])
        renamed = {f["name"]: n for f, n in zip(fields, new) if f["name"] != n}
        if renamed:
            gdf = gdf.rename(columns=renamed)
            messages.append("Nomes de campos ajustados ao limite de 10 caracteres do Shapefile: " +
                            "; ".join(f"{a} → {b}" for a, b in renamed.items()))
        for f, n in zip(fields, new):
            if f["type"] == "datetime":
                gdf[n] = gdf[n].astype("string")
                messages.append(f"Campo '{f['name']}' (data e hora) gravado como texto: Shapefile não suporta hora.")
        shp_dir = out_dir / "shp"
        shp_dir.mkdir(exist_ok=True)
        shp_path = shp_dir / f"{base}.shp"
        gdf.to_file(shp_path, driver=spec["driver"], engine="pyogrio", encoding="UTF-8")
        zpath = out_dir / f"{base}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(shp_dir.iterdir()):
                zf.write(f, f.name)
        return zpath, messages
    if fmt == "csv":
        df = pd.DataFrame(data)
        df.insert(0, "wkt", shapely.to_wkt(geoms))
        path = out_dir / f"{base}.csv"
        df.to_csv(path, index=False)
        if layer["srid"]:
            messages.append(f"Coordenadas WKT no CRS da camada (SRID {layer['srid']}).")
        return path, messages
    path = out_dir / f"{base}{spec['ext']}"
    gdf.to_file(path, driver=spec["driver"], engine="pyogrio", layer=base if fmt == "gpkg" else None)
    return path, messages
