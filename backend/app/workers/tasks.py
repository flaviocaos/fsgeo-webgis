"""Tarefas Celery: importação, ferramentas e exportação.

Cada tarefa abre sua própria conexão/transação. O PID da conexão fica gravado no job
para que o cancelamento interrompa a consulta em andamento (pg_cancel_backend).
"""
from __future__ import annotations

import logging
import shutil
import traceback
import uuid
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from app import jobs
from app.core.config import get_settings
from app.db.pool import connection
from app.storage import get_storage
from app.workers.celery_app import celery_app
from geo import crs as crsmod
from geo.io.detect import DetectError, detect, expand_inputs
from geo.io.export import ExportError, export_vector
from geo.io.import_vector import ImportError_, import_vector_layer
from geo.layerstore import LayerStoreError, add_to_project_top
from geo.raster.ingest import RasterIngestError, to_cog
from geo.vector import tools as vtools

log = logging.getLogger(__name__)
USER_ERRORS = (DetectError, ImportError_, RasterIngestError, vtools.ToolError, ExportError, LayerStoreError,
               crsmod.CRSInputError)


def _workdir(job_id) -> Path:
    d = Path(get_settings().work_dir).resolve() / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _run(job_id: str, body) -> None:
    """Executa o corpo do job com tratamento uniforme de erro, cancelamento e limpeza."""
    job = jobs.get_job(job_id)
    if job is None:
        return
    work = _workdir(job_id)
    try:
        with connection() as conn:
            pid = conn.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
            if not jobs.mark_running(job_id, pid):
                return  # cancelado antes de iniciar
            result, msgs = body(conn, job, work)
        jobs.finish(job_id, "succeeded", result=result, messages=[{"nivel": "aviso", "texto": m} for m in msgs])
    except psycopg.errors.QueryCanceled:
        jobs.finish(job_id, "cancelled", error="Processamento cancelado pelo usuário.")
    except USER_ERRORS as exc:
        status = "cancelled" if jobs.is_cancelling(job_id) else "failed"
        jobs.finish(job_id, status, error=str(exc))
    except Exception as exc:  # erro inesperado: registra detalhes no log do servidor
        log.error("job %s falhou: %s", job_id, traceback.format_exc())
        status = "cancelled" if jobs.is_cancelling(job_id) else "failed"
        jobs.finish(job_id, status, error=f"Erro interno no processamento ({type(exc).__name__}). "
                                          "Detalhes no log do servidor.")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ importação

def _import_body(conn, job, work: Path):
    params = job["params"]
    storage = get_storage()
    s = get_settings()
    rows = conn.execute("SELECT * FROM app.datasets WHERE id = ANY(%s) AND project_id=%s",
                        ([uuid.UUID(d) for d in params["dataset_ids"]], job["project_id"])).fetchall()
    if len(rows) != len(params["dataset_ids"]):
        raise DetectError("Arquivo enviado não encontrado.")
    files = []
    inbox = work / "in"
    inbox.mkdir()
    for r in rows:
        dst = inbox / Path(r["original_name"]).name
        storage.get_to_file(r["storage_key"], dst)
        files.append(dst)
    jobs.progress(job["id"], 10, "Arquivos recebidos; detectando formato")
    mains = expand_inputs(files, work / "x", s.max_zip_uncompressed_mb * 1024 * 1024)

    created, msgs, failures = [], [], []
    for path in mains:
        try:
            det = detect(path)
            msgs += det.warnings
            if det.kind == "vector":
                import pyogrio
                for lname in det.layers:
                    with conn.transaction():
                        total = pyogrio.read_info(path, layer=lname).get("features")
                        name = lname if len(det.layers) > 1 else path.stem
                        layer, m = import_vector_layer(
                            conn, path, lname, project_id=job["project_id"], user_id=job["user_id"],
                            name=name, dataset_id=rows[0]["id"],
                            progress=lambda p, t: jobs.progress(job["id"], p, None),
                            total_hint=total if total and total > 0 else None)
                    created.append({"id": str(layer["id"]), "nome": layer["name"], "tipo": "vetorial",
                                    "feicoes": layer["feature_count"], "formato": det.format_label})
                    msgs += [f"{layer['name']}: {x}" for x in m]
            else:
                with conn.transaction():
                    layer = _import_raster(conn, job, path, work, storage, rows[0]["id"])
                created.append({"id": str(layer["id"]), "nome": layer["name"], "tipo": "raster",
                                "bandas": layer["band_count"], "formato": det.format_label})
        except USER_ERRORS as exc:
            failures.append(f"{path.name}: {exc}")
    if not created:
        raise DetectError("; ".join(failures) or "Nenhuma camada importada.")
    msgs += [f"Não importado — {f}" for f in failures]
    conn.execute("UPDATE app.datasets SET status='imported' WHERE id = ANY(%s)", ([r["id"] for r in rows],))
    return {"camadas": created}, msgs


