"""Armazenamento S3 (o mesmo protocolo do MinIO) contra um servidor S3 real em processo (moto server):
upload, download, URL assinada e leitura de COG pelo GDAL via /vsis3 — o caminho usado em produção."""
import os
import urllib.request

import boto3
import pytest

from app.core.config import Settings
from app.storage import S3Storage, gdal_env
from tests.conftest import FIXTURES


@pytest.fixture(scope="module")
def s3_server():
    from moto.server import ThreadedMotoServer
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    srv = ThreadedMotoServer(ip_address="127.0.0.1", port=5059)
    srv.start()
    yield "http://127.0.0.1:5059"
    srv.stop()


@pytest.fixture()
def storage(s3_server):
    s = Settings(storage_backend="s3", s3_bucket="webgis-teste", s3_endpoint_url=s3_server,
                 s3_access_key="teste", s3_secret_key="teste", s3_region="us-east-1")
    boto3.client("s3", endpoint_url=s3_server, aws_access_key_id="teste", aws_secret_access_key="teste",
                 region_name="us-east-1").create_bucket(Bucket="webgis-teste")
    return s, S3Storage(s)


def test_put_get_signed_url_delete(storage, tmp_path):
    s, st = storage
    key = "projects/p1/exports/j1/lotes.geojson"
    st.put_file(FIXTURES / "lotes.geojson", key)
    assert st.exists(key)
    st.get_to_file(key, tmp_path / "x.geojson")
    assert (tmp_path / "x.geojson").read_bytes() == (FIXTURES / "lotes.geojson").read_bytes()
    url = st.signed_url(key, "lotes.geojson")
    assert "X-Amz-Signature" in url and "X-Amz-Expires=900" in url
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url) as r:
        assert r.read() == (FIXTURES / "lotes.geojson").read_bytes()
    st.delete(key)
    assert not st.exists(key)
    with pytest.raises(ValueError):
        st.put_file(FIXTURES / "lotes.geojson", "projects/../../etc/passwd")


def test_gdal_reads_cog_from_s3(storage, tmp_path):
    from geo.raster.ingest import to_cog
    from geo.raster.tiles import render_tile, sample_point
    s, st = storage
    cog = tmp_path / "img.tif"
    info = to_cog(FIXTURES / "imagem_4bandas.tif", cog)
    st.put_file(cog, "projects/p1/rasters/img.tif")
    env = gdal_env(s)
    assert env["session"].endpoint_url == "127.0.0.1:5059" and env["AWS_HTTPS"] == "NO"
    path = st.gdal_path("projects/p1/rasters/img.tif")
    assert path == "/vsis3/webgis-teste/projects/p1/rasters/img.tif"
    from pyproj import Transformer
    lon, lat = Transformer.from_crs(31983, 4326, always_xy=True).transform(190055, 8250995)
    assert sample_point(path, lon, lat, env) == [1005, 2005, 3005, 4005]
    from tests.integration.helpers import tile_xyz
    z, x, y = tile_xyz(lon, lat, 14)
    png = render_tile(path, z, x, y, info["estatisticas"], env=env)
    assert png[:4] == b"\x89PNG"
