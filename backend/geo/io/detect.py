"""Preparação e detecção de arquivos enviados.

A detecção abre o arquivo com GDAL (não confia na extensão) e só aceita os drivers
liberados na fase atual. Formatos fora da lista recebem mensagem clara de indisponibilidade.
"""
from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

VECTOR_DRIVERS = {"GeoJSON": "GeoJSON", "ESRI Shapefile": "Shapefile", "GPKG": "GeoPackage"}
RASTER_DRIVERS = {"GTiff": "GeoTIFF"}

# Formatos previstos nas próximas fases (mensagem de indisponível, não de erro desconhecido).
PLANNED = {
    ".kml": "KML", ".kmz": "KMZ", ".gml": "GML", ".gpx": "GPX", ".csv": "CSV", ".dxf": "DXF",
    ".fgb": "FlatGeobuf", ".parquet": "GeoParquet", ".jp2": "JPEG2000", ".img": "ERDAS IMG",
    ".asc": "ASCII Grid", ".hdr": "ENVI", ".nc": "NetCDF", ".hdf": "HDF", ".h5": "HDF5",
    ".vrt": "VRT", ".png": "PNG georreferenciado", ".jpg": "JPEG georreferenciado",
}
CANDIDATE_EXT = {".geojson", ".json", ".shp", ".gpkg", ".tif", ".tiff"}


class DetectError(ValueError):
    pass


@dataclass
class Detected:
    path: Path
    kind: str                 # vector | raster
    driver: str
    format_label: str
    layers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def safe_extract_zip(zip_path: Path, dest: Path, max_bytes: int, max_members: int = 10000) -> list[Path]:
    """Extrai um zip recusando caminhos absolutos, '..', links simbólicos e zip-bombs."""
    out: list[Path] = []
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > max_members:
            raise DetectError("O arquivo zip tem itens demais.")
        total = 0
        for info in infos:
            name = info.filename
            if name.startswith("/") or "\\" in name or any(p == ".." for p in name.split("/")):
                raise DetectError(f"Caminho inválido dentro do zip: {name}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise DetectError("O zip contém links simbólicos, que não são aceitos.")
            total += info.file_size
            if total > max_bytes:
                raise DetectError("O conteúdo descompactado excede o limite permitido.")
        for info in infos:
            if info.is_dir() or info.filename.startswith("__MACOSX/"):
                continue
            target = (dest / info.filename).resolve()
            if dest not in target.parents:
                raise DetectError(f"Caminho inválido dentro do zip: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                remaining = info.file_size
                while chunk := src.read(1024 * 1024):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise DetectError("Item do zip maior que o declarado.")
                    dst.write(chunk)
            out.append(target)
    return out


def expand_inputs(files: list[Path], workdir: Path, max_zip_bytes: int) -> list[Path]:
    """Descompacta zips e devolve os arquivos principais encontrados (um por conjunto de dados)."""
    all_files: list[Path] = []
    for f in files:
        if f.suffix.lower() == ".zip":
            if not zipfile.is_zipfile(f):
                raise DetectError(f"'{f.name}' não é um zip válido.")
            sub = workdir / f"z_{f.stem}"
            sub.mkdir(parents=True, exist_ok=True)
            all_files += safe_extract_zip(f, sub, max_zip_bytes)
        else:
            all_files.append(f)
    mains = [p for p in all_files if p.suffix.lower() in CANDIDATE_EXT]
    if not mains:
        exts = {p.suffix.lower() for p in all_files}
        planned = sorted({PLANNED[e] for e in exts if e in PLANNED})
        if planned:
            raise DetectError(f"Formato ainda não suportado nesta fase: {', '.join(planned)}. "
                              "Na Fase 1 são aceitos GeoJSON, Shapefile, GeoPackage e GeoTIFF.")
        if exts & {".shx", ".dbf", ".prj", ".cpg"}:
            raise DetectError("Arquivo .shp ausente: envie o .shp junto com .shx, .dbf e .prj.")
        raise DetectError("Nenhum arquivo geoespacial reconhecido. Formatos aceitos: GeoJSON, "
                          "Shapefile (.zip ou .shp/.shx/.dbf/.prj), GeoPackage e GeoTIFF.")
    return sorted(mains)


def detect(path: Path) -> Detected:
    import pyogrio
    import rasterio
    from rasterio.errors import RasterioIOError

    warnings: list[str] = []
    ext = path.suffix.lower()
    if ext == ".shp":
        missing = [s for s in (".shx", ".dbf") if not _sibling(path, s)]
        if missing:
            raise DetectError(f"Shapefile '{path.name}' incompleto: faltam {', '.join(missing)}.")
        if not _sibling(path, ".prj"):
            warnings.append(f"'{path.name}' não tem .prj: o sistema de referência ficará indefinido "
                            "até você defini-lo na camada.")

    if ext in (".tif", ".tiff"):
        try:
            with rasterio.open(path) as ds:
                driver = ds.driver
        except RasterioIOError as exc:
            raise DetectError(f"Não foi possível ler '{path.name}' como raster: arquivo corrompido ou inválido.") from exc
        if driver not in RASTER_DRIVERS:
            raise DetectError(f"Driver raster '{driver}' ainda não suportado.")
        return Detected(path, "raster", driver, RASTER_DRIVERS[driver], warnings=warnings)

    try:
        info_layers = pyogrio.list_layers(path)
        layers = [str(r[0]) for r in info_layers]
        driver = pyogrio.read_info(path, layer=layers[0])["driver"] if layers else None
    except Exception as exc:  # pyogrio.errors.DataSourceError e afins
        raise DetectError(f"Não foi possível ler '{path.name}': arquivo corrompido ou em formato não reconhecido.") from exc
    if not layers:
        raise DetectError(f"'{path.name}' não contém camadas vetoriais.")
    if driver not in VECTOR_DRIVERS:
        raise DetectError(f"Formato '{driver}' ainda não suportado nesta fase.")
    return Detected(path, "vector", driver, VECTOR_DRIVERS[driver], layers=layers, warnings=warnings)


def _sibling(path: Path, ext: str) -> bool:
    for cand in path.parent.iterdir():
        if cand.stem == path.stem and cand.suffix.lower() == ext:
            return True
    return False
