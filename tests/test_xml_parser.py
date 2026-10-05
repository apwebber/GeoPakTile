from pathlib import Path

import diskcache
import pytest
import requests

from pygeopkgxyz.xml_parser import parse_capabilities

xml_cache = diskcache.Cache('tests/.diskcache/xml')
EXPIRE = 2.592e6 # 30 days

@pytest.fixture
@xml_cache.memoize(expire=EXPIRE)
def earthdata_4326_xml():
    url = 'https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities'
    res = requests.get(url)
    res.raise_for_status()

    return res.text

@pytest.fixture
@xml_cache.memoize(expire=EXPIRE)
def earthdata_3413_xml():
    url = 'https://gibs.earthdata.nasa.gov/wmts/epsg3413/best/wms.cgi?SERVICE=WMS&REQUEST=GetCapabilities'
    res = requests.get(url)
    res.raise_for_status()

    return res.text

@pytest.fixture
@xml_cache.memoize(expire=EXPIRE)
def earthdata_3857_xml():
    url = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities'
    res = requests.get(url)
    res.raise_for_status()

    return res.text

@pytest.fixture
@xml_cache.memoize(expire=EXPIRE)
def earthdata_3031_xml():
    url = 'https://gibs.earthdata.nasa.gov/wmts/epsg3031/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities'
    res = requests.get(url)
    res.raise_for_status()
    return res.text

@pytest.fixture
def os_27700_xml():
    return Path('tests/27700.xml').read_text()
        

def test_parse_earthdata(earthdata_4326_xml, earthdata_3857_xml, earthdata_3413_xml, earthdata_3031_xml, os_27700_xml):
    tmss = parse_capabilities(earthdata_4326_xml)
    assert len(tmss) == 7

    tmss = parse_capabilities(earthdata_3413_xml)
    assert len(tmss) == 4

    tmss = parse_capabilities(earthdata_3857_xml)
    assert len(tmss) == 7

    tmss = parse_capabilities(earthdata_3031_xml)
    assert len(tmss) == 3

    tmss = parse_capabilities(os_27700_xml)
    with open('tests/27700.json', 'w') as f:
        f.write(tmss[0].model_dump_json(indent=2))
    assert len(tmss) == 2