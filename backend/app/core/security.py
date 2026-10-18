"""Verificação de tokens de acesso.

Modo "supabase": aceita JWTs do Supabase Auth.
  - Chave simétrica (HS256) com SUPABASE_JWT_SECRET, ou
  - Chaves assimétricas (RS256/ES256) publicadas em <SUPABASE_URL>/auth/v1/.well-known/jwks.json.
Modo "local": emite e valida tokens HS256 para um único usuário de desenvolvimento.
  É recusado quando ENVIRONMENT=production.
"""
from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from functools import lru_cache

import jwt

from app.core.config import Settings, get_settings
from app.core.errors import APIError

LOCAL_ISSUER = "webgis-local"


@dataclass(frozen=True)
class Identity:
    external_id: str
    email: str | None


def _unauthorized(msg: str = "Sessão inválida ou expirada. Entre novamente.") -> APIError:
    return APIError(401, "nao_autenticado", msg)


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str, settings: Settings | None = None) -> Identity:
    s = settings or get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise _unauthorized()
    alg = header.get("alg")

    try:
        if s.auth_mode == "local":
            if s.environment == "production":
                raise _unauthorized("Modo de autenticação local não é permitido em produção.")
            if alg != "HS256" or not s.local_jwt_secret:
                raise _unauthorized()
            claims = jwt.decode(
                token, s.local_jwt_secret, algorithms=["HS256"],
                audience=s.supabase_jwt_audience, issuer=LOCAL_ISSUER,
                options={"require": ["exp", "sub"]},
            )
        else:
            issuer = f"{s.supabase_url.rstrip('/')}/auth/v1" if s.supabase_url else None
            if alg == "HS256":
                if not s.supabase_jwt_secret:
                    raise _unauthorized()
                key: object = s.supabase_jwt_secret
            elif alg in ("RS256", "ES256"):
                if not s.supabase_url:
                    raise _unauthorized()
                key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
            else:
                raise _unauthorized()
            claims = jwt.decode(
                token, key, algorithms=[alg],
                audience=s.supabase_jwt_audience, issuer=issuer,
                options={"require": ["exp", "sub"]},
            )
    except APIError:
        raise
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Sua sessão expirou. Entre novamente.")
    except (jwt.PyJWTError, jwt.PyJWKClientError):
        raise _unauthorized()

    return Identity(external_id=str(claims["sub"]), email=claims.get("email"))


def local_login(email: str, password: str, settings: Settings | None = None) -> str:
    """Emite token para o usuário de desenvolvimento (somente AUTH_MODE=local)."""
    s = settings or get_settings()
    if s.auth_mode != "local" or s.environment == "production":
        raise APIError(404, "nao_encontrado", "Login local desabilitado.")
    if not (s.dev_user_email and s.dev_user_password and s.local_jwt_secret):
        raise APIError(500, "config_incompleta", "Defina DEV_USER_EMAIL, DEV_USER_PASSWORD e LOCAL_JWT_SECRET.")
    ok_email = hmac.compare_digest(email.strip().lower(), s.dev_user_email.strip().lower())
    ok_pass = hmac.compare_digest(password, s.dev_user_password)
    if not (ok_email and ok_pass):
        raise APIError(401, "credenciais_invalidas", "E-mail ou senha incorretos.")
    now = int(time.time())
    return jwt.encode(
        {"sub": f"local:{s.dev_user_email.lower()}", "email": s.dev_user_email.lower(),
         "aud": s.supabase_jwt_audience, "iss": LOCAL_ISSUER, "iat": now, "exp": now + 12 * 3600},
        s.local_jwt_secret, algorithm="HS256",
    )
