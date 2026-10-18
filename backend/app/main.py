"""Aplicação FastAPI da plataforma WebGIS."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, crs, layers, projects, tiles, tools, uploads
from app.core.config import get_settings
from app.core.errors import APIError, api_error_handler
from app.db.pool import close_pool, connection


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_pool()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="FS Geotecnologias · WebGIS API",
        version="0.1.0",
        description="API da plataforma WebGIS: projetos, camadas, edição vetorial, geoprocessamento e exportação.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.add_exception_handler(APIError, api_error_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_, exc: RequestValidationError):
        details = [{"campo": ".".join(str(p) for p in e["loc"][1:]), "erro": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"erro": {"codigo": "dados_invalidos",
                                                               "mensagem": "Dados inválidos na requisição.",
                                                               "detalhes": details}})

    for r in (auth, projects, uploads, layers, tiles, tools, crs):
        app.include_router(r.router, prefix="/api/v1")

    @app.get("/health", tags=["saúde"])
    def health():
        with connection() as conn:
            pg = conn.execute("SELECT postgis_lib_version() AS v").fetchone()["v"]
        return {"status": "ok", "postgis": pg}

    return app


app = create_app()
