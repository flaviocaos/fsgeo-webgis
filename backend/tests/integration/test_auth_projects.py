"""Autenticação (Supabase HS256 e JWKS, modo local), isolamento entre usuários e projetos."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import security
from app.core.config import Settings
from app.core.errors import APIError
from tests.conftest import SUPABASE_URL, make_token
from tests.integration.helpers import scalar, table_of


def test_requests_without_or_with_bad_tokens_are_rejected(client):
    assert client.get("/api/v1/projects").status_code == 401
    for tok in ["abc", make_token("u", "a@b.c", secret="outro-segredo-qualquer-com-32-chars!!"),
                make_token("u", "a@b.c", exp_in=-10), make_token("u", "a@b.c", aud="anon"),
                make_token("u", "a@b.c", iss="http://outro/auth/v1")]:
        r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 401, tok
    r = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {make_token('u', 'a@b.c', exp_in=-10)}"})
    assert "expirou" in r.json()["erro"]["mensagem"]


def test_asymmetric_supabase_token_via_jwks(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeJWKS:
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": key.public_key()})()

    monkeypatch.setattr(security, "_jwks_client", lambda url: FakeJWKS())
    now = int(time.time())
    tok = jwt.encode({"sub": "abc", "email": "x@y.z", "aud": "authenticated", "iss": f"{SUPABASE_URL}/auth/v1",
                      "exp": now + 60}, key, algorithm="RS256", headers={"kid": "k1"})
    s = Settings(auth_mode="supabase", supabase_url=SUPABASE_URL, supabase_jwt_secret="")
    ident = security.verify_token(tok, s)
    assert ident.external_id == "abc" and ident.email == "x@y.z"
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": "abc", "aud": "authenticated", "iss": f"{SUPABASE_URL}/auth/v1", "exp": now + 60},
                        other, algorithm="RS256")
    with pytest.raises(APIError):
        security.verify_token(forged, s)
    none_alg = jwt.encode({"sub": "abc", "aud": "authenticated", "exp": now + 60}, None, algorithm="none")
    with pytest.raises(APIError):
        security.verify_token(none_alg, s)


def test_local_mode_login_and_refused_in_production():
    s = Settings(auth_mode="local", environment="development", local_jwt_secret="x" * 40,
                 dev_user_email="dev@fs.com.br", dev_user_password="senha-forte")
    tok = security.local_login("DEV@fs.com.br", "senha-forte", s)
    assert security.verify_token(tok, s).email == "dev@fs.com.br"
    with pytest.raises(APIError) as e:
        security.local_login("dev@fs.com.br", "errada", s)
    assert e.value.status == 401
    prod = s.model_copy(update={"environment": "production"})
    with pytest.raises(APIError):
        security.local_login("dev@fs.com.br", "senha-forte", prod)
    with pytest.raises(APIError):
        security.verify_token(tok, prod)
    # Token local não vale no modo Supabase
    sb = Settings(auth_mode="supabase", supabase_url=SUPABASE_URL, supabase_jwt_secret="x" * 40)
    with pytest.raises(APIError):
        security.verify_token(tok, sb)


def test_projects_are_isolated_between_users(api, other):
    p = api.project("Privado")
    assert all(x["id"] != p["id"] for x in other.get("/api/v1/projects").json())
    assert other.get(f"/api/v1/projects/{p['id']}").status_code == 404
    layer = api.post(f"/api/v1/projects/{p['id']}/layers", json={"nome": "x", "geometria": "Point"}).json()
    assert other.get(f"/api/v1/layers/{layer['id']}/features").status_code == 404
    assert other.get(f"/api/v1/layers/{layer['id']}/tiles/0/0/0.pbf").status_code == 404
    assert other.delete(f"/api/v1/projects/{p['id']}").status_code == 404


def test_project_crs_validation_and_state(api):
    r = api.post("/api/v1/projects", json={"nome": "SIRGAS", "crs": "31983"})
    assert r.status_code == 201 and r.json()["crs"] == "EPSG:31983"
    assert api.post("/api/v1/projects", json={"nome": "x", "crs": "EPSG:999999"}).status_code == 400
    pid = r.json()["id"]
    estado = {"vista": {"centro": [-47.9, -15.8], "zoom": 14}, "mapa_base": "osm-vetorial",
              "servicos": [{"tipo": "wms", "url": "https://exemplo/wms", "camadas": "x"}]}
    r = api.patch(f"/api/v1/projects/{pid}", json={"estado": estado, "nome": "Renomeado"})
    assert r.json()["estado"] == estado and r.json()["nome"] == "Renomeado" and r.json()["versao"] == 2


def test_layer_order_visibility_and_style_are_saved(api):
    p = api.project()
    a = api.post(f"/api/v1/projects/{p['id']}/layers", json={"nome": "A", "geometria": "Point"}).json()
    b = api.post(f"/api/v1/projects/{p['id']}/layers", json={"nome": "B", "geometria": "Point"}).json()
    proj = api.get(f"/api/v1/projects/{p['id']}").json()
    assert [l["nome"] for l in proj["camadas"]] == ["B", "A"]   # mais recente no topo
    r = api.put(f"/api/v1/projects/{p['id']}/layers-state", json=[
        {"camada_id": a["id"], "posicao": 5, "visivel": False, "opacidade": 0.5, "grupo": "Base",
         "estilo": {"cor": "#ff0000", "raio": 6}},
        {"camada_id": b["id"], "posicao": 1}])
    assert r.status_code == 200
    proj = api.get(f"/api/v1/projects/{p['id']}").json()
    assert [l["nome"] for l in proj["camadas"]] == ["A", "B"]
    ex = proj["camadas"][0]["exibicao"]
    assert ex == {"posicao": 5, "grupo": "Base", "visivel": False, "opacidade": 0.5,
                  "estilo": {"cor": "#ff0000", "raio": 6}}


def test_duplicate_project_copies_data_independently(api):
    p = api.project()
    lotes = api.import_layer(p["id"], "lotes.geojson")
    api.import_layer(p["id"], "imagem_4bandas.tif")
    copy = api.post(f"/api/v1/projects/{p['id']}/duplicate").json()
    cp = api.get(f"/api/v1/projects/{copy['id']}").json()
    assert len(cp["camadas"]) == 2 and copy["nome"].endswith("(cópia)")
    c_lotes = next(l for l in cp["camadas"] if l["tipo"] == "vetorial")
    assert table_of(c_lotes["id"]) != table_of(lotes["id"])
    # Editar a cópia não altera o original, e os novos fid seguem a sequência própria
    fid = api.get(f"/api/v1/layers/{c_lotes['id']}/features").json()["features"][0]["id"]
    api.post(f"/api/v1/layers/{c_lotes['id']}/edits", json={"excluir": [fid]})
    r = api.post(f"/api/v1/layers/{c_lotes['id']}/edits", json={"criar": [{"ref": "n", "geometria": {
        "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}]})
    assert r.json()["criadas"]["n"] == 5
    assert api.get(f"/api/v1/layers/{lotes['id']}").json()["feicoes"] == 4


def test_delete_project_drops_tables(api):
    p = api.project()
    l = api.import_layer(p["id"], "lotes.geojson")
    t = table_of(l["id"])
    assert api.delete(f"/api/v1/projects/{p['id']}").status_code == 204
    assert scalar("SELECT to_regclass(%s) IS NULL", f"layerdata.{t}")


def test_audit_log_records_actions(api):
    p = api.project()
    api.import_layer(p["id"], "lotes.geojson")
    n = scalar("SELECT count(*) FROM app.audit_log WHERE resource_id=%s", p["id"])
    assert n >= 2


def test_crs_endpoints(api):
    r = api.get("/api/v1/crs/search", params={"q": "31983"}).json()
    assert r[0]["codigo"] == "EPSG:31983" and "SIRGAS 2000" in r[0]["nome"]
    assert any(c["codigo"] == "EPSG:4674" for c in api.get("/api/v1/crs/search").json())
    t = api.post("/api/v1/crs/transform", json={"de": "EPSG:31983", "para": "EPSG:4674",
                                                  "coordenadas": [[190000, 8250000]]}).json()
    lon, lat = t["coordenadas"][0]
    assert -48.0 < lon < -47.8 and -15.9 < lat < -15.7
    t = api.post("/api/v1/crs/transform", json={"de": "EPSG:4674", "para": "EPSG:4618", "coordenadas": [[-47.9, -15.8]]}).json()
    assert "Datums diferentes" in t["aviso_datum"]
    info = api.get("/api/v1/crs/EPSG:31983").json()
    assert info["unidade"] == "metre" and info["geografico"] is False


def test_health(client):
    assert client.get("/health").json()["postgis"].startswith("3.")