def _import_raster(conn, job, path: Path, work: Path, storage, dataset_id) -> dict:
    jobs.progress(job["id"], 30, f"Convertendo {path.name} para Cloud Optimized GeoTIFF")
    layer_id = uuid.uuid4()
    cog = work / f"{layer_id.hex}.tif"
    info = to_cog(path, cog)
    from pyproj import CRS
    srid = crsmod.srid_for_crs(conn, CRS.from_wkt(info["crs_wkt"]))
    key = f"projects/{job['project_id']}/rasters/{layer_id.hex}.tif"
    jobs.progress(job["id"], 80, "Gravando no armazenamento")
    storage.put_file(cog, key)
    w, so, e, n = info["bounds_4326"]
    conn.execute(
        """INSERT INTO app.layers (id, project_id, dataset_id, source_job_id, kind, name, srid, cog_key, band_count,
                                   band_dtype, nodata, raster_stats, bbox_4326, editable, created_by)
           VALUES (%s,%s,%s,%s,'raster',%s,%s,%s,%s,%s,%s,%s, ST_MakeEnvelope(%s,%s,%s,%s,4326), false, %s)""",
        (layer_id, job["project_id"], dataset_id, job["id"], path.stem, srid, key, info["count"], info["dtype"],
         info["nodata"], Jsonb(info), w, so, e, n, job["user_id"]))
    style = {"bandas": [1, 2, 3] if info["count"] >= 3 else [1], "paleta": "cinza", "realce": "percentil"}
    add_to_project_top(conn, job["project_id"], layer_id, style=style)
    return conn.execute("SELECT * FROM app.layers WHERE id=%s", (layer_id,)).fetchone()


@celery_app.task(name="webgis.import_dataset")
def import_dataset(job_id: str) -> None:
    _run(job_id, _import_body)


# ------------------------------------------------------------------ ferramentas

def _tool_body(conn, job, work: Path):
    def prog(p, m):
        jobs.progress(job["id"], p, m)
    ctx = vtools.Ctx(conn, job["project_id"], job["user_id"], job["id"], prog)
    out = vtools.run(ctx, job["tool_id"], job["params"])
    layer = out["camada"]
    result = {"camada": {"id": str(layer["id"]), "nome": layer["name"], "feicoes": layer["feature_count"]},
              "estatisticas": out["estatisticas"]}
    return result, out["mensagens"]


@celery_app.task(name="webgis.run_tool")
def run_tool(job_id: str) -> None:
    _run(job_id, _tool_body)


# ------------------------------------------------------------------ exportação

def _export_body(conn, job, work: Path):
    p = job["params"]
    layer = conn.execute("SELECT * FROM app.layers WHERE id=%s AND project_id=%s",
                         (p["layer_id"], job["project_id"])).fetchone()
    if not layer:
        raise ExportError("Camada não encontrada.")
    storage = get_storage()
    fmt = p["formato"]
    msgs: list[str] = []
    jobs.progress(job["id"], 20, "Gerando arquivo")
    if layer["kind"] == "raster":
        if fmt != "geotiff":
            raise ExportError("Camadas raster são exportadas como GeoTIFF.")
        from geo.io.export import slug
        path = work / f"{slug(layer['name'])}.tif"
        storage.get_to_file(layer["cog_key"], path)
        msgs.append("Exportado como Cloud Optimized GeoTIFF (compatível com qualquer leitor GeoTIFF).")
    else:
        path, msgs = export_vector(conn, layer, fmt, work / "out")
    key = f"projects/{job['project_id']}/exports/{job['id']}/{path.name}"
    jobs.progress(job["id"], 85, "Gravando no armazenamento")
    storage.put_file(path, key)
    size = path.stat().st_size
    exp = conn.execute(
        "INSERT INTO app.exports (project_id, layer_id, job_id, format, storage_key, filename, size_bytes, user_id)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (job["project_id"], layer["id"], job["id"], fmt, key, path.name, size, job["user_id"])).fetchone()
    return {"exportacao_id": str(exp["id"]), "arquivo": path.name, "tamanho_bytes": size}, msgs


@celery_app.task(name="webgis.export_layer")
def export_layer(job_id: str) -> None:
    _run(job_id, _export_body)


TASKS = {"import": import_dataset, "tool": run_tool, "export": export_layer}


def enqueue(job: dict) -> None:
    task = TASKS[job["kind"]]
    res = task.apply_async(args=[str(job["id"])])
    with connection() as conn:
        conn.execute("UPDATE app.jobs SET celery_id=%s WHERE id=%s", (res.id, job["id"]))
