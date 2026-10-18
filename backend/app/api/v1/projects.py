from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from app.api.v1.common import LAYER_COLUMNS, public_layer, public_project
from app.core.deps import CurrentUser, UserDep, audit, require_project
from app.core.errors import APIError, bad_request, not_found
from app.db.pool import connection
from app.storage import get_storage
from geo import crs as crsmod
from geo.layerstore import drop_layer_table, get_fields, table_ident

router = APIRouter(tags=["projetos"])


class ProjectCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    descricao: str = ""
    crs: str = "EPSG:4326"


class ProjectPatch(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = None
    crs: str | None = None
    estado: dict[str, Any] | None = None


class LayerState(BaseModel):
    camada_id: UUID
    posicao: int
    grupo: str | None = None
    visivel: bool = True
    opacidade: float = Field(default=1, ge=0, le=1)
    estilo: dict[str, Any] = {}


class MemberAdd(BaseModel):
    email: str
    papel: str = Field(pattern="^(editor|viewer)$")


def _validate_crs(value: str) -> str:
    try:
        c = crsmod.parse_crs(value)
    except crsmod.CRSInputError as exc:
        raise bad_request(str(exc))
    epsg = c.to_epsg(min_confidence=70)
    if not epsg:
        raise bad_request("O CRS do projeto deve ter código EPSG (ex.: EPSG:4326, EPSG:4674, EPSG:31983).")
    return f"EPSG:{epsg}"


@router.get("/projects")
def list_projects(user: CurrentUser = UserDep):
    with connection() as conn:
        rows = conn.execute(
            """SELECT p.*, m.role, (SELECT count(*) FROM app.layers l WHERE l.project_id = p.id) AS layer_count
               FROM app.projects p JOIN app.project_members m ON m.project_id = p.id AND m.user_id = %s
               ORDER BY p.updated_at DESC""", (user.id,)).fetchall()
    return [public_project(r) for r in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, user: CurrentUser = UserDep):
    crs = _validate_crs(body.crs)
    with connection() as conn:
        row = conn.execute(
            "INSERT INTO app.projects (owner_id, name, description, crs) VALUES (%s,%s,%s,%s) RETURNING *",
            (user.id, body.nome.strip(), body.descricao, crs)).fetchone()
        conn.execute("INSERT INTO app.project_members (project_id, user_id, role) VALUES (%s,%s,'owner')",
                     (row["id"], user.id))
        audit(conn, user, "criar", "projeto", row["id"])
    return public_project(row, "owner")


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        role = require_project(conn, project_id, user)
        row = conn.execute("SELECT * FROM app.projects WHERE id=%s", (project_id,)).fetchone()
        layers = conn.execute(
            f"SELECT {LAYER_COLUMNS} FROM app.layers l JOIN app.project_layers pl ON pl.layer_id = l.id "
            "WHERE l.project_id = %s ORDER BY pl.position DESC", (project_id,)).fetchall()
        out = public_project(row, role)
        out["camadas"] = [public_layer(l, get_fields(conn, l["id"]) if l["kind"] == "vector" else None)
                          for l in layers]
    return out


@router.patch("/projects/{project_id}")
def patch_project(project_id: UUID, body: ProjectPatch, user: CurrentUser = UserDep):
    with connection() as conn:
        role = require_project(conn, project_id, user, "editor")
        sets, params = [], []
        if body.nome is not None:
            sets.append("name=%s"); params.append(body.nome.strip())
        if body.descricao is not None:
            sets.append("description=%s"); params.append(body.descricao)
        if body.crs is not None:
            sets.append("crs=%s"); params.append(_validate_crs(body.crs))
        if body.estado is not None:
            sets.append("state=%s"); params.append(Jsonb(body.estado))
        if sets:
            sets.append("version = version + 1"); sets.append("updated_at = now()")
            conn.execute(f"UPDATE app.projects SET {', '.join(sets)} WHERE id=%s", (*params, project_id))
        row = conn.execute("SELECT * FROM app.projects WHERE id=%s", (project_id,)).fetchone()
    return public_project(row, role)


@router.put("/projects/{project_id}/layers-state")
def save_layers_state(project_id: UUID, body: list[LayerState], user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user, "editor")
        ids = {r["layer_id"] for r in conn.execute(
            "SELECT layer_id FROM app.project_layers WHERE project_id=%s", (project_id,)).fetchall()}
        for st in body:
            if st.camada_id not in ids:
                raise bad_request(f"Camada {st.camada_id} não pertence ao projeto.")
            conn.execute(
                "UPDATE app.project_layers SET position=%s, group_name=%s, visible=%s, opacity=%s, style=%s "
                "WHERE project_id=%s AND layer_id=%s",
                (st.posicao, st.grupo, st.visivel, st.opacidade, Jsonb(st.estilo), project_id, st.camada_id))
        conn.execute("UPDATE app.projects SET updated_at=now(), version=version+1 WHERE id=%s", (project_id,))
    return {"ok": True}


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: UUID, user: CurrentUser = UserDep):
    keys: list[str] = []
    with connection() as conn:
        require_project(conn, project_id, user, "owner")
        layers = conn.execute("SELECT * FROM app.layers WHERE project_id=%s", (project_id,)).fetchall()
        for l in layers:
            if l["kind"] == "vector":
                drop_layer_table(conn, l["table_name"])
            else:
                shared = conn.execute("SELECT 1 FROM app.layers WHERE cog_key=%s AND project_id<>%s LIMIT 1",
                                      (l["cog_key"], project_id)).fetchone()
                if not shared:
                    keys.append(l["cog_key"])
        keys += [r["storage_key"] for r in conn.execute(
            "SELECT storage_key FROM app.exports WHERE project_id=%s UNION ALL "
            "SELECT storage_key FROM app.datasets WHERE project_id=%s", (project_id, project_id)).fetchall()]
        conn.execute("DELETE FROM app.projects WHERE id=%s", (project_id,))
        audit(conn, user, "excluir", "projeto", project_id)
    storage = get_storage()
    for k in keys:
        try:
            storage.delete(k)
        except Exception:
            pass


