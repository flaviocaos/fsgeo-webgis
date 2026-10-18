"""Catálogo de ferramentas, execução, jobs (status, progresso, cancelamento) e exportação."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.deps import CurrentUser, UserDep, audit, require_layer, require_project
from app.core.errors import APIError, bad_request, not_found
from app.db.pool import connection
from app.jobs import TERMINAL, create_job, get_job, public_job
from app.storage import check_local_signature, get_storage
from app.workers.celery_app import celery_app
from app.workers.tasks import enqueue
from geo.io.export import FORMATS
from geo.registry import catalog, get_tool

router = APIRouter(tags=["ferramentas e jobs"])


class RunTool(BaseModel):
    parametros: dict[str, Any]


class ExportRequest(BaseModel):
    formato: str


def _job_for_user(conn, job_id: UUID, user: CurrentUser, min_role: str = "viewer") -> dict:
    job = conn.execute("SELECT * FROM app.jobs WHERE id=%s", (job_id,)).fetchone()
    if not job:
        raise not_found("Processamento")
    require_project(conn, job["project_id"], user, min_role)
    return job


def _start(conn_job: dict) -> dict:
    enqueue(conn_job)
    return public_job(get_job(conn_job["id"]))


@router.get("/tools")
def list_tools(user: CurrentUser = UserDep):
    return catalog()


@router.post("/projects/{project_id}/tools/{tool_id}/run", status_code=202)
def run_tool(project_id: UUID, tool_id: str, body: RunTool, user: CurrentUser = UserDep):
    tool = get_tool(tool_id)
    if tool is None:
        raise not_found("Ferramenta")
    if tool["status"] != "disponivel":
        raise APIError(409, "ferramenta_indisponivel", f"'{tool['nome']}' ainda não está disponível "
                                                      f"(prevista para a Fase {tool['fase']}).")
    with connection() as conn:
        require_project(conn, project_id, user, "editor")
        for p in tool["parametros"]:
            if p.get("obrigatorio") and body.parametros.get(p["nome"]) in (None, ""):
                raise bad_request(f"Parâmetro obrigatório ausente: {p['rotulo']}.")
        job = create_job(conn, project_id=project_id, user_id=user.id, kind="tool", tool_id=tool_id,
                         params=body.parametros)
        audit(conn, user, "executar", "ferramenta", tool_id, {"job": str(job["id"])})
    return _start(job)


@router.get("/projects/{project_id}/jobs")
def list_jobs(project_id: UUID, limite: int = Query(default=30, ge=1, le=200), user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user)
        rows = conn.execute("SELECT * FROM app.jobs WHERE project_id=%s ORDER BY created_at DESC LIMIT %s",
                            (project_id, limite)).fetchall()
    return [public_job(r) for r in rows]


@router.get("/jobs/{job_id}")
def job_status(job_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        return public_job(_job_for_user(conn, job_id, user))


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: UUID, user: CurrentUser = UserDep):
    """Progresso por Server-Sent Events até o job terminar."""
    with connection() as conn:
        _job_for_user(conn, job_id, user)

    async def stream():
        last = None
        for _ in range(3 * 3600):
            row = await asyncio.to_thread(get_job, job_id)
            data = public_job(row)
            snapshot = (data["status"], data["progresso"], len(data["mensagens"]))
            if snapshot != last:
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                last = snapshot
            if data["status"] in TERMINAL:
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        job = _job_for_user(conn, job_id, user, "editor")
        if job["status"] in TERMINAL:
            raise bad_request("Este processamento já terminou.")
        if job["status"] == "queued":
            conn.execute("UPDATE app.jobs SET status='cancelled', finished_at=now(), "
                         "error='Cancelado antes de iniciar.' WHERE id=%s AND status='queued'", (job_id,))
            if job["celery_id"]:
                celery_app.control.revoke(job["celery_id"])
        else:
            conn.execute("UPDATE app.jobs SET status='cancelling' WHERE id=%s", (job_id,))
            if job["pg_pid"]:
                conn.execute("SELECT pg_cancel_backend(%s)", (job["pg_pid"],))
        audit(conn, user, "cancelar", "job", job_id)
    return public_job(get_job(job_id))


@router.get("/export-formats")
def export_formats():
    return [{"id": k, "rotulo": v["rotulo"], "tipo": "vetorial"} for k, v in FORMATS.items()] + \
           [{"id": "geotiff", "rotulo": "GeoTIFF", "tipo": "raster"}]


@router.post("/layers/{layer_id}/export", status_code=202)
def export_layer(layer_id: UUID, body: ExportRequest, user: CurrentUser = UserDep):
    with connection() as conn:
        layer = require_layer(conn, layer_id, user)
        valid = {"geotiff"} if layer["kind"] == "raster" else set(FORMATS)
        if body.formato not in valid:
            raise bad_request(f"Formato inválido para esta camada. Use: {', '.join(sorted(valid))}.")
        job = create_job(conn, project_id=layer["project_id"], user_id=user.id, kind="export", tool_id=None,
                         params={"layer_id": str(layer_id), "formato": body.formato, "camada": layer["name"]})
        audit(conn, user, "exportar", "camada", layer_id, {"formato": body.formato})
    return _start(job)


@router.get("/exports/{export_id}/url")
def export_url(export_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        exp = conn.execute("SELECT * FROM app.exports WHERE id=%s", (export_id,)).fetchone()
        if not exp:
            raise not_found("Exportação")
        require_project(conn, exp["project_id"], user)
    s = get_settings()
    return {"url": get_storage().signed_url(exp["storage_key"], exp["filename"]),
            "expira_em_segundos": s.signed_url_ttl_seconds, "arquivo": exp["filename"]}


@router.get("/files/{key:path}", include_in_schema=False)
def download_local(key: str, exp: int, sig: str, name: str = "arquivo"):
    """Download por URL assinada (somente armazenamento local; no S3 a URL aponta direto ao bucket)."""
    from fastapi.responses import FileResponse
    s = get_settings()
    storage = get_storage()
    if s.storage_backend != "local" or not check_local_signature(key, exp, sig, s):
        raise APIError(403, "url_invalida", "Link expirado ou inválido. Gere um novo link de download.")
    path = storage.local_file(key)  # type: ignore[attr-defined]
    if not path.exists():
        raise not_found("Arquivo")
    return FileResponse(path, filename=name)


