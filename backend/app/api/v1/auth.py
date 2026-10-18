from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.deps import CurrentUser, UserDep
from app.core.security import local_login

router = APIRouter(tags=["autenticação"])


class LocalLogin(BaseModel):
    email: str
    senha: str


@router.get("/auth/config")
def auth_config():
    s = get_settings()
    return {"modo": s.auth_mode, "supabase_url": s.supabase_url or None}


@router.post("/auth/local/login")
def login_local(body: LocalLogin):
    token = local_login(body.email, body.senha)
    return {"access_token": token, "token_type": "bearer", "expira_em_segundos": 12 * 3600}


@router.get("/me")
def me(user: CurrentUser = UserDep):
    return {"id": str(user.id), "email": user.email}
