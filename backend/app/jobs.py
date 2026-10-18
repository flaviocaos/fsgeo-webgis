"""Registro de jobs: criação, progresso e conclusão (cada atualização em transação própria,
para que o progresso fique visível enquanto o processamento roda em outra transação)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.db.pool import connection

TERMINAL = {"succeeded", "failed", "cancelled"}


def create_job(conn, *, project_id, user_id, kind: str, tool_id: str | None, params: dict) -> dict:
    return conn.execute(
        "INSERT INTO app.jobs (project_id, user_id, kind, tool_id, params) VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (project_id, user_id, kind, tool_id, Jsonb(params)),
    ).fetchone()


def get_job(job_id: UUID | str) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM app.jobs WHERE id=%s", (job_id,)).fetchone()


def mark_running(job_id, pg_pid: int | None) -> bool:
    """Marca o job como em execução. Devolve False se ele foi cancelado antes de começar."""
    with connection() as conn:
        row = conn.execute(
            "UPDATE app.jobs SET status='running', started_at=now(), progress=GREATEST(progress,5), pg_pid=%s "
            "WHERE id=%s AND status='queued' RETURNING id", (pg_pid, job_id)).fetchone()
        return row is not None


def progress(job_id, pct: int, message: str | None = None) -> None:
    with connection() as conn:
        if message:
            conn.execute(
                "UPDATE app.jobs SET progress=GREATEST(progress, %s), messages = messages || %s WHERE id=%s "
                "AND status IN ('running','cancelling')",
                (max(0, min(99, pct)), Jsonb([{"nivel": "info", "texto": message}]), job_id))
        else:
            conn.execute("UPDATE app.jobs SET progress=GREATEST(progress,%s) WHERE id=%s", (max(0, min(99, pct)), job_id))


def finish(job_id, status: str, *, result: dict | None = None, error: str | None = None,
           messages: list[dict[str, Any]] | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE app.jobs SET status=%s, progress=CASE WHEN %s='succeeded' THEN 100 ELSE progress END, "
            "result=%s, error=%s, messages = messages || %s, finished_at=now(), pg_pid=NULL WHERE id=%s",
            (status, status, Jsonb(result) if result is not None else None, error, Jsonb(messages or []), job_id))


def is_cancelling(job_id) -> bool:
    with connection() as conn:
        row = conn.execute("SELECT status FROM app.jobs WHERE id=%s", (job_id,)).fetchone()
        return bool(row and row["status"] in ("cancelling", "cancelled"))


def public_job(row: dict) -> dict:
    return {
        "id": str(row["id"]), "projeto_id": str(row["project_id"]), "tipo": row["kind"],
        "ferramenta": row["tool_id"], "parametros": row["params"], "status": row["status"],
        "progresso": row["progress"], "mensagens": row["messages"], "resultado": row["result"],
        "erro": row["error"], "criado_em": row["created_at"].isoformat(),
        "iniciado_em": row["started_at"].isoformat() if row["started_at"] else None,
        "concluido_em": row["finished_at"].isoformat() if row["finished_at"] else None,
    }
