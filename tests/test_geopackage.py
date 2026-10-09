import math
import pickle
from pathlib import Path

import morecantile
import numpy as np
import pytest
import rasterio
import requests
from morecantile.commons import BoundingBox
from rio_cogeo.cogeo import cog_validate

from geopaktile import GeoPakTile, gpkg_tiles_to_cog


def _get_osm_tile(z: int, x: int, y: int) -> bytes:
    """
    Download an OpenStreetMap XYZ tile.

    Parameters
    ----------
    z : int
        Zoom level.
    x : int
        X coordinate.
    y : int
        Y coordinate.

    Returns
    -------
    bytes
        The tile image data in bytes.
    """
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    headers = {"User-Agent": "pytest-osm-tile-fixture/1.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.content


@pytest.fixture()
def osm_tiles_z0_z3() -> list[tuple[int, int, int, bytes]]:
    """
    Download OpenStreetMap XYZ tiles for zoom levels 0 to 3.

    Returns
    -------
    list[tuple[int, int, int, bytes]]
        List of tuples containing zoom level, x, y coordinates and tile bytes.
    """

    root = Path("tests/data/osmtiles/z0_z3")
    tiles: list[tuple[int, int, int, bytes]] = []

    for z in range(4):
        for x in range(2**z):
            for y in range(2**z):
                path = root / str(z) / str(x) / f"{y}.png"
                path.parent.mkdir(parents=True, exist_ok=True)

                if not path.exists():
                    content = _get_osm_tile(z, x, y)
                    path.write_bytes(content)

                tiles.append((z, x, y, path.read_bytes()))

    return tiles

@pytest.fixture()
def os_tiles_small_to_15() -> tuple[list[tuple[int, int, int, bytes]], BoundingBox]:

    root = Path("tests/data/osmtiles/small_to_z15")
    pickle_path = root / "osm_tiles_small_to_15.pkl"
    
    
    if pickle_path.exists():
        with open(pickle_path, "rb") as f:
            tiles = pickle.load(f)
        return tiles

    tms = morecantile.tms.get("WebMercatorQuad")
    tms_tiles = list(
        tms.tiles(
            west=-3.968,
            south=50.554,
            east=-3.963,
            north=50.56,
            zooms=list(range(16)),
        )
    )

    # Compute the overall extent of the tile set in geographic coordinates.
    tile_bounds = [tms.xy_bounds(tile) for tile in tms_tiles]
    overall_bbox = BoundingBox(
        min(bounds[0] for bounds in tile_bounds),
        min(bounds[1] for bounds in tile_bounds),
        max(bounds[2] for bounds in tile_bounds),
        max(bounds[3] for bounds in tile_bounds),
    )

    tiles: list[tuple[int, int, int, bytes]] = []
    
    for t in tms_tiles:
        path = root / str(t.z) / str(t.x) / f"{t.y}.png"
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            content = _get_osm_tile(t.z, t.x, t.y)
            path.write_bytes(content)

        tiles.append((t.z, t.x, t.y, path.read_bytes()))

    return tiles, overall_bbox

@pytest.fixture()
def test_gpkg_path() -> Path:
    p = Path("tests/out/test.gpkg")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    return p

@pytest.fixture()
def test_gpkg_path_z15() -> Path:
    p = Path("tests/out/test_z15.gpkg")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    return p


@pytest.fixture()
def test_27700_gpkg() -> Path:
    p = Path("tests/out/test_27700.gpkg")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    return p


def test_geopackage_creation(osm_tiles_z0_z3, test_gpkg_path):

    gpkg = GeoPakTile(test_gpkg_path, tms=morecantile.tms.get("WebMercatorQuad"), mode='rwc')
    gpkg.add_tiles(osm_tiles_z0_z3)
    gpkg.close()

    with rasterio.open(test_gpkg_path) as src:
        assert src.count == 4
        assert src.width > 0
        assert src.height > 0
        assert len(src.overviews(1)) == 3
        assert src.crs.to_string() == "EPSG:3857"

    # test convert to COG
    cog_path = test_gpkg_path.with_suffix(".cog.tif")
    gpkg_tiles_to_cog(test_gpkg_path, cog_path, overwrite=True)

    with rasterio.open(cog_path) as src:
        assert src.count == 4
        assert src.width > 0
        assert src.height > 0
        assert len(src.overviews(1)) == 3
        assert src.crs.to_string() == "EPSG:3857"

    assert cog_validate(cog_path)[0]

def test_geopackage_creation_context(osm_tiles_z0_z3, test_gpkg_path):

    with GeoPakTile(test_gpkg_path, tms=morecantile.tms.get("WebMercatorQuad"), mode='rwc') as gpkg:
        gpkg.add_tiles(osm_tiles_z0_z3)

    with rasterio.open(test_gpkg_path) as src:
            assert src.count == 4
            assert src.width > 0
            assert src.height > 0
            assert len(src.overviews(1)) == 3
            assert src.crs.to_string() == "EPSG:3857"

def test_geopackage_creation_context_z15(os_tiles_small_to_15, test_gpkg_path_z15):

    tiles, bbox = os_tiles_small_to_15

    with GeoPakTile(test_gpkg_path_z15, tms=morecantile.tms.get("WebMercatorQuad"), mode='rwc') as gpkg:
        gpkg.add_tiles(tiles)

    with rasterio.open(test_gpkg_path_z15) as src:
            assert src.count == 4
            assert src.width > 0
            assert src.height > 0
            assert len(src.overviews(1)) == 15
            assert src.crs.to_string() == "EPSG:3857"
            assert math.isclose(src.bounds.left, bbox.left, rel_tol=1e-5)
            assert math.isclose(src.bounds.bottom, bbox.bottom, rel_tol=1e-5)
            assert math.isclose(src.bounds.right, bbox.right, rel_tol=1e-5)
            assert math.isclose(src.bounds.top, bbox.top, rel_tol=1e-5)

    cog_path = test_gpkg_path_z15.with_suffix(".cog.tif")
    gpkg_tiles_to_cog(test_gpkg_path_z15, cog_path, overwrite=True)

    with rasterio.open(cog_path) as src:
        assert src.count == 4
        assert src.width > 0
        assert src.height > 0
        assert len(src.overviews(1)) == 8 # not 15 - any more than this results in less than 1 pixel in the overviews
        assert src.crs.to_string() == "EPSG:3857"

    assert cog_validate(cog_path)[0]

def test_has_tile(osm_tiles_z0_z3, test_gpkg_path):

    with GeoPakTile(test_gpkg_path, tms=morecantile.tms.get("WebMercatorQuad"), mode='rwc') as gpkg:
        gpkg.add_tiles(osm_tiles_z0_z3)

    # repoen in read-only mode
    with GeoPakTile(test_gpkg_path, mode='ro') as gpkg:
        for t in osm_tiles_z0_z3:
            assert gpkg.has_tile(t[0], t[1], t[2])
        
        assert not gpkg.has_tile(0, 0, 99999)


def test_has_tiles(osm_tiles_z0_z3, test_gpkg_path):

    with GeoPakTile(test_gpkg_path, tms=morecantile.tms.get("WebMercatorQuad"), mode='rwc') as gpkg:
        gpkg.add_tiles(osm_tiles_z0_z3)

    # repoen in read-only mode
    with GeoPakTile(test_gpkg_path, mode='ro') as gpkg:
        
        # All tiles present
        zxys = [(t[0], t[1], t[2]) for t in osm_tiles_z0_z3]
        results = gpkg.has_tiles(zxys)
        n = np.count_nonzero(results)
        assert n == len(zxys)
        assert False not in results

        # Add a tile that isn't present
        zxys.append((3,1,999))
        results = gpkg.has_tiles(zxys)
        n = np.count_nonzero(results)
        assert n == len(zxys) - 1
        nf = np.count_nonzero(~results)
        assert nf == 1

        # Test a long query
        nt = 10_000_000
        base = np.asarray(zxys, dtype=np.int32)
        reps = (nt + len(base) - 1) // len(base)
        zxys = np.tile(base, (reps, 1))[:nt]
        count = np.count_nonzero(zxys[:,2] == 999)

        #zxys = zxys * nt
        results = gpkg.has_tiles(zxys)
        n = np.count_nonzero(results)
        assert n == len(zxys) - count
        nf = np.count_nonzero(~results)
        assert nf == count