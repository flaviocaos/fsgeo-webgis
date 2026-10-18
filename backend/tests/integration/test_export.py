"""Exportação: arquivos reais, legíveis por GDAL, entregues por URL assinada e temporária."""
import zipfile
from urllib.parse import parse_qs, urlparse

import pyogrio
import pytest


def export(api, layer_id, fmt):
    job = api.post(f"/api/v1/layers/{layer_id}/export", json={"formato": fmt}).json()
    assert job["status"] == "succeeded", job
    url = api.get(f"/api/v1/exports/{job['resultado']['exportacao_id']}/url").json()["url"]
    return job, url


def download(client, url, tmp_path, name):
    u = urlparse(url)
    r = client.get(u.path + "?" + u.query)
    assert r.status_code == 200, r.text
    f = tmp_path / name
    f.write_bytes(r.content)
    return f


@pytest.fixture()
def lotes(api):
    p = api.project()
    return p, api.import_layer(p["id"], "lotes.geojson"), api.import_layer(p["id"], "vias_shp.zip")


def test_geojson_export_in_wgs84(api, client, lotes, tmp_path):
    _, _, vias = lotes
    job, url = export(api, vias["id"], "geojson")
    assert any("RFC 7946" in m["texto"] for m in job["mensagens"])
    f = download(client, url, tmp_path, "vias.geojson")
    info = pyogrio.read_info(f)
    assert info["features"] == 2 and info["crs"] == "EPSG:4326"


def test_geopackage_roundtrip_keeps_crs_and_types(api, client, lotes, tmp_path):
    _, lotes_l, vias = lotes
    _, url = export(api, vias["id"], "gpkg")
    f = download(client, url, tmp_path, "vias.gpkg")
    info = pyogrio.read_info(f)
    assert info["crs"] == "EPSG:31983" and info["features"] == 2
    _, url = export(api, lotes_l["id"], "gpkg")
    df = pyogrio.read_dataframe(download(client, url, tmp_path, "lotes.gpkg"))
    assert sorted(df["nome"]) == ["Lote A", "Lote B", "Lote C", "Lote D"]
    assert str(df["quadra"].dtype).startswith("int")


def test_shapefile_export_zip_truncates_names_with_message(api, client, tmp_path):
    p = api.project()
    r = api.post(f"/api/v1/projects/{p['id']}/layers", json={
        "nome": "Pontos de Coleta", "geometria": "Point", "crs": "EPSG:31983",
        "campos": [{"nome": "nome_do_responsavel", "tipo": "text"}, {"nome": "nome_do_responsavel_2", "tipo": "text"},
                   {"nome": "coletado_em", "tipo": "datetime"}]})
    lid = r.json()["id"]
    api.post(f"/api/v1/layers/{lid}/edits", json={"criar": [{"ref": "a", "geometria": {
        "type": "Point", "coordinates": [-47.9, -15.8]}, "atributos": {"nome_do_responsavel": "Ana",
                                                                     "coletado_em": "2024-05-01T10:30:00-03:00"}}]})
    job, url = export(api, lid, "shp")
    textos = " ".join(m["texto"] for m in job["mensagens"])
    assert "10 caracteres" in textos and "não suporta hora" in textos
    f = download(client, url, tmp_path, "pontos.zip")
    names = zipfile.ZipFile(f).namelist()
    assert {"Pontos_de_Coleta.shp", "Pontos_de_Coleta.shx", "Pontos_de_Coleta.dbf", "Pontos_de_Coleta.prj"} <= set(names)
    df = pyogrio.read_dataframe(f"/vsizip/{f}/Pontos_de_Coleta.shp")
    assert list(df.columns)[:3] == ["nome_do_re", "nome_do_r2", "coletado_e"] and df.iloc[0]["nome_do_re"] == "Ana"


def test_csv_and_raster_export(api, client, lotes, tmp_path):
    p, lotes_l, _ = lotes
    _, url = export(api, lotes_l["id"], "csv")
    text = download(client, url, tmp_path, "l.csv").read_text()
    assert text.splitlines()[0].startswith("wkt,nome") and text.count("POLYGON") == 4
    img = api.import_layer(p["id"], "imagem_4bandas.tif")
    _, url = export(api, img["id"], "geotiff")
    import rasterio
    with rasterio.open(download(client, url, tmp_path, "img.tif")) as ds:
        assert ds.count == 4 and ds.crs.to_epsg() == 31983
    r = api.post(f"/api/v1/layers/{img['id']}/export", json={"formato": "gpkg"})
    assert r.status_code == 400


def test_signed_url_tampering_and_expiry(api, client, lotes):
    _, _, vias = lotes
    _, url = export(api, vias["id"], "geojson")
    u = urlparse(url)
    q = parse_qs(u.query)
    bad_sig = u.path + f"?exp={q['exp'][0]}&sig={'0' * 64}&name=x"
    assert client.get(bad_sig).status_code == 403
    expired = u.path + f"?exp=1000&sig={q['sig'][0]}&name=x"
    assert client.get(expired).status_code == 403
    other_key = u.path.replace("exports", "uploads") + "?" + u.query
    assert client.get(other_key).status_code == 403


def test_export_url_requires_project_access(api, other, lotes):
    _, _, vias = lotes
    job = api.post(f"/api/v1/layers/{vias['id']}/export", json={"formato": "geojson"}).json()
    r = other.get(f"/api/v1/exports/{job['resultado']['exportacao_id']}/url")
    assert r.status_code == 404
