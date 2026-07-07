from pathlib import Path

import pytest
import requests

from pygeopkgxyz.pygeopkgxyz import create_tile_geopackage, add_xyz_tiles_to_geopackage


@pytest.fixture()
def osm_tiles_z0_z3() -> list[tuple[int, int, int, bytes]]:
    """
    Download OpenStreetMap XYZ tiles for zoom levels 0 and 1.

    Returns
    -------
    list[pathlib.Path]
        Local paths to downloaded PNG tiles.
    """

    root = Path('tests/data/osmtiles')

    tiles: list[tuple[int, int, int, bytes]] = []

    headers = {
        "User-Agent": "pytest-osm-tile-fixture/1.0"
    }

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

def test_geopackage_creation(osm_tiles_z0_z3):
    create_tile_geopackage('tests/out/test.gpkg')
    add_xyz_tiles_to_geopackage('tests/out/test.gpkg', osm_tiles_z0_z3)
