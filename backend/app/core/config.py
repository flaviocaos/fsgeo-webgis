"""Configuração da aplicação, lida de variáveis de ambiente."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"

    # Banco
    database_url: str = "postgresql://postgres:postgres@localhost:5432/webgis"
    db_pool_min: int = 1
    db_pool_max: int = 10

    # Fila
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    # Autenticação
    # "supabase": valida tokens emitidos pelo Supabase Auth.
    # "local": login de desenvolvimento com um único usuário definido no .env.
    auth_mode: Literal["supabase", "local"] = "supabase"
    supabase_url: str = ""
    supabase_jwt_secret: str = ""          # projetos com chave HS256 (legado)
    supabase_jwt_audience: str = "authenticated"
    local_jwt_secret: str = ""
    dev_user_email: str = ""
    dev_user_password: str = ""

    # Armazenamento de objetos
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_dir: str = "./data/storage"
    s3_bucket: str = "webgis"
    s3_endpoint_url: str = ""              # MinIO: http://minio:9000
    s3_public_endpoint_url: str = ""       # URL que o navegador enxerga (URLs assinadas)
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    signed_url_ttl_seconds: int = 900
    url_signing_secret: str = "troque-este-segredo"

    # Limites
    max_upload_mb: int = 2048
    storage_quota_mb: int = 10240
    max_zip_uncompressed_mb: int = 8192
    max_features_per_request: int = 5000

    # API
    public_api_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000"
    work_dir: str = "./data/work"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
