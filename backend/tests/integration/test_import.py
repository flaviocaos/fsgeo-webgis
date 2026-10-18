"""Importação: formatos aceitos, CRS, avisos e erros claros."""
from tests.conftest import FIXTURES


def test_geojson_import_preserves_attributes_and_types(api):
    p = api.project()
    layer = api.import_layer(p["id"], "lotes.geojson")
    assert layer["tipo"] == "vetorial"
    assert layer["geometria"] == "Polygon"
    assert layer["crs"] == "EPSG:4326"
    assert layer["feicoes"] == 4
    tipos = {c["nome"]: c["tipo"] for c in layer["campos"]}
    assert tipos == {"nome": "text", "quadra": "integer", "area_ha": "real", "ativo": "boolean",
                     "data_cadastro": "date", "observacao": "text"}
    feats = api.get(f"/api/v1/layers/{layer['id']}/features", params={"ordenar": "nome"}).json()
    assert [f["properties"]["nome"] for f in feats["features"]] == ["Lote A", "Lote B", "Lote C", "Lote D"]
    assert feats["features"][0]["properties"]["data_cadastro"] == "2024-01-15"
    assert feats["features"][1]["properties"]["observacao"] is None
    w, s, e, n = layer["bbox"]
    assert -48 < w < e < -47 and -16 < s < n < -15


def test_shapefile_zip_keeps_utm_crs(api):
    p = api.project()
    layer = api.import_layer(p["id"], "vias_shp.zip")
    assert layer["crs"] == "EPSG:31983"
    assert layer["geometria"] == "LineString"
    assert {c["nome"] for c in layer["campos"]} == {"nome_da_vi", "largura_m"}  # Shapefile limita nomes a 10 caracteres
    assert layer["feicoes"] == 2


def test_loose_shapefile_parts_import_together(api, tmp_path):
    import zipfile
    with zipfile.ZipFile(FIXTURES / "vias_shp.zip") as zf:
        zf.extractall(tmp_path)
    p = api.project()
    ids = [api.upload(p["id"], f) for f in sorted(tmp_path.iterdir())]
    job = api.post(f"/api/v1/projects/{p['id']}/imports", json={"datasets": ids}).json()
    assert job["status"] == "succeeded", job
    assert job["resultado"]["camadas"][0]["feicoes"] == 2


def test_geopackage_sirgas_geographic(api):
    p = api.project()
    layer = api.import_layer(p["id"], "nascentes.gpkg")
    assert layer["crs"] == "EPSG:4674"
    assert layer["geometria"] == "Point"
    assert layer["feicoes"] == 3


def test_shapefile_without_prj_is_imported_with_undefined_crs(api):
    p = api.project()
    job = api.import_files(p["id"], "sem_prj_shp.zip")
    assert job["status"] == "succeeded"
    textos = " ".join(m["texto"] for m in job["mensagens"])
    assert ".prj" in textos
    layer = api.get(f"/api/v1/layers/{job['resultado']['camadas'][0]['id']}").json()
    assert layer["crs"] is None and layer["editavel"] is False
    # Ferramentas recusam camada sem CRS
    j = api.run_tool(p["id"], "vector.buffer", camada=layer["id"], distancia=5)
    assert j["status"] == "failed" and "sistema de referência" in j["erro"]
    # Definir o CRS libera a camada
    r = api.post(f"/api/v1/layers/{layer['id']}/crs", json={"crs": "EPSG:31983"})
    assert r.status_code == 200, r.text
    assert r.json()["crs"] == "EPSG:31983" and r.json()["editavel"] is True


def test_corrupted_file_fails_with_clear_message(api):
    p = api.project()
    job = api.import_files(p["id"], "corrompido.gpkg")
    assert job["status"] == "failed"
    assert "corrompido" in job["erro"]


def test_invalid_geometry_is_imported_and_reported(api):
    p = api.project()
    job = api.import_files(p["id"], "invalido.geojson")
    assert job["status"] == "succeeded"
    assert any("inválida" in m["texto"] for m in job["mensagens"])


def test_unsupported_format_is_reported_as_planned(api, tmp_path):
    f = tmp_path / "pontos.kml"
    f.write_text("<kml></kml>")
    p = api.project()
    ds = api.upload(p["id"], f)
    job = api.post(f"/api/v1/projects/{p['id']}/imports", json={"datasets": [ds]}).json()
    assert job["status"] == "failed"
    assert "KML" in job["erro"] and "ainda não suportado" in job["erro"]


def test_geotiff_import_creates_cog_with_stats(api):
    p = api.project()
    layer = api.import_layer(p["id"], "imagem_4bandas.tif")
    assert layer["tipo"] == "raster"
    assert layer["crs"] == "EPSG:31983"
    r = layer["raster"]
    assert r["bandas"] == 4 and r["largura"] == 100 and r["resolucao"] == [10.0, 10.0]
    b1 = r["estatisticas"][0]
    assert b1["min"] == 1000 and b1["max"] == 1099


def test_geotiff_without_georeference_is_rejected(api):
    p = api.project()
    job = api.import_files(p["id"], "sem_georref.tif")
    assert job["status"] == "failed"
    assert "sistema de referência" in job["erro"] or "georreferenciado" in job["erro"]


def test_multipart_upload_with_small_parts(api, monkeypatch):
    from app.api.v1 import uploads
    monkeypatch.setattr(uploads, "PART_SIZE", 1000)
    p = api.project()
    ds = api.upload(p["id"], FIXTURES / "imagem_4bandas.tif")
    job = api.post(f"/api/v1/projects/{p['id']}/imports", json={"datasets": [ds]}).json()
    assert job["status"] == "succeeded", job


def test_zip_with_path_traversal_is_rejected(api, tmp_path):
    import zipfile
    bad = tmp_path / "ruim.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../../fora.geojson", "{}")
    p = api.project()
    ds = api.upload(p["id"], bad)
    job = api.post(f"/api/v1/projects/{p['id']}/imports", json={"datasets": [ds]}).json()
    assert job["status"] == "failed" and "Caminho inválido" in job["erro"]
