"""Upload em partes e disparo de importação."""
from __future__ import annotations

import hashlib
import math
import re
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.deps import CurrentUser, UserDep, audit, require_project
from app.core.errors import APIError, bad_request, not_found
from app.db.pool import connection
from app.jobs import create_job, public_job
from app.storage import get_storage
from app.workers.tasks import enqueue

router = APIRouter(tags=["upload e importação"])
PART_SIZE = 8 * 1024 * 1024


class UploadCreate(BaseModel):
    nome_arquivo: str = Field(min_length=1, max_length=255)
    tamanho: int = Field(gt=0)


class ImportRequest(BaseModel):
    datasets: list[UUID] = Field(min_length=1, max_length=20)


def _clean_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ()]+", "_", base, flags=re.UNICODE).strip(" .")
    if not base:
        raise bad_request("Nome de arquivo inválido.")
    return base[:200]


def _parts_dir(upload_id) -> Path:
    d = Path(get_settings().work_dir).resolve() / "uploads" / str(upload_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/projects/{project_id}/uploads", status_code=201)
def create_upload(project_id: UUID, body: UploadCreate, user: CurrentUser = UserDep):
    s = get_settings()
    if body.tamanho > s.max_upload_mb * 1024 * 1024:
        raise APIError(413, "arquivo_grande", f"O arquivo excede o limite de {s.max_upload_mb} MB.")
    with connection() as conn:
        require_project(conn, project_id, user, "editor")
        used = conn.execute("SELECT COALESCE(SUM(size_bytes),0) AS n FROM app.datasets WHERE uploaded_by=%s",
                            (user.id,)).fetchone()["n"]
        if used + body.tamanho > s.storage_quota_mb * 1024 * 1024:
            raise APIError(413, "cota_excedida",
                           f"Cota de armazenamento excedida ({s.storage_quota_mb} MB por usuário).")
        parts = max(1, math.ceil(body.tamanho / PART_SIZE))
        row = conn.execute(
            "INSERT INTO app.uploads (project_id, user_id, filename, total_size, part_count) VALUES (%s,%s,%s,%s,%s) "
            "RETURNING id", (project_id, user.id, _clean_name(body.nome_arquivo), body.tamanho, parts)).fetchone()
    return {"id": str(row["id"]), "tamanho_parte": PART_SIZE, "partes": parts}


def _get_open_upload(conn, upload_id, user) -> dict:
    up = conn.execute("SELECT * FROM app.uploads WHERE id=%s", (upload_id,)).fetchone()
    if not up or up["user_id"] != user.id:
        raise not_found("Upload")
    if up["status"] != "open":
        raise bad_request("Este upload já foi concluído.")
    return up


@router.put("/uploads/{upload_id}/parts/{n}")
async def put_part(upload_id: UUID, n: int, request: Request, user: CurrentUser = UserDep):
    with connection() as conn:
        up = _get_open_upload(conn, upload_id, user)
    if not 1 <= n <= up["part_count"]:
        raise bad_request("Número de parte inválido.")
    expected = PART_SIZE if n < up["part_count"] else up["total_size"] - PART_SIZE * (up["part_count"] - 1)
    path = _parts_dir(upload_id) / f"{n:06d}.part"
    size = 0
    with open(path, "wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > expected:
                f.close()
                path.unlink(missing_ok=True)
                raise bad_request("Parte maior que o esperado.")
            f.write(chunk)
    if size != expected:
        path.unlink(missing_ok=True)
        raise bad_request(f"Parte {n} incompleta: recebidos {size} de {expected} bytes.")
    return {"parte": n, "bytes": size}


@router.post("/uploads/{upload_id}/complete")
def complete_upload(upload_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        up = _get_open_upload(conn, upload_id, user)
        require_project(conn, up["project_id"], user, "editor")
    d = _parts_dir(upload_id)
    missing = [i for i in range(1, up["part_count"] + 1) if not (d / f"{i:06d}.part").exists()]
    if missing:
        raise bad_request(f"Faltam partes: {missing[:10]}")
    final = d / up["filename"]
    sha = hashlib.sha256()
    with open(final, "wb") as out:
        for i in range(1, up["part_count"] + 1):
            p = d / f"{i:06d}.part"
            with open(p, "rb") as src:
                while chunk := src.read(1024 * 1024):
                    sha.update(chunk)
                    out.write(chunk)
            p.unlink()
    size = final.stat().st_size
    if size != up["total_size"]:
        shutil.rmtree(d, ignore_errors=True)
        raise bad_request("Tamanho final diferente do declarado.")
    with connection() as conn:
        ds = conn.execute(
            "INSERT INTO app.datasets (project_id, uploaded_by, original_name, storage_key, size_bytes, sha256) "
            "VALUES (%s,%s,%s,'',%s,%s) RETURNING id", (up["project_id"], user.id, up["filename"], size,
                                                       sha.hexdigest())).fetchone()
        key = f"projects/{up['project_id']}/uploads/{ds['id']}/{up['filename']}"
        get_storage().put_file(final, key)
        conn.execute("UPDATE app.datasets SET storage_key=%s WHERE id=%s", (key, ds["id"]))
        conn.execute("UPDATE app.uploads SET status='complete' WHERE id=%s", (upload_id,))
        audit(conn, user, "upload", "dataset", ds["id"], {"arquivo": up["filename"], "bytes": size})
    shutil.rmtree(d, ignore_errors=True)
    return {"dataset_id": str(ds["id"]), "arquivo": up["filename"], "tamanho": size, "sha256": sha.hexdigest()}


@router.post("/projects/{project_id}/imports", status_code=202)
def start_import(project_id: UUID, body: ImportRequest, user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user, "editor")
        found = conn.execute("SELECT count(*) AS n FROM app.datasets WHERE id = ANY(%s) AND project_id=%s",
                             (body.datasets, project_id)).fetchone()["n"]
        if found != len(set(body.datasets)):
            raise not_found("Arquivo enviado")
        job = create_job(conn, project_id=project_id, user_id=user.id, kind="import", tool_id=None,
                         params={"dataset_ids": [str(d) for d in body.datasets]})
        audit(conn, user, "importar", "projeto", project_id, {"job": str(job["id"])})
    enqueue(job)
    with connection() as conn:
        job = conn.execute("SELECT * FROM app.jobs WHERE id=%s", (job["id"],)).fetchone()
    return public_job(job)
