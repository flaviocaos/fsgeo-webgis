"""Editor vetorial: transações, tipos, validação, histórico e concorrência."""
import pytest

SQUARE = {"type": "Polygon", "coordinates": [[[-47.90, -15.80], [-47.89, -15.80], [-47.89, -15.79],
                                              [-47.90, -15.79], [-47.90, -15.80]]]}
BOWTIE = {"type": "Polygon", "coordinates": [[[-47.90, -15.80], [-47.89, -15.79], [-47.89, -15.80],
                                              [-47.90, -15.79], [-47.90, -15.80]]]}


def new_layer(api, project_id, geometria="Polygon", crs="EPSG:31983", campos=None):
    r = api.post(f"/api/v1/projects/{project_id}/layers", json={
        "nome": f"Camada {geometria}", "geometria": geometria, "crs": crs,
        "campos": campos if campos is not None else [{"nome": "nome", "tipo": "text"},
                                                     {"nome": "area_m2", "tipo": "real"},
                                                     {"nome": "classe", "tipo": "integer"}]})
    assert r.status_code == 201, r.text
    return r.json()


def edits(api, layer_id, **body):
    return api.post(f"/api/v1/layers/{layer_id}/edits", json=body)


def test_create_empty_layer_uses_project_crs(api):
    p = api.project(crs="EPSG:4674")
    r = api.post(f"/api/v1/projects/{p['id']}/layers", json={"nome": "Pontos", "geometria": "Point"})
    assert r.status_code == 201
    assert r.json()["crs"] == "EPSG:4674" and r.json()["feicoes"] == 0 and r.json()["editavel"]


def test_create_point_line_polygon_and_read_back(api):
    p = api.project()
    for gtype, geom in [("Point", {"type": "Point", "coordinates": [-47.9, -15.8]}),
                        ("LineString", {"type": "LineString", "coordinates": [[-47.9, -15.8], [-47.8, -15.7]]}),
                        ("Polygon", SQUARE)]:
        layer = new_layer(api, p["id"], gtype)
        r = edits(api, layer["id"], criar=[{"ref": "t1", "geometria": geom, "atributos": {"nome": "x", "classe": "3"}}])
        assert r.status_code == 200, r.text
        fid = r.json()["criadas"]["t1"]
        f = api.get(f"/api/v1/layers/{layer['id']}/features", params={"fids": str(fid)}).json()["features"][0]
        assert f["geometry"]["type"] == gtype
        assert f["properties"] == {"nome": "x", "area_m2": None, "classe": 3}
        # Ida e volta UTM ↔ WGS 84 preserva a coordenada (< 1e-8 grau ≈ 1 mm)
        first = f["geometry"]["coordinates"]
        while isinstance(first[0], list):
            first = first[0]
        assert abs(first[0] + 47.9) < 1e-8 and abs(first[1] + 15.8) < 1e-8


def test_single_part_geometry_goes_into_multi_layer(api):
    p = api.project()
    layer = new_layer(api, p["id"], "MultiPolygon")
    r = edits(api, layer["id"], criar=[{"ref": "a", "geometria": SQUARE}])
    assert r.status_code == 200
    f = api.get(f"/api/v1/layers/{layer['id']}/features").json()["features"][0]
    assert f["geometry"]["type"] == "MultiPolygon"


def test_wrong_geometry_type_is_rejected(api):
    p = api.project()
    layer = new_layer(api, p["id"], "Polygon")
    r = edits(api, layer["id"], criar=[{"ref": "p", "geometria": {"type": "Point", "coordinates": [-47.9, -15.8]}}])
    assert r.status_code == 422
    assert "incompatível" in r.json()["erro"]["detalhes"][0]["erro"]


def test_invalid_geometry_rejected_then_fixed_on_request(api):
    p = api.project()
    layer = new_layer(api, p["id"], "MultiPolygon")
    r = edits(api, layer["id"], criar=[{"ref": "b", "geometria": BOWTIE}])
    assert r.status_code == 422
    det = r.json()["erro"]["detalhes"][0]
    assert det["ref"] == "b" and det["corrigivel"] is True and "Self-intersection" in det["erro"]
    r = edits(api, layer["id"], criar=[{"ref": "b", "geometria": BOWTIE}], corrigir_invalidas=True)
    assert r.status_code == 200, r.text
    f = api.get(f"/api/v1/layers/{layer['id']}/features").json()["features"][0]
    assert f["geometry"]["type"] == "MultiPolygon" and len(f["geometry"]["coordinates"]) == 2


