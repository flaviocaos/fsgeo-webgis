"""Geoprocessamento: resultados conferidos contra valores analíticos.

Geometrias de referência (tests/fixtures, gerados por scripts/gerar_dados_teste.py):
- quadrado_31983: 1 quadrado de 100 m x 100 m em SIRGAS 2000 / UTM 23S
- lotes (WGS 84): 4 quadrados de 100 m lado a lado (A, B na quadra 1; C, D na quadra 2)
- zona_31983: retângulo que cobre a metade direita de A e a metade esquerda de B
"""
import math
import threading
import time

import pytest

from tests.integration.helpers import area_m2, scalar


@pytest.fixture()
def proj(api):
    p = api.project()
    p["lotes"] = api.import_layer(p["id"], "lotes.geojson")
    p["zona"] = api.import_layer(p["id"], "zona_31983.gpkg")
    return p


def done(job):
    assert job["status"] == "succeeded", job
    return job["resultado"]["camada"]["id"]


def test_buffer_area_matches_analytic_value(api):
    p = api.project()
    sq = api.import_layer(p["id"], "quadrado_31983.gpkg")
    out = done(api.run_tool(p["id"], "vector.buffer", camada=sq["id"], distancia=10, unidade="m", segmentos=8))
    # Área exata = 100² + 4·100·10 + π·10² = 14314,16 m². Com 8 segmentos por quarto de círculo,
    # o arco vira polígono de 32 lados: 10000 + 4000 + 16·100·sen(π/16) = 14312,15 m².
    expected_poly = 10000 + 4000 + 16 * 100 * math.sin(2 * math.pi / 32)
    assert area_m2(out) == pytest.approx([expected_poly], abs=0.01)
    assert area_m2(out)[0] < 10000 + 4000 + math.pi * 100


def test_buffer_in_geographic_layer_uses_utm_and_reports_it(api, proj):
    job = api.run_tool(proj["id"], "vector.buffer", camada=proj["lotes"]["id"], distancia=10)
    out = done(job)
    assert any("UTM" in m["texto"] for m in job["mensagens"])
    for a in area_m2(out):
        assert a == pytest.approx(14312.15, rel=2e-3)
    info = api.get(f"/api/v1/layers/{out}").json()
    assert info["crs"] == "EPSG:4326" and info["geometria"] == "MultiPolygon" and info["feicoes"] == 4
    assert {c["nome"] for c in info["campos"]} == {c["nome"] for c in proj["lotes"]["campos"]}


def test_buffer_dissolve_and_km(api):
    p = api.project()
    sq = api.import_layer(p["id"], "quadrado_31983.gpkg")
    out = done(api.run_tool(p["id"], "vector.buffer", camada=sq["id"], distancia=0.01, unidade="km",
                            dissolver=True))
    assert len(area_m2(out)) == 1
    assert area_m2(out)[0] == pytest.approx(14312.15, abs=0.5)


def test_negative_buffer_on_polygon(api):
    p = api.project()
    sq = api.import_layer(p["id"], "quadrado_31983.gpkg")
    out = done(api.run_tool(p["id"], "vector.buffer", camada=sq["id"], distancia=-10))
    assert area_m2(out) == pytest.approx([80 * 80], abs=0.01)


def test_clip_keeps_only_inside_parts(api, proj):
    out = done(api.run_tool(proj["id"], "vector.clip", camada=proj["lotes"]["id"], recorte=proj["zona"]["id"]))
    areas = area_m2(out)
    assert len(areas) == 2
    assert areas == pytest.approx([5000, 5000], rel=1e-3)
    feats = api.get(f"/api/v1/layers/{out}/features", params={"ordenar": "nome"}).json()["features"]
    assert [f["properties"]["nome"] for f in feats] == ["Lote A", "Lote B"]