@router.post("/projects/{project_id}/duplicate", status_code=201)
def duplicate_project(project_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user, "viewer")
        src = conn.execute("SELECT * FROM app.projects WHERE id=%s", (project_id,)).fetchone()
        new = conn.execute(
            "INSERT INTO app.projects (owner_id, name, description, crs, state) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (user.id, f"{src['name']} (cópia)"[:200], src["description"], src["crs"], Jsonb(src["state"]))).fetchone()
        conn.execute("INSERT INTO app.project_members (project_id, user_id, role) VALUES (%s,%s,'owner')",
                     (new["id"], user.id))
        layers = conn.execute(
            "SELECT l.*, pl.position, pl.group_name, pl.visible, pl.opacity, pl.style FROM app.layers l "
            "JOIN app.project_layers pl ON pl.layer_id=l.id WHERE l.project_id=%s", (project_id,)).fetchall()
        for l in layers:
            nid = uuid.uuid4()
            table = f"l_{nid.hex}" if l["kind"] == "vector" else None
            if table:
                conn.execute(sql.SQL("CREATE TABLE {} (LIKE {} INCLUDING ALL)").format(
                    table_ident(table), table_ident(l["table_name"])))
                # A sequência do fid precisa ser própria da nova tabela.
                conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN fid DROP DEFAULT").format(table_ident(table)))
                seq = sql.Identifier("layerdata", f"{table}_fid_seq")
                conn.execute(sql.SQL("CREATE SEQUENCE {} OWNED BY {}.fid").format(seq, table_ident(table)))
                conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN fid SET DEFAULT nextval({})").format(
                    table_ident(table), sql.Literal(f"layerdata.{table}_fid_seq")))
                conn.execute(sql.SQL("INSERT INTO {} SELECT * FROM {}").format(
                    table_ident(table), table_ident(l["table_name"])))
                conn.execute(sql.SQL("SELECT setval({}, GREATEST((SELECT COALESCE(MAX(fid),0) FROM {}), 1))").format(
                    sql.Literal(f"layerdata.{table}_fid_seq"), table_ident(table)))
            conn.execute(
                """INSERT INTO app.layers (id, project_id, kind, name, srid, geom_type, table_name, cog_key,
                       band_count, band_dtype, nodata, raster_stats, bbox_4326, feature_count, next_field,
                       editable, created_by)
                   SELECT %s, %s, kind, name, srid, geom_type, %s, cog_key, band_count, band_dtype, nodata,
                       raster_stats, bbox_4326, feature_count, next_field, editable, %s FROM app.layers WHERE id=%s""",
                (nid, new["id"], table, user.id, l["id"]))
            conn.execute("INSERT INTO app.layer_fields (layer_id, name, column_name, type, position) "
                         "SELECT %s, name, column_name, type, position FROM app.layer_fields WHERE layer_id=%s",
                         (nid, l["id"]))
            conn.execute("INSERT INTO app.project_layers (project_id, layer_id, position, group_name, visible, "
                         "opacity, style) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                         (new["id"], nid, l["position"], l["group_name"], l["visible"], l["opacity"], Jsonb(l["style"])))
        audit(conn, user, "duplicar", "projeto", project_id, {"novo": str(new["id"])})
    return public_project(new, "owner")


@router.get("/projects/{project_id}/members")
def list_members(project_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user)
        rows = conn.execute("SELECT u.id, u.email, m.role FROM app.project_members m JOIN app.users u "
                            "ON u.id=m.user_id WHERE m.project_id=%s ORDER BY m.role, u.email", (project_id,)).fetchall()
    return [{"id": str(r["id"]), "email": r["email"], "papel": r["role"]} for r in rows]


@router.post("/projects/{project_id}/members", status_code=201)
def add_member(project_id: UUID, body: MemberAdd, user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user, "owner")
        target = conn.execute("SELECT id FROM app.users WHERE lower(email)=lower(%s)", (body.email.strip(),)).fetchone()
        if not target:
            raise APIError(404, "usuario_nao_encontrado",
                           "Usuário não encontrado. A pessoa precisa entrar na plataforma ao menos uma vez.")
        if target["id"] == user.id:
            raise bad_request("Você já é o dono do projeto.")
        conn.execute("INSERT INTO app.project_members (project_id, user_id, role) VALUES (%s,%s,%s) "
                     "ON CONFLICT (project_id, user_id) DO UPDATE SET role=EXCLUDED.role",
                     (project_id, target["id"], body.papel))
        audit(conn, user, "compartilhar", "projeto", project_id, {"email": body.email, "papel": body.papel})
    return {"ok": True}


@router.delete("/projects/{project_id}/members/{member_id}", status_code=204)
def remove_member(project_id: UUID, member_id: UUID, user: CurrentUser = UserDep):
    with connection() as conn:
        require_project(conn, project_id, user, "owner")
        r = conn.execute("DELETE FROM app.project_members WHERE project_id=%s AND user_id=%s AND role<>'owner' "
                         "RETURNING user_id", (project_id, member_id)).fetchone()
        if not r:
            raise not_found("Membro")
