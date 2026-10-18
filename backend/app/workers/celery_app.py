from celery import Celery

from app.core.config import get_settings

_s = get_settings()

celery_app = Celery("webgis", broker=_s.redis_url, backend=_s.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_always_eager=_s.celery_task_always_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=3 * 3600,
    task_time_limit=3 * 3600 + 120,
    task_serializer="json",
    accept_content=["json"],
    result_expires=24 * 3600,
    broker_connection_retry_on_startup=True,
)