def test_intersection_carries_attributes_from_both(api, proj):
    job = api.run_tool(proj["id"], "vector.intersection", camada=proj["lotes"]["id"], sobreposicao=proj["zona"]["id"])
    out = done(job)
    assert any("reprojetada" in m["texto"] for m in job["mensagens"])
    feats = api.get(f"/api/v1/layers/{out}/features").json()["features"]
    assert len(feats) == 2
    assert all(f["properties"]["zona"] == "Zona 1" for f in feats)
    assert sum(area_m2(out)) == pytest.approx(10000, rel=1e-3)


def test_difference(api, proj):
    out = done(api.run_tool(proj["id"], "vector.difference", camada=proj["lotes"]["id"],
                            sobreposicao=proj["zona"]["id"]))
    areas = sorted(area_m2(out))
    assert areas == pytest.approx([5000, 5000, 10000, 10000], rel=1e-3)


def test_dissolve_by_field_and_all(api, proj):
    by = done(api.run_tool(proj["id"], "vector.dissolve", camada=proj["lotes"]["id"], campos=["quadra"]))
    feats = api.get(f"/api/v1/layers/{by}/features", params={"ordenar": "quadra"}).json()["features"]
    assert [f["properties"] for f in feats] == [{"quadra": 1}, {"quadra": 2}]
    assert area_m2(by) == pytest.approx([20000, 20000], rel=1e-3)
    allm = done(api.run_tool(proj["id"], "vector.dissolve", camada=proj["lotes"]["id"]))
    assert area_m2(allm) == pytest.approx([40000], rel=1e-3)


def test_centroid_position(api):
    p = api.project()
    sq = api.import_layer(p["id"], "quadrado_31983.gpkg")
    out = done(api.run_tool(p["id"], "vector.centroid", camada=sq["id"]))
    t = scalar("SELECT table_name FROM app.layers WHERE id=%s", out)
    x = scalar(f"SELECT ST_X(geom) FROM layerdata.{t}")
    y = scalar(f"SELECT ST_Y(geom) FROM layerdata.{t}")
    assert (x, y) == pytest.approx((190050.0, 8250050.0))


def test_multipart_to_singlepart(api):
    p = api.project()
    r = api.post(f"/api/v1/projects/{p['id']}/layers", json={"nome": "M", "geometria": "MultiPolygon",
                                                              "crs": "EPSG:4326", "campos": [{"nome": "n", "tipo": "integer"}]})
    lid = r.json()["id"]
    two = {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]]]}
    api.post(f"/api/v1/layers/{lid}/edits", json={"criar": [{"ref": "a", "geometria": two, "atributos": {"n": 7}}]})
    out = done(api.run_tool(p["id"], "vector.multipart_to_singlepart", camada=lid))
    info = api.get(f"/api/v1/layers/{out}").json()
    assert info["geometria"] == "Polygon" and info["feicoes"] == 2
    feats = api.get(f"/api/v1/layers/{out}/features").json()["features"]
    assert all(f["properties"]["n"] == 7 for f in feats)


def test_simplify_reduces_vertices(api):
    p = api.project()
    r = api.post(f"/api/v1/projects/{p['id']}/layers", json={"nome": "L", "geometria": "LineString", "crs": "EPSG:31983"})
    lid = r.json()["id"]
    # Linha quase reta com 101 vértices em coordenadas UTM (em WGS 84 na API)
    from pyproj import Transformer
    t = Transformer.from_crs(31983, 4326, always_xy=True)
    coords = [list(t.transform(190000 + i * 10, 8250000 + (0.2 if i % 2 else 0))) for i in range(101)]
    api.post(f"/api/v1/layers/{lid}/edits", json={"criar": [{"ref": "a", "geometria": {"type": "LineString",
                                                                                       "coordinates": coords}}]})
    job = api.run_tool(p["id"], "vector.simplify", camada=lid, tolerancia=1)
    done(job)
    st = job["resultado"]["estatisticas"]
    assert st["vertices_antes"] == 101 and st["vertices_depois"] == 2


