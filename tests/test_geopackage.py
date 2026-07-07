import json
import os
from pathlib import Path

import pytest
import requests

from pygeopkgxyz.pygeopkgxyz import create_tile_geopackage, add_xyz_tiles_to_geopackage
from pygeopkgxyz.tilematrix_models import TileMatrixSet


@pytest.fixture()
def osm_tiles_z0_z3() -> list[tuple[int, int, int, bytes]]:
    """
    Download OpenStreetMap XYZ tiles for zoom levels 0 and 1.

    Returns
    -------
    list[pathlib.Path]
        Local paths to downloaded PNG tiles.
    """

    root = Path("tests/data/osmtiles")

    tiles: list[tuple[int, int, int, bytes]] = []

    headers = {"User-Agent": "pytest-osm-tile-fixture/1.0"}

    for z in range(4):
        for x in range(2**z):
            for y in range(2**z):
                path = root / str(z) / str(x) / f"{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)

                if not path.exists():
                    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"

                    response = requests.get(
                        url,
                        headers=headers,
                        timeout=30,
                    )
                    response.raise_for_status()

                    path.write_bytes(response.content)

                tiles.append((z, x, y, path.read_bytes()))

    return tiles


@pytest.fixture()
def os_tiles_z0() -> list[tuple[int, int, int, bytes]]:
    """
    Download OpenStreetMap XYZ tiles for zoom levels 0 and 1.

    Returns
    -------
    list[pathlib.Path]
        Local paths to downloaded PNG tiles.
    """
    OS_API_KEY = os.environ["OS_API_KEY"]

    root = Path("tests/data/ostiles")

    tiles: list[tuple[int, int, int, bytes]] = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    }

    for z in range(1):
        for x in range(5):
            for y in range(7):
                path = root / str(z) / str(x) / f"{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)

                if not path.exists():
                    try:
                        url = f"https://api.os.uk/maps/raster/v1/zxy/Leisure_27700/{z}/{x}/{y}.png?key={OS_API_KEY}"

                        response = requests.get(
                            url,
                            headers=headers,
                            timeout=30,
                        )
                        response.raise_for_status()

                        path.write_bytes(response.content)
                    except requests.HTTPError:
                        pass

                if path.exists():
                    tiles.append((z, x, y, path.read_bytes()))

    if not tiles:
        raise ValueError("No tiles were found.")

    return tiles


@pytest.fixture()
def test_gpkg() -> Path:
    p = Path("tests/out/test.gpkg")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    return p


@pytest.fixture()
def test_27700_gpkg() -> Path:
    p = Path("tests/out/test_27700.gpkg")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    return p

@pytest.fixture
def os_27700_tms() -> TileMatrixSet:
    """
    EPSG:27700 TileMatrixSet as published by the OS Maps API, using the
    OGC 0.28mm standardized pixel size. 14 zoom levels (0-13), consistent
    TopLeftCorner across all levels.
    """
    data = json.loads(Path("tests/27700.json").read_text())
    return TileMatrixSet.model_validate(data)


def test_geopackage_creation(osm_tiles_z0_z3, test_gpkg):
    create_tile_geopackage(test_gpkg)
    add_xyz_tiles_to_geopackage(test_gpkg, osm_tiles_z0_z3)


def test_other_epsg(os_tiles_z0, os_27700_tms, test_27700_gpkg):
    create_tile_geopackage(
        test_27700_gpkg,
        tms=os_27700_tms
    )
    add_xyz_tiles_to_geopackage(test_27700_gpkg, os_tiles_z0, tms=os_27700_tms)
