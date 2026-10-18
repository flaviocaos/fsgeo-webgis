"""Erros com mensagens em português, devolvidos como JSON uniforme."""
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def not_found(what: str = "Recurso") -> APIError:
    return APIError(404, "nao_encontrado", f"{what} não encontrado.")


def forbidden(message: str = "Você não tem permissão para esta ação.") -> APIError:
    return APIError(403, "sem_permissao", message)


def bad_request(message: str, details: Any = None, code: str = "requisicao_invalida") -> APIError:
    return APIError(400, code, message, details)


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    body: dict[str, Any] = {"erro": {"codigo": exc.code, "mensagem": exc.message}}
    if exc.details is not None:
        body["erro"]["detalhes"] = exc.details
    return JSONResponse(status_code=exc.status, content=body)
