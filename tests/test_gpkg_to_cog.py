import gzip
import shutil
import sqlite3
from pathlib import Path

import pytest

from geopaktile.gpkg_to_cog import BadTileError, check_tiles, gpkg_tiles_to_cog

WEMBURY = Path("tests/test_data/wembury.gpkg")
COG_PATH = Path("tests/out/wembury_cog.tif")

# Bad tile data, and text the diagnostic message should contain for it.
BAD_TILES = {
    "empty": (b"", "empty (0 bytes)"),
    "html_error_page": (
        b"<html><head><title>429 Too Many Requests</title></head></html>",
        "429 Too Many Requests",
    ),
    "json_error": (b'{"error": "Missing API key"}', "Missing API key"),
    "gzip": (gzip.compress(b"not an image"), "gzip"),
    "random_bytes": (bytes(range(200, 256)), "unrecognised format"),
    "text_not_blob": ("a text value", "stored as TEXT"),
}


def corrupt_copy(tmp_path: Path, data: bytes | str) -> tuple[Path, str]:
    """Copy wembury.gpkg and overwrite one max-zoom tile with `data`.

    Returns the copy's path and the "Tile z=... col=... row=..." label the
    diagnostics use for the corrupted tile.
    """
    gpkg = tmp_path / "wembury_bad.gpkg"
    shutil.copy(WEMBURY, gpkg)

    with sqlite3.connect(gpkg) as con:
        (table,) = con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'tiles'"
        ).fetchone()
        z, col, row = con.execute(
            f'SELECT zoom_level, tile_column, tile_row FROM "{table}" '
            "ORDER BY zoom_level DESC, tile_row, tile_column LIMIT 1"
        ).fetchone()
        con.execute(
            f'UPDATE "{table}" SET tile_data = ? '
            "WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
            (data, z, col, row),
        )
    con.close()  # the context manager commits but doesn't close
    return gpkg, f"Tile z={z} col={col} row={row}"


def truncated_tile() -> bytes:
    """First half of a real tile from wembury.gpkg."""
    with sqlite3.connect(WEMBURY) as con:
        (table,) = con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'tiles'"
        ).fetchone()
        (data,) = con.execute(
            f'SELECT tile_data FROM "{table}" ORDER BY zoom_level DESC LIMIT 1'
        ).fetchone()
    con.close()
    return data[: len(data) // 2]


def test_wembury_tiles_are_valid():
    assert check_tiles(WEMBURY) == []


@pytest.mark.parametrize("data, expected", BAD_TILES.values(), ids=BAD_TILES.keys())
def test_check_tiles_reports_bad_tile(tmp_path, data, expected):
    gpkg, label = corrupt_copy(tmp_path, data)

    problems = check_tiles(gpkg)

    assert len(problems) == 1
    assert problems[0].startswith(label)
    assert expected in problems[0]


def test_check_tiles_reports_truncated_tile(tmp_path):
    gpkg, label = corrupt_copy(tmp_path, truncated_tile())

    problems = check_tiles(gpkg)

    assert len(problems) == 1
    assert problems[0].startswith(label)
    assert "truncated" in problems[0]


def test_conversion_raises_on_bad_tile(tmp_path):
    gpkg, label = corrupt_copy(tmp_path, b"")

    with pytest.raises(BadTileError, match=label):
        gpkg_tiles_to_cog(gpkg, tmp_path / "out.tif")


def test_conversion_skips_bad_tile(tmp_path):
    gpkg, label = corrupt_copy(tmp_path, b"")
    cog = tmp_path / "out.tif"

    with pytest.warns(UserWarning, match="Skipped 1 tile") as record:
        gpkg_tiles_to_cog(gpkg, cog, skip_bad_tiles=True)

    assert cog.exists()
    assert any(label in str(w.message) for w in record)

def test_wembury():

    Path(COG_PATH).unlink(missing_ok=True)

    gpkg_tiles_to_cog(
        "tests/test_data/wembury.gpkg",
        COG_PATH
    )