"""Importação raster: valida georreferência, converte para COG e calcula estatísticas."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds


class RasterIngestError(ValueError):
    pass


def to_cog(src: Path, dst: Path) -> dict:
    from rio_cogeo.cogeo import cog_translate
    from rio_cogeo.profiles import cog_profiles

    with rasterio.open(src) as ds:
        if ds.crs is None:
            raise RasterIngestError(
                f"'{src.name}' não tem sistema de referência. Defina o CRS no arquivo antes de enviar "
                "(definir CRS de raster na plataforma está previsto para a Fase 2).")
        if ds.transform.is_identity:
            raise RasterIngestError(f"'{src.name}' não está georreferenciado (sem transformação geográfica).")
        if ds.count == 0:
            raise RasterIngestError(f"'{src.name}' não tem bandas.")
    profile = cog_profiles.get("deflate")
    cog_translate(str(src), str(dst), profile, in_memory=False, quiet=True,
                  config={"GDAL_NUM_THREADS": "ALL_CPUS"})
    return describe(dst)


def describe(path: Path) -> dict:
    with rasterio.open(path) as ds:
        scale = min(1.0, 1024 / max(ds.width, ds.height))
        shape = (ds.count, max(1, int(ds.height * scale)), max(1, int(ds.width * scale)))
        data = ds.read(out_shape=shape, masked=True)
        stats = []
        for b in range(ds.count):
            band = data[b]
            valid = band.compressed() if np.ma.isMaskedArray(band) else band.ravel()
            valid = valid[np.isfinite(valid)] if valid.dtype.kind == "f" else valid
            if valid.size == 0:
                stats.append({"banda": b + 1, "vazia": True})
                continue
            p2, p98 = np.percentile(valid, [2, 98])
            stats.append({
                "banda": b + 1, "min": float(valid.min()), "max": float(valid.max()),
                "media": float(valid.mean()), "desvio": float(valid.std()),
                "p2": float(p2), "p98": float(p98), "descricao": ds.descriptions[b],
            })
        bounds = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
        res = ds.res
        return {
            "width": ds.width, "height": ds.height, "count": ds.count, "dtype": ds.dtypes[0],
            "nodata": ds.nodata, "crs_wkt": ds.crs.to_wkt(), "epsg": ds.crs.to_epsg(),
            "bounds_4326": [float(v) for v in bounds], "resolucao": [float(res[0]), float(res[1])],
            "estatisticas": stats, "amostragem_estatisticas": round(scale, 4),
        }
