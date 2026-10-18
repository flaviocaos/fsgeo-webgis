"""Tabela de atributos, seleção, identificação e tiles."""
import json

import mapbox_vector_tile
import pytest
from rasterio.io import MemoryFile

from tests.integration.helpers import tile_xyz

LON, LAT = -47.8925, -15.809  # dentro dos lotes de teste


@pytest.fixture()
def lotes(api):
    p = api.project()
    return p, api.import_layer(p["id"], "lotes.geojson")


def feats(api, lid, **params):
    return api.get(f"/api/v1/layers/{lid}/features", params=params).json()


def flt(*conds, combinar="todas"):
    return json.dumps({"condicoes": [dict(zip(("campo", "operador", "valor"), c)) for c in conds],
                       "combinar": combinar})


def test_filter_sort_and_paginate(api, lotes):
    _, l = lotes
    r = feats(api, l["id"], filtro=flt(("quadra", "=", 1)), ordenar="nome", direcao="desc")
    assert r["total"] == 2 and [f["properties"]["nome"] for f in r["features"]] == ["Lote B", "Lote A"]
    r = feats(api, l["id"], filtro=flt(("nome", "contem", "c"), ("ativo", "=", "sim"), combinar="todas"))
    assert [f["properties"]["nome"] for f in r["features"]] == ["Lote C"]
    r = feats(api, l["id"], filtro=flt(("nome", "=", "Lote A"), ("nome", "=", "Lote D"), combinar="qualquer"))
    assert r["total"] == 2
    r = feats(api, l["id"], filtro=flt(("observacao", "nulo", None)))
    assert r["total"] == 2
    r = feats(api, l["id"], filtro=flt(("data_cadastro", ">=", "2024-03-01")))
    assert r["total"] == 2
    r = feats(api, l["id"], filtro=flt(("quadra", "em", [2, 3])))
    assert r["total"] == 2
    page = feats(api, l["id"], limite=3, deslocamento=3, geometria="false")
    assert page["total"] == 4 and len(page["features"]) == 1 and page["features"][0]["geometry"] is None


def test_filter_rejects_bad_input(api, lotes):
    _, l = lotes
    r = api.get(f"/api/v1/layers/{l['id']}/features", params={"filtro": flt(("quadra", "=", "abc"))})
    assert r.status_code == 400 and "incompatível" in r.json()["erro"]["mensagem"]
    r = api.get(f"/api/v1/layers/{l['id']}/features", params={"filtro": flt(("x; drop table", "=", 1))})
    assert r.status_code == 400
    r = api.get(f"/api/v1/layers/{l['id']}/features", params={"filtro": flt(("nome", "like", "%"))})
    assert r.status_code == 400


def test_like_wildcards_are_escaped(api, lotes):
    _, l = lotes
    r = feats(api, l["id"], filtro=flt(("nome", "contem", "%")))
    assert r["total"] == 0


def test_numeric_field_stats(api, lotes):
    _, l = lotes
    s = api.get(f"/api/v1/layers/{l['id']}/fields/quadra/stats").json()
    assert s["total"] == 4 and s["min"] == 1 and s["max"] == 2 and s["media"] == 1.5 and s["soma"] == 6
    assert {v["valor"] for v in s["mais_frequentes"]} == {1, 2}


def test_add_rename_delete_field(api, lotes):
    _, l = lotes
    r = api.post(f"/api/v1/layers/{l['id']}/fields", json={"nome": "proprietário", "tipo": "text"})
    assert r.status_code == 201 and "proprietário" in [c["nome"] for c in r.json()["campos"]]
    assert api.post(f"/api/v1/layers/{l['id']}/fields", json={"nome": "PROPRIETÁRIO", "tipo": "text"}).status_code == 400
    assert api.post(f"/api/v1/layers/{l['id']}/fields", json={"nome": "fid", "tipo": "text"}).status_code == 400
    r = api.patch(f"/api/v1/layers/{l['id']}/fields/proprietário", json={"novo_nome": "dono"})
    assert "dono" in [c["nome"] for c in r.json()["campos"]]
    fid = feats(api, l["id"])["features"][0]["id"]
    api.post(f"/api/v1/layers/{l['id']}/edits", json={"atualizar": [{"fid": fid, "atributos": {"dono": "Maria"}}]})
    assert feats(api, l["id"], fids=str(fid))["features"][0]["properties"]["dono"] == "Maria"
    r = api.delete(f"/api/v1/layers/{l['id']}/fields/dono")
    assert "dono" not in [c["nome"] for c in r.json()["campos"]]