def test_batch_is_all_or_nothing(api):
    p = api.project()
    layer = new_layer(api, p["id"])
    r = edits(api, layer["id"], criar=[
        {"ref": "ok", "geometria": SQUARE, "atributos": {"nome": "bom"}},
        {"ref": "ruim", "geometria": SQUARE, "atributos": {"classe": "abc"}}])
    assert r.status_code == 422
    assert r.json()["erro"]["detalhes"][0]["ref"] == "ruim"
    info = api.get(f"/api/v1/layers/{layer['id']}").json()
    assert info["feicoes"] == 0 and info["versao"] == layer["versao"]


def test_update_move_and_delete_with_history(api):
    p = api.project()
    layer = new_layer(api, p["id"])
    c = edits(api, layer["id"], criar=[{"ref": "a", "geometria": SQUARE, "atributos": {"nome": "antes"}},
                                       {"ref": "b", "geometria": SQUARE, "atributos": {"nome": "apagar"}}]).json()
    fa, fb = c["criadas"]["a"], c["criadas"]["b"]
    moved = {"type": "Polygon", "coordinates": [[[x + 0.01, y] for x, y in SQUARE["coordinates"][0]]]}
    r = edits(api, layer["id"], versao_base=c["versao"],
              atualizar=[{"fid": fa, "geometria": moved, "atributos": {"nome": "depois", "area_m2": 12.5}}],
              excluir=[fb])
    assert r.status_code == 200, r.text
    assert r.json()["alteradas"] == 1 and r.json()["excluidas"] == 1
    feats = api.get(f"/api/v1/layers/{layer['id']}/features").json()["features"]
    assert len(feats) == 1 and feats[0]["properties"]["nome"] == "depois"
    assert abs(feats[0]["geometry"]["coordinates"][0][0][0] - (-47.89)) < 1e-8
    hist = api.get(f"/api/v1/layers/{layer['id']}/edits").json()
    assert [h["operacao"] for h in hist][:2] == ["delete", "update"]
    assert {h["operacao"] for h in hist} == {"insert", "update", "delete"}


def test_version_conflict_between_two_editors(api, other):
    p = api.project()
    api.post(f"/api/v1/projects/{p['id']}/members", json={"email": other.email, "papel": "editor"})
    other.get("/api/v1/me")  # garante que o usuário existe (login)
    r = api.post(f"/api/v1/projects/{p['id']}/members", json={"email": other.email, "papel": "editor"})
    assert r.status_code == 201, r.text
    layer = new_layer(api, p["id"])
    base = layer["versao"]
    assert edits(api, layer["id"], versao_base=base, criar=[{"ref": "a", "geometria": SQUARE}]).status_code == 200
    r = edits(other, layer["id"], versao_base=base, criar=[{"ref": "b", "geometria": SQUARE}])
    assert r.status_code == 409 and r.json()["erro"]["codigo"] == "conflito_versao"


def test_viewer_cannot_edit(api, other):
    p = api.project()
    other.get("/api/v1/me")
    api.post(f"/api/v1/projects/{p['id']}/members", json={"email": other.email, "papel": "viewer"})
    layer = new_layer(api, p["id"])
    assert other.get(f"/api/v1/layers/{layer['id']}/features").status_code == 200
    r = edits(other, layer["id"], criar=[{"ref": "a", "geometria": SQUARE}])
    assert r.status_code == 403


def test_unknown_field_and_deleted_feature_errors(api):
    p = api.project()
    layer = new_layer(api, p["id"])
    r = edits(api, layer["id"], criar=[{"ref": "a", "geometria": SQUARE, "atributos": {"inexistente": 1}}])
    assert r.status_code == 422 and "não existe" in r.json()["erro"]["detalhes"][0]["erro"]
    r = edits(api, layer["id"], excluir=[999999])
    assert r.status_code == 422


@pytest.mark.parametrize("valor,esperado", [("10", 10), (7, 7), (None, None), ("", None)])
def test_integer_coercion(api, valor, esperado):
    p = api.project()
    layer = new_layer(api, p["id"])
    fid = edits(api, layer["id"], criar=[{"ref": "a", "geometria": SQUARE, "atributos": {"classe": valor}}]).json()["criadas"]["a"]
    f = api.get(f"/api/v1/layers/{layer['id']}/features", params={"fids": fid}).json()["features"][0]
    assert f["properties"]["classe"] == esperado


def test_tile_cache_version_bumps_on_edit(api):
    p = api.project()
    layer = new_layer(api, p["id"])
    v0 = api.get(f"/api/v1/layers/{layer['id']}").json()["versao"]
    edits(api, layer["id"], criar=[{"ref": "a", "geometria": SQUARE}])
    assert api.get(f"/api/v1/layers/{layer['id']}").json()["versao"] == v0 + 1
