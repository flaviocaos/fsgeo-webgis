"""Infraestrutura de testes: PostGIS real, Celery em modo síncrono (executa de verdade, no mesmo processo),
armazenamento local em diretório temporário e tokens assinados como o Supabase assina."""
from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

import jwt
import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@/webgis_test?host=/tmp")
JWT_SECRET = "segredo-de-teste-com-pelo-menos-32-caracteres"
SUPABASE_URL = "http://supabase.teste"
_TMP = tempfile.mkdtemp(prefix="webgis-test-")

os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": TEST_DB,
    "CELERY_TASK_ALWAYS_EAGER": "true",
    "AUTH_MODE": "supabase",
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_JWT_SECRET": JWT_SECRET,
    "STORAGE_BACKEND": "local",
    "STORAGE_LOCAL_DIR": f"{_TMP}/storage",
    "WORK_DIR": f"{_TMP}/work",
    "URL_SIGNING_SECRET": "assinatura-teste",
    "PUBLIC_API_URL": "http://testserver",
})

FIXTURES = Path(__file__).parent / "fixtures"


def make_token(sub: str, email: str, *, secret: str = JWT_SECRET, exp_in: int = 3600, aud: str = "authenticated",
               iss: str = f"{SUPABASE_URL}/auth/v1") -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "email": email, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_in,
                       "role": "authenticated"}, secret, algorithm="HS256")


@pytest.fixture(scope="session", autouse=True)
def database():
    import psycopg
    with psycopg.connect(TEST_DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS app CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS layerdata CASCADE")
        conn.execute("DROP TABLE IF EXISTS public.schema_migrations")
        conn.execute("DELETE FROM spatial_ref_sys WHERE srid >= 910000")
    from app.db.migrate import migrate
    migrate(TEST_DB)
    yield
    from app.db.pool import close_pool
    close_pool()


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


class Api:
    """Cliente autenticado com atalhos para os fluxos mais usados nos testes."""

    def __init__(self, client, email: str):
        self.c = client
        self.email = email
        self.h = {"Authorization": f"Bearer {make_token(f'user-{email}', email)}"}

    def get(self, url, **kw):
        return self.c.get(url, headers=self.h, **kw)

    def post(self, url, **kw):
        return self.c.post(url, headers=self.h, **kw)

    def patch(self, url, **kw):
        return self.c.patch(url, headers=self.h, **kw)

    def put(self, url, **kw):
        return self.c.put(url, headers=self.h, **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self.h, **kw)

    def project(self, nome="Projeto teste", crs="EPSG:4326") -> dict:
        r = self.post("/api/v1/projects", json={"nome": nome, "crs": crs})
        assert r.status_code == 201, r.text
        return r.json()

    def upload(self, project_id: str, path: Path, part_size: int | None = None) -> str:
        data = path.read_bytes()
        r = self.post(f"/api/v1/projects/{project_id}/uploads", json={"nome_arquivo": path.name, "tamanho": len(data)})
        assert r.status_code == 201, r.text
        up = r.json()
        ps = up["tamanho_parte"]
        for i in range(up["partes"]):
            rr = self.put(f"/api/v1/uploads/{up['id']}/parts/{i + 1}", content=data[i * ps:(i + 1) * ps])
            assert rr.status_code == 200, rr.text
        rc = self.post(f"/api/v1/uploads/{up['id']}/complete")
        assert rc.status_code == 200, rc.text
        return rc.json()["dataset_id"]

    def import_files(self, project_id: str, *names: str) -> dict:
        ids = [self.upload(project_id, FIXTURES / n) for n in names]
        r = self.post(f"/api/v1/projects/{project_id}/imports", json={"datasets": ids})
        assert r.status_code == 202, r.text
        return r.json()

    def import_layer(self, project_id: str, name: str) -> dict:
        job = self.import_files(project_id, name)
        assert job["status"] == "succeeded", job
        return self.get(f"/api/v1/layers/{job['resultado']['camadas'][0]['id']}").json()

    def run_tool(self, project_id: str, tool: str, **params) -> dict:
        r = self.post(f"/api/v1/projects/{project_id}/tools/{tool}/run", json={"parametros": params})
        assert r.status_code == 202, r.text
        return r.json()


@pytest.fixture()
def api(client):
    return Api(client, f"ana-{uuid.uuid4().hex[:8]}@exemplo.com.br")


@pytest.fixture()
def other(client):
    return Api(client, f"bruno-{uuid.uuid4().hex[:8]}@exemplo.com.br")