def test_select_by_rectangle_polygon_and_attribute(api, lotes):
    _, l = lotes
    w, s, e, n = l["bbox"]
    left = w + (e - w) * 0.3  # cobre A e o comecinho de B
    r = api.post(f"/api/v1/layers/{l['id']}/select", json={"bbox": [w - 1e-4, s - 1e-4, left, n + 1e-4]}).json()
    assert len(r["fids"]) == 2
    poly = {"type": "Polygon", "coordinates": [[[w, s], [w + 1e-5, s], [w + 1e-5, n], [w, n], [w, s]]]}
    assert len(api.post(f"/api/v1/layers/{l['id']}/select", json={"geometria": poly}).json()["fids"]) == 1
    r = api.post(f"/api/v1/layers/{l['id']}/select", json={"filtro": {"condicoes": [
        {"campo": "ativo", "operador": "=", "valor": False}]}}).json()
    assert len(r["fids"]) == 1
    assert api.post(f"/api/v1/layers/{l['id']}/select", json={}).status_code == 400


def test_bbox_query_returns_only_visible_features(api, lotes):
    _, l = lotes
    w, s, e, n = l["bbox"]
    r = feats(api, l["id"], bbox=f"{w},{s},{w + (e - w) * 0.1},{n}")
    assert r["total"] == 1
    r = feats(api, l["id"], bbox="10,10,11,11")
    assert r["total"] == 0


def test_identify_vector_and_raster(api, lotes):
    p, l = lotes
    feats_ = api.get(f"/api/v1/layers/{l['id']}/identify", params={"lon": LON, "lat": LAT}).json()["feicoes"]
    assert len(feats_) >= 1 and feats_[0]["properties"]["nome"].startswith("Lote")
    assert feats_[0]["distancia_m"] == 0
    img = api.import_layer(p["id"], "imagem_4bandas.tif")
    # Pixel na coluna 5 (x = 190000 + 55 m) → banda b vale b*1000 + 5
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(31983, 4326, always_xy=True).transform(190055, 8250995)
    v = api.get(f"/api/v1/layers/{img['id']}/identify", params={"lon": lon, "lat": lat}).json()
    assert [b["valor"] for b in v["valores"]] == [1005, 2005, 3005, 4005]
    out = api.get(f"/api/v1/layers/{img['id']}/identify", params={"lon": 0, "lat": 0}).json()
    assert out["valores"] is None


def test_vector_tile_contains_features_and_attributes(api, lotes):
    _, l = lotes
    z, x, y = tile_xyz(LON, LAT, 15)
    r = api.get(f"/api/v1/layers/{l['id']}/tiles/{z}/{x}/{y}.pbf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/vnd.mapbox-vector-tile"
    decoded = mapbox_vector_tile.decode(r.content)
    fs = decoded["camada"]["features"]
    assert len(fs) == 4
    assert {f["properties"]["nome"] for f in fs} == {"Lote A", "Lote B", "Lote C", "Lote D"}
    assert all(isinstance(f["id"], int) for f in fs)
    assert api.get(f"/api/v1/layers/{l['id']}/tiles/15/0/0.pbf").status_code == 204
    assert api.get(f"/api/v1/layers/{l['id']}/tiles/3/99/0.pbf").status_code == 400


def test_vector_tile_for_utm_layer(api):
    p = api.project()
    vias = api.import_layer(p["id"], "vias_shp.zip")
    z, x, y = tile_xyz(LON, LAT, 14)
    r = api.get(f"/api/v1/layers/{vias['id']}/tiles/{z}/{x}/{y}.pbf")
    assert r.status_code == 200
    assert len(mapbox_vector_tile.decode(r.content)["camada"]["features"]) == 2
    # Tile do outro lado do mundo não quebra a transformação para UTM
    assert api.get(f"/api/v1/layers/{vias['id']}/tiles/5/30/10.pbf").status_code == 204


def test_raster_tile_png(api):
    p = api.project()
    img = api.import_layer(p["id"], "imagem_4bandas.tif")
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(31983, 4326, always_xy=True).transform(190500, 8250500)
    z, x, y = tile_xyz(lon, lat, 15)
    r = api.get(f"/api/v1/layers/{img['id']}/raster/{z}/{x}/{y}.png", params={"bandas": "3,2,1"})
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    with MemoryFile(r.content) as mf, mf.open() as ds:
        assert ds.count == 4  # RGB + alfa
        alpha = ds.read(4)
        assert alpha.max() == 255 and alpha.min() == 0   # parte do tile fora da imagem fica transparente
    r = api.get(f"/api/v1/layers/{img['id']}/raster/{z}/{x}/{y}.png", params={"bandas": "4", "paleta": "viridis"})
    assert r.status_code == 200
    assert api.get(f"/api/v1/layers/{img['id']}/raster/{z}/{x}/{y}.png", params={"bandas": "9"}).status_code == 400
    assert api.get(f"/api/v1/layers/{img['id']}/raster/5/0/0.png").status_code == 204