def test_reproject_to_sirgas_utm(api, proj):
    job = api.run_tool(proj["id"], "vector.reproject", camada=proj["lotes"]["id"], crs="EPSG:31983")
    out = done(job)
    info = api.get(f"/api/v1/layers/{out}").json()
    assert info["crs"] == "EPSG:31983"
    assert area_m2(out) == pytest.approx([10000] * 4, rel=1e-4)
    assert any("Datums diferentes" in m["texto"] for m in job["mensagens"])


def test_fix_geometries_reports_and_repairs(api):
    p = api.project()
    bad = api.import_layer(p["id"], "invalido.geojson")
    job = api.run_tool(p["id"], "vector.fix_geometries", camada=bad["id"])
    out = done(job)
    st = job["resultado"]["estatisticas"]
    assert st["invalidas"] == 1 and st["exemplos"][0]["motivo"].startswith("Self-intersection")
    assert scalar(f"SELECT bool_and(ST_IsValid(geom)) FROM layerdata.l_{out.replace('-', '')}")


def test_tools_reject_bad_parameters(api, proj):
    j = api.run_tool(proj["id"], "vector.clip", camada=proj["lotes"]["id"], recorte=proj["lotes"]["id"] + "x")
    assert j["status"] == "failed" and "identificador inválido" in j["erro"]
    vias = api.import_layer(proj["id"], "vias_shp.zip")
    j = api.run_tool(proj["id"], "vector.clip", camada=proj["lotes"]["id"], recorte=vias["id"])
    assert j["status"] == "failed" and "não aceito" in j["erro"]
    j = api.run_tool(proj["id"], "vector.buffer", camada=vias["id"], distancia=-5)
    assert j["status"] == "failed" and "negativa" in j["erro"]
    r = api.post(f"/api/v1/projects/{proj['id']}/tools/vector.buffer/run", json={"parametros": {"camada": proj["lotes"]["id"]}})
    assert r.status_code == 400 and "Distância" in r.json()["erro"]["mensagem"]


def test_unavailable_tool_cannot_run(api, proj):
    cat = api.get("/api/v1/tools").json()
    union = next(t for t in cat if t["id"] == "vector.union")
    assert union["status"] == "indisponivel" and union["fase"] == 2
    r = api.post(f"/api/v1/projects/{proj['id']}/tools/vector.union/run", json={"parametros": {}})
    assert r.status_code == 409 and r.json()["erro"]["codigo"] == "ferramenta_indisponivel"


def test_tool_outputs_never_modify_inputs(api, proj):
    before = area_m2(proj["lotes"]["id"])
    done(api.run_tool(proj["id"], "vector.buffer", camada=proj["lotes"]["id"], distancia=50))
    assert area_m2(proj["lotes"]["id"]) == before


def test_running_query_can_be_cancelled(api, proj):
    """Cancela um job em execução: o pg_cancel_backend interrompe a consulta e o job termina como cancelado."""
    from app import jobs
    from app.db.pool import connection
    from app.workers import tasks

    with connection() as conn:
        job = jobs.create_job(conn, project_id=proj["id"], user_id=scalar("SELECT user_id FROM app.project_members "
                                                                         "WHERE project_id=%s", proj["id"]),
                              kind="tool", tool_id="vector.buffer", params={})

    def slow_body(conn, job_row, work):
        conn.execute("SELECT pg_sleep(30)")
        return {}, []

    th = threading.Thread(target=tasks._run, args=(str(job["id"]), slow_body))
    th.start()
    for _ in range(50):
        if api.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "running":
            break
        time.sleep(0.1)
    t0 = time.time()
    r = api.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert r.status_code == 200
    th.join(timeout=10)
    assert time.time() - t0 < 5
    final = api.get(f"/api/v1/jobs/{job['id']}").json()
    assert final["status"] == "cancelled"
