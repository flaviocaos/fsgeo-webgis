"""Renderização de tiles e consulta de pixel em COGs (rio-tiler)."""
from __future__ import annotations

import numpy as np
import rasterio
from rio_tiler.colormap import cmap
from rio_tiler.errors import PointOutsideBounds
from rio_tiler.io import Reader

PALETTES = {"cinza", "viridis", "terrain", "rdylgn", "magma", "spectral"}
_CMAP_NAMES = {"viridis": "viridis", "terrain": "terrain", "rdylgn": "rdylgn", "magma": "magma",
               "spectral": "spectral"}


def render_tile(path: str, z: int, x: int, y: int, stats: list[dict], *, bands: list[int] | None = None,
                palette: str = "cinza", stretch: str = "percentil", nodata=None,
                env: dict | None = None) -> bytes | None:
    with rasterio.Env(**(env or {})):
        with Reader(path) as r:
            if not r.tile_exists(x, y, z):
                return None
            count = r.dataset.count
            if bands:
                if any(b < 1 or b > count for b in bands):
                    raise ValueError(f"Banda inexistente; o raster tem {count} banda(s).")
                idx = bands
            else:
                idx = [1, 2, 3] if count >= 3 else [1]
            img = r.tile(x, y, z, indexes=tuple(idx), nodata=nodata)
            ranges = []
            for b in idx:
                st = next((s for s in stats if s.get("banda") == b), None)
                if not st or st.get("vazia"):
                    ranges.append((0, 1))
                elif stretch == "minmax":
                    ranges.append((st["min"], st["max"] if st["max"] > st["min"] else st["min"] + 1))
                else:
                    ranges.append((st["p2"], st["p98"] if st["p98"] > st["p2"] else st["p2"] + 1))
            img.rescale(in_range=ranges)
            colormap = None
            if len(idx) == 1 and palette in _CMAP_NAMES:
                colormap = cmap.get(_CMAP_NAMES[palette])
            return img.render(img_format="PNG", colormap=colormap)


def sample_point(path: str, lon: float, lat: float, env: dict | None = None) -> list[float | None] | None:
    with rasterio.Env(**(env or {})):
        with Reader(path) as r:
            try:
                pt = r.point(lon, lat)
            except PointOutsideBounds:
                return None
            arr = pt.array
            masked = np.ma.getmaskarray(arr)
            return [None if masked[i] else float(arr.data[i]) for i in range(arr.shape[0])]
