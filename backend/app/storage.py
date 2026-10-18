"""Armazenamento de objetos: sistema de arquivos local (desenvolvimento/testes) ou S3/MinIO.

As chaves seguem o padrão projects/<project_id>/<categoria>/<arquivo>, o que isola arquivos
por projeto. Downloads saem sempre por URL temporária assinada.
"""
from __future__ import annotations

import hashlib
import hmac
import shutil
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from app.core.config import Settings, get_settings


class Storage(Protocol):
    def put_file(self, local_path: Path, key: str) -> None: ...
    def get_to_file(self, key: str, local_path: Path) -> None: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def gdal_path(self, key: str) -> str: ...
    def signed_url(self, key: str, filename: str) -> str: ...


def _safe_key(key: str) -> str:
    parts = [p for p in key.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise ValueError("chave de armazenamento inválida")
    return "/".join(parts)


class LocalStorage:
    def __init__(self, s: Settings):
        self.root = Path(s.storage_local_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.s = s

    def _path(self, key: str) -> Path:
        p = (self.root / _safe_key(key)).resolve()
        if self.root not in p.parents:
            raise ValueError("chave fora do diretório de armazenamento")
        return p

    def put_file(self, local_path: Path, key: str) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dst)

    def get_to_file(self, key: str, local_path: Path) -> None:
        shutil.copyfile(self._path(key), local_path)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def gdal_path(self, key: str) -> str:
        return str(self._path(key))

    def local_file(self, key: str) -> Path:
        return self._path(key)

    def signed_url(self, key: str, filename: str) -> str:
        exp = int(time.time()) + self.s.signed_url_ttl_seconds
        sig = sign_local(key, exp, self.s)
        base = self.s.public_api_url.rstrip("/")
        return f"{base}/api/v1/files/{quote(_safe_key(key))}?exp={exp}&sig={sig}&name={quote(filename)}"


def sign_local(key: str, exp: int, s: Settings) -> str:
    msg = f"{_safe_key(key)}|{exp}".encode()
    return hmac.new(s.url_signing_secret.encode(), msg, hashlib.sha256).hexdigest()


def check_local_signature(key: str, exp: int, sig: str, s: Settings) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sign_local(key, exp, s), sig)


class S3Storage:
    def __init__(self, s: Settings):
        import boto3
        from botocore.config import Config

        self.s = s
        kw = dict(region_name=s.s3_region, aws_access_key_id=s.s3_access_key or None,
                  aws_secret_access_key=s.s3_secret_key or None,
                  config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint_url or None, **kw)
        # Cliente separado para assinar URLs com o endereço que o navegador alcança.
        public = s.s3_public_endpoint_url or s.s3_endpoint_url or None
        self.public_client = boto3.client("s3", endpoint_url=public, **kw)
        self.bucket = s.s3_bucket

    def put_file(self, local_path: Path, key: str) -> None:
        self.client.upload_file(str(local_path), self.bucket, _safe_key(key))

    def get_to_file(self, key: str, local_path: Path) -> None:
        self.client.download_file(self.bucket, _safe_key(key), str(local_path))

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    def gdal_path(self, key: str) -> str:
        return f"/vsis3/{self.bucket}/{_safe_key(key)}"

    def signed_url(self, key: str, filename: str) -> str:
        return self.public_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": _safe_key(key),
                    "ResponseContentDisposition": f'attachment; filename="{filename}"'},
            ExpiresIn=self.s.signed_url_ttl_seconds,
        )


def gdal_env(s: Settings | None = None) -> dict:
    """Opções para rasterio.Env ler COGs no S3/MinIO (credenciais via sessão AWS do rasterio)."""
    s = s or get_settings()
    if s.storage_backend != "s3":
        return {}
    from rasterio.session import AWSSession

    endpoint = None
    env: dict = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}
    if s.s3_endpoint_url:
        from urllib.parse import urlparse
        u = urlparse(s.s3_endpoint_url)
        endpoint = u.netloc
        env.update({"AWS_HTTPS": "YES" if u.scheme == "https" else "NO", "AWS_VIRTUAL_HOSTING": "FALSE"})
    env["session"] = AWSSession(aws_access_key_id=s.s3_access_key or None,
                                aws_secret_access_key=s.s3_secret_key or None,
                                region_name=s.s3_region, endpoint_url=endpoint)
    return env


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage(s) if s.storage_backend == "s3" else LocalStorage(s)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
