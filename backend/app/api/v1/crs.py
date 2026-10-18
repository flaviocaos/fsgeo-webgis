from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser, UserDep
from app.core.errors import bad_request
from geo import crs as crsmod

router = APIRouter(tags=["sistemas de referência"])

# Atalhos frequentes no Brasil
COMMON = ["EPSG:4326", "EPSG:4674", "EPSG:3857", "EPSG:31982", "EPSG:31983", "EPSG:31984", "EPSG:31981",
          "EPSG:31985", "EPSG:5880", "EPSG:32722", "EPSG:32723", "EPSG:32724", "EPSG:29193"]


class TransformRequest(BaseModel):
    de: str
    para: str
    coordenadas: list[list[float]] = Field(min_length=1, max_length=10000)


@router.get("/crs/search")
def search_crs(q: str = Query(default="", max_length=100), limite: int = Query(default=30, ge=1, le=200),
               user: CurrentUser = UserDep):
    from pyproj.database import query_crs_info
    from pyproj.enums import PJType

    q = q.strip().lower()
    if not q:
        out = []
        for code in COMMON:
            c = crsmod.parse_crs(code)
            out.append({"codigo": code, "nome": c.name, "geografico": c.is_geographic})
        return out
    results = []
    for info in query_crs_info(auth_name="EPSG", pj_types=[PJType.GEOGRAPHIC_2D_CRS, PJType.PROJECTED_CRS]):
        code = f"EPSG:{info.code}"
        if q in info.name.lower() or q == info.code or q == code.lower() or (q.isdigit() and info.code.startswith(q)):
            results.append({"codigo": code, "nome": info.name, "geografico": info.type == PJType.GEOGRAPHIC_2D_CRS,
                            "obsoleto": info.deprecated})
        if len(results) >= limite * 3:
            break
    results.sort(key=lambda r: (r["obsoleto"], r["codigo"] != f"EPSG:{q}", len(r["nome"])))
    return results[:limite]


@router.get("/crs/{code}")
def crs_info(code: str, user: CurrentUser = UserDep):
    try:
        return crsmod.describe(crsmod.parse_crs(code))
    except crsmod.CRSInputError as exc:
        raise bad_request(str(exc))


@router.post("/crs/transform")
def transform(body: TransformRequest, user: CurrentUser = UserDep):
    try:
        a, b = crsmod.parse_crs(body.de), crsmod.parse_crs(body.para)
        pts = crsmod.transform_points(body.de, body.para, body.coordenadas)
    except crsmod.CRSInputError as exc:
        raise bad_request(str(exc))
    return {"coordenadas": pts, "aviso_datum": crsmod.datum_warning(a, b)}
