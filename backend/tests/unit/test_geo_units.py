"""Testes unitários do pacote geo/ (sem banco, sem HTTP)."""
import datetime as dt
import zipfile

import pytest

from geo import crs as crsmod
from geo.filters import FilterError, build_where, coerce
from geo.io.detect import DetectError, detect, expand_inputs, safe_extract_zip
from geo.io.export import _shp_names, slug
from geo.layerstore import LayerStoreError, clean_field_name, dedupe_names
from geo.registry import catalog
from tests.conftest import FIXTURES


@pytest.mark.parametrize("lon,lat,epsg", [(-47.9, -15.8, 32723), (-60.0, -3.1, 32721), (-61.0, -3.1, 32720), (2.35, 48.85, 32631),
                                          (-180, 0, 32601), (179.99, -10, 32760)])
def test_utm_zone(lon, lat, epsg):
    assert crsmod.utm_epsg(lon, lat) == epsg


def test_parse_and_describe_crs():
    c = crsmod.parse_crs("31983")
    d = crsmod.describe(c)
    assert d["codigo"] == "EPSG:31983" and d["unidade"] == "metre" and "AmericaS 2000" in d["datum"]
    assert crsmod.is_metric(c) and not crsmod.is_metric(crsmod.parse_crs("EPSG:4674"))
    with pytest.raises(crsmod.CRSInputError):
        crsmod.parse_crs("nao-existe")


def test_transform_points_and_datum_warning():
    [[x, y]] = crsmod.transform_points("EPSG:4674", "EPSG:31983", [[-47.9, -15.8]])
    assert 180000 < x < 200000 and 8250000 < y < 8260000
    assert crsmod.datum_warning(crsmod.parse_crs(4326), crsmod.parse_crs(4674)).startswith("Datums diferentes")
    assert crsmod.datum_warning(crsmod.parse_crs(4674), crsmod.parse_crs(31983)) is None


@pytest.mark.parametrize("value,ftype,expected", [
    ("12", "integer", 12), (12.0, "integer", 12), ("1.5", "real", 1.5), ("sim", "boolean", True),
    ("não", "boolean", False), ("2024-02-03", "date", dt.date(2024, 2, 3)), (5, "text", "5"), (None, "integer", None),
])
def test_coerce(value, ftype, expected):
    assert coerce(value, ftype) == expected


@pytest.mark.parametrize("value,ftype", [("1.5", "integer"), ("abc", "real"), ("talvez", "boolean"),
                                         ("31/12/2024", "date"), (True, "integer")])
def test_coerce_errors(value, ftype):
    with pytest.raises(FilterError):
        coerce(value, ftype)


def test_build_where_is_parametrized():
    fields = {"nome": {"column_name": "f_1", "type": "text"}, "n": {"column_name": "f_2", "type": "integer"}}
    w, params = build_where([{"campo": "nome", "operador": "contem", "valor": "a%b"},
                             {"campo": "n", "operador": ">", "valor": "3"}], "qualquer", fields)
    text = w.as_string(None)
    assert '"f_1"::text ILIKE %s' in text and '"f_2" > %s' in text and " OR " in text
    assert params == ["%a\\%b%", 3]
    with pytest.raises(FilterError):
        build_where([{"campo": "nome", "operador": "; DROP", "valor": 1}], "todas", fields)


def test_field_names():
    assert dedupe_names(["a", "A", "fid", "b"]) == ["a", "A_2", "fid_orig", "b"]
    assert clean_field_name("  área   do lote ") == "área do lote"
    with pytest.raises(LayerStoreError):
        clean_field_name("geom")


def test_shapefile_field_names_are_unique_and_short():
    names = _shp_names(["nome_do_responsavel", "nome_do_responsavel_2", "área", "x"])
    assert names == ["nome_do_re", "nome_do_r2", "area", "x"]
    assert slug("Lotes – Área Norte!") == "Lotes_Area_Norte"


def test_safe_zip_rejects_symlink_and_bomb(tmp_path):
    z = tmp_path / "link.zip"
    with zipfile.ZipFile(z, "w") as zf:
        info = zipfile.ZipInfo("ln")
        info.external_attr = (0o120777 << 16)
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(DetectError, match="links simbólicos"):
        safe_extract_zip(z, tmp_path / "o", 10 ** 6)
    big = tmp_path / "big.zip"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.geojson", "0" * 2_000_000)
    with pytest.raises(DetectError, match="limite"):
        safe_extract_zip(big, tmp_path / "o2", 1_000_000)


def test_detect_formats():
    assert detect(FIXTURES / "lotes.geojson").format_label == "GeoJSON"
    assert detect(FIXTURES / "nascentes.gpkg").layers == ["nascentes"]
    assert detect(FIXTURES / "imagem_4bandas.tif").kind == "raster"
    with pytest.raises(DetectError, match="corrompido"):
        detect(FIXTURES / "corrompido.gpkg")


def test_expand_inputs_messages(tmp_path):
    (tmp_path / "a.dbf").write_bytes(b"x")
    with pytest.raises(DetectError, match=".shp ausente"):
        expand_inputs([tmp_path / "a.dbf"], tmp_path / "w", 10 ** 6)
    (tmp_path / "b.dxf").write_bytes(b"x")
    with pytest.raises(DetectError, match="DXF"):
        expand_inputs([tmp_path / "b.dxf"], tmp_path / "w", 10 ** 6)


def test_catalog_covers_prompt_tools_and_marks_unavailable():
    cat = {t["id"]: t for t in catalog()}
    for tid in ["vector.buffer", "vector.clip", "vector.intersection", "vector.dissolve"]:
        assert cat[tid]["status"] == "disponivel"
    for tid in ["vector.union", "network.shortest_path", "terrain.slope", "spectral.ndvi", "analysis.voronoi"]:
        assert cat[tid]["status"] == "indisponivel" and cat[tid]["parametros"] == []
    assert len(cat) == len(catalog())
