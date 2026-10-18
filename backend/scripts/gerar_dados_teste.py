"""Gera os dados geoespaciais de exemplo/teste em tests/fixtures.

Todos os valores são conhecidos de antemão, para que os testes comparem resultados exatos.
Uso: python scripts/gerar_dados_teste.py [diretório]
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, Polygon, box

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests" / "fixtures")

# Região de Brasília: SIRGAS 2000 / UTM 23S (EPSG:31983)
X0, Y0 = 190000.0, 8250000.0


def zip_dir(files: list[Path], dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp"
    tmp.mkdir(exist_ok=True)

    # 1) Lotes (GeoJSON, WGS 84): 4 quadrados de 100 m lado a lado, gerados em UTM e convertidos.
    lotes = gpd.GeoDataFrame(
        {"nome": ["Lote A", "Lote B", "Lote C", "Lote D"],
         "quadra": [1, 1, 2, 2],
         "area_ha": [1.0, 1.0, 1.0, 1.0],
         "ativo": [True, False, True, True],
         "data_cadastro": ["2024-01-15", "2024-02-20", "2024-03-10", "2024-04-05"],
         "observacao": ["esquina", None, None, "APP"]},
        geometry=[box(X0 + i * 100, Y0, X0 + (i + 1) * 100, Y0 + 100) for i in range(4)], crs="EPSG:31983")
    lotes["data_cadastro"] = lotes["data_cadastro"].astype("datetime64[ms]").dt.date
    lotes.to_crs("EPSG:4326").to_file(OUT / "lotes.geojson", driver="GeoJSON", engine="pyogrio")

    # 2) Quadrado de 100 m em UTM (GeoPackage) — base dos testes analíticos de buffer.
    gpd.GeoDataFrame({"nome": ["Quadrado"]}, geometry=[box(X0, Y0, X0 + 100, Y0 + 100)], crs="EPSG:31983") \
        .to_file(OUT / "quadrado_31983.gpkg", driver="GPKG", layer="quadrado", engine="pyogrio")

    # 3) Área de recorte: retângulo cobrindo metade dos lotes A e B (x de X0+50 a X0+150).
    gpd.GeoDataFrame({"zona": ["Zona 1"]}, geometry=[box(X0 + 50, Y0 - 50, X0 + 150, Y0 + 150)], crs="EPSG:31983") \
        .to_file(OUT / "zona_31983.gpkg", driver="GPKG", layer="zona", engine="pyogrio")

    # 4) Vias (Shapefile zipado, SIRGAS 2000 / UTM 23S)
    vias = gpd.GeoDataFrame(
        {"nome_da_via": ["Rua 1", "Rua 2"], "largura_m": [12.0, 8.5]},
        geometry=[LineString([(X0 - 50, Y0 + 50), (X0 + 450, Y0 + 50)]),
                  LineString([(X0 + 200, Y0 - 100), (X0 + 200, Y0 + 200)])], crs="EPSG:31983")
    vias.to_file(tmp / "vias.shp", driver="ESRI Shapefile", engine="pyogrio", encoding="UTF-8")
    zip_dir(sorted(tmp.glob("vias.*")), OUT / "vias_shp.zip")

    # 5) Nascentes (GeoPackage, SIRGAS 2000 geográfico EPSG:4674)
    pts = gpd.GeoSeries([Point(X0 + 50, Y0 + 50), Point(X0 + 250, Y0 + 50), Point(X0 + 1000, Y0 + 1000)],
                        crs="EPSG:31983").to_crs("EPSG:4674")
    gpd.GeoDataFrame({"codigo": ["N1", "N2", "N3"], "vazao_ls": [0.5, 1.25, 3.0]}, geometry=pts) \
        .to_file(OUT / "nascentes.gpkg", driver="GPKG", layer="nascentes", engine="pyogrio")

    # 6) Shapefile sem .prj
    sem = gpd.GeoDataFrame({"id": [1]}, geometry=[box(X0, Y0, X0 + 10, Y0 + 10)], crs="EPSG:31983")
    sem.to_file(tmp / "sem_prj.shp", driver="ESRI Shapefile", engine="pyogrio")
    (tmp / "sem_prj.prj").unlink()
    zip_dir([p for p in sorted(tmp.glob("sem_prj.*"))], OUT / "sem_prj_shp.zip")

    # 7) Polígono inválido (gravata-borboleta) em GeoJSON
    bow = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"nome": "invalido"},
         "geometry": {"type": "Polygon", "coordinates": [[[-47.9, -15.8], [-47.89, -15.79], [-47.89, -15.8],
                                                          [-47.9, -15.79], [-47.9, -15.8]]]}},
        {"type": "Feature", "properties": {"nome": "valido"},
         "geometry": {"type": "Polygon", "coordinates": [[[-47.88, -15.8], [-47.87, -15.8], [-47.87, -15.79],
                                                          [-47.88, -15.79], [-47.88, -15.8]]]}}]}
    (OUT / "invalido.geojson").write_text(json.dumps(bow))

    # 8) Arquivo corrompido com extensão de GeoPackage
    (OUT / "corrompido.gpkg").write_bytes(b"isto nao e um geopackage" * 50)

    # 9) Raster 4 bandas (uint16), 100 x 100 px de 10 m, UTM 23S. Banda b vale b*1000 + coluna.
    data = np.zeros((4, 100, 100), dtype="uint16")
    for b in range(4):
        data[b] = (b + 1) * 1000 + np.arange(100, dtype="uint16")[None, :]
    with rasterio.open(OUT / "imagem_4bandas.tif", "w", driver="GTiff", width=100, height=100, count=4,
                       dtype="uint16", crs="EPSG:31983", transform=from_origin(X0, Y0 + 1000, 10, 10),
                       nodata=0) as ds:
        ds.write(data)
        ds.descriptions = ("azul", "verde", "vermelho", "infravermelho")

    # 10) Raster sem georreferência
    with rasterio.open(OUT / "sem_georref.tif", "w", driver="GTiff", width=10, height=10, count=1,
                       dtype="uint8") as ds:
        ds.write(np.ones((1, 10, 10), dtype="uint8"))

    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    print("Dados gerados em", OUT)
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:28s} {f.stat().st_size:>8d} bytes")


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    main()
