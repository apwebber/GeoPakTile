from pathlib import Path

import pytest
import requests

from geopaktile import parse_capabilities

TEST_DATA = Path("tests/test_data")
GIBS = "https://gibs.earthdata.nasa.gov"


def cached_xml(filename: str, url: str) -> str:
    """Read a capabilities document from tests/test_data, downloading it if missing.

    Commit the downloaded file to the repo so tests run offline. Delete it to
    fetch a fresh copy.
    """
    path = TEST_DATA / filename
    print(path)
    if path.exists():
        return path.read_text(encoding="utf-8")

    res = requests.get(url, timeout=60)
    res.raise_for_status()  # only save successful downloads

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(res.text, encoding="utf-8")
    return res.text


@pytest.fixture
def earthdata_4326_xml():
    return cached_xml(
        "earthdata_4326.xml",
        f"{GIBS}/wmts/epsg4326/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities",
    )


@pytest.fixture
def earthdata_3413_xml():
    return cached_xml(
        "earthdata_3413.xml",
        f"{GIBS}/wmts/epsg3413/best/wms.cgi?SERVICE=WMS&REQUEST=GetCapabilities",
    )


@pytest.fixture
def earthdata_3857_xml():
    return cached_xml(
        "earthdata_3857.xml",
        f"{GIBS}/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities",
    )


@pytest.fixture
def earthdata_3031_xml():
    return cached_xml(
        "earthdata_3031.xml",
        f"{GIBS}/wmts/epsg3031/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities",
    )


@pytest.fixture
def os_27700_xml():
    return Path("tests/test_data/27700.xml").read_text()


def test_parse_earthdata(
    earthdata_4326_xml,
    earthdata_3857_xml,
    earthdata_3413_xml,
    earthdata_3031_xml,
    os_27700_xml,
):
    tmss = parse_capabilities(earthdata_4326_xml)
    assert len(tmss) == 7

    tmss = parse_capabilities(earthdata_3413_xml)
    assert len(tmss) == 4

    tmss = parse_capabilities(earthdata_3857_xml)
    assert len(tmss) == 7

    tmss = parse_capabilities(earthdata_3031_xml)
    assert len(tmss) == 3

    tmss = parse_capabilities(os_27700_xml)
    assert len(tmss) == 2