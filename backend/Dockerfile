# API e worker usam a mesma imagem. GDAL/PROJ vêm nas wheels de pyogrio, rasterio e pyproj.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 curl && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 webgis
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY geo ./geo
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /data && chown webgis /data

USER webgis
ENV WORK_DIR=/data/work STORAGE_LOCAL_DIR=/data/storage
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
