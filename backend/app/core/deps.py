"""Dependências FastAPI: usuário atual e checagem de papel no projeto."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, Query

from app.core.errors import APIError, forbidden, not_found
from app.core.security import verify_token
from app.db.pool import connection

ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None


def _token_from(authorization: str | None, access_token: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if access_token:  # usado apenas pelo EventSource (SSE), que não envia cabeçalhos
        return access_token
    raise APIError(401, "nao_autenticado", "Faça login para continuar.")


def current_user(
    authorization: str | None = Header(default=None),
    access_token: str | None = Query(default=None, include_in_schema=False),
) -> CurrentUser:
    ident = verify_token(_token_from(authorization, access_token))
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO app.users (external_id, email) VALUES (%s, %s)
            ON CONFLICT (external_id) DO UPDATE
              SET email = COALESCE(EXCLUDED.email, app.users.email), last_seen_at = now()
            RETURNING id, email
            """,
            (ident.external_id, ident.email),
        ).fetchone()
    return CurrentUser(id=row["id"], email=row["email"])


def project_role(conn, project_id: UUID, user_id: UUID) -> str | None:
    row = conn.execute(
        "SELECT role FROM app.project_members WHERE project_id = %s AND user_id = %s",
        (project_id, user_id),
    ).fetchone()
    return row["role"] if row else None


def require_project(conn, project_id: UUID, user: CurrentUser, min_role: str = "viewer") -> str:
    exists = conn.execute("SELECT 1 FROM app.projects WHERE id = %s", (project_id,)).fetchone()
    role = project_role(conn, project_id, user.id) if exists else None
    if not exists or role is None:
        # Não revela a existência de projetos alheios.
        raise not_found("Projeto")
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise forbidden(
            "Seu papel neste projeto é somente leitura." if role == "viewer"
            else "Somente o dono do projeto pode fazer isso."
        )
    return role


def require_layer(conn, layer_id: UUID, user: CurrentUser, min_role: str = "viewer") -> dict[str, Any]:
    layer = conn.execute("SELECT * FROM app.layers WHERE id = %s", (layer_id,)).fetchone()
    if not layer:
        raise not_found("Camada")
    require_project(conn, layer["project_id"], user, min_role)
    return layer


def audit(conn, user: CurrentUser | None, action: str, resource_type: str,
          resource_id: Any = None, detail: dict | None = None) -> None:
    from psycopg.types.json import Jsonb
    conn.execute(
        "INSERT INTO app.audit_log (user_id, action, resource_type, resource_id, detail)"
        " VALUES (%s, %s, %s, %s, %s)",
        (user.id if user else None, action, resource_type,
         str(resource_id) if resource_id is not None else None, Jsonb(detail or {})),
    )


UserDep = Depends(current_user)
