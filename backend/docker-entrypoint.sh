#!/bin/sh
set -e
case "$1" in
  api)
    python -m app.db.migrate
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${API_WORKERS:-2}" --proxy-headers
    ;;
  worker)
    exec celery -A app.workers.celery_app worker --loglevel=info --concurrency="${WORKER_CONCURRENCY:-2}"
    ;;
  migrate)
    exec python -m app.db.migrate
    ;;
  *)
    exec "$@"
    ;;
esac
