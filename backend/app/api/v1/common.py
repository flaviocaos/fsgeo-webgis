"""Representações públicas e utilidades comuns às rotas."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

LAYER_COLUMNS = """
    l.*, ARRAY[ST_XMin(l.bbox_4326), ST_YMin(l.bbox_4326), ST_XMax(l.bbox_4326), ST_YMax(l.bbox_4326)] AS bbox,
    pl.position, pl.group_name, pl.visible, pl.opacity, pl.style
"""


def srid_code(srid: int) -> str | None:
    if not srid:
        return None
    return f"EPSG:{srid}" if srid < 900000 else f"WEBGIS:{srid}"


def public_layer(row: dict[str, Any], fields: list[dict[str, Any]] | None) -> dict[str, Any]:
    bbox = row.get("bbox")
    out = {
        "id": str(row["id"]),
        "projeto_id": str(row["project_id"]),
        "nome": row["name"],
        "tipo": "vetorial" if row["kind"] == "vector" else "raster",
        "geometria": row["geom_type"],
        "srid": row["srid"],
        "crs": srid_code(row["srid"]),
        "feicoes": row["feature_count"],
        "versao": row["version"],
        "editavel": bool(row["editable"]) and row["kind"] == "vector" and bool(row["srid"]),
        "bbox": [float(v) for v in bbox] if bbox and all(v is not None for v in bbox) else None,
        "campos": [{"nome": f["name"], "tipo": f["type"]} for f in (fields or [])],
        "criada_em": row["created_at"].isoformat(),
        "origem_job": str(row["source_job_id"]) if row.get("source_job_id") else None,
    }
    if row["kind"] == "raster":
        st = row.get("raster_stats") or {}
        out["raster"] = {"bandas": row["band_count"], "tipo_dado": row["band_dtype"], "nodata": row["nodata"],
                         "largura": st.get("width"), "altura": st.get("height"),
                         "resolucao": st.get("resolucao"), "estatisticas": st.get("estatisticas", [])}
    if "position" in row and row.get("position") is not None:
        out["exibicao"] = {"posicao": row["position"], "grupo": row["group_name"], "visivel": row["visible"],
                           "opacidade": row["opacity"], "estilo": row["style"] or {}}
    return out


def jsonable(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, memoryview)):
        return None
    return value


def public_project(row: dict[str, Any], role: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "nome": row["name"], "descricao": row["description"], "crs": row["crs"],
        "estado": row["state"], "versao": row["version"], "papel": role or row.get("role"),
        "criado_em": row["created_at"].isoformat(), "atualizado_em": row["updated_at"].isoformat(),
        "camadas": row.get("layer_count"),
    }
