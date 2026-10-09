"""Convert a GeoPackage tile pyramid layer to a Cloud Optimized GeoTIFF.

The highest selected zoom level becomes the full-resolution image and each
lower zoom level is copied, unresampled, into the COG as an overview.

Requires: numpy, pillow, rasterio (with GDAL >= 3.1 for the COG driver)

How it works:
    1. Each selected zoom level is mosaicked into a temporary GeoTIFF
       covering the same extent.
    2. A VRT is written whose band(s) point at the base level and list the
       other levels as explicit <Overview> elements.
    3. GDAL's COG driver copies the VRT with OVERVIEWS=FORCE_USE_EXISTING,
       so the zoom-level pixels become the overviews instead of GDAL
       resampling new ones.

For the levels to line up exactly, the extent is snapped outward to the pixel
grid of the coarsest selected level. By default the coarsest level is chosen
so that the extent is about one tile across there, which keeps that snapping
to a fraction of a percent of the extent.
"""

from __future__ import annotations

import io
import math
import sqlite3
import tempfile
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import rasterio
import rasterio.shutil
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from rasterio.windows import Window

SUPPORTED_BANDS = {"RGBA": 4, "RGB": 3}
COLOR_INTERP = ["Red", "Green", "Blue", "Alpha"]
_EPS = 1e-6


@dataclass(frozen=True)
class _Level:
    zoom: int
    matrix_width: int
    matrix_height: int
    tile_width: int
    tile_height: int
    px: float  # pixel width in CRS units
    py: float  # pixel height in CRS units


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _as_int(value: float, what: str) -> int:
    """Round to int, warning if the value wasn't (nearly) integral."""
    rounded = round(value)
    if abs(value - rounded) > 1e-3:
        warnings.warn(
            f"{what} is {value:.4f} pixels, not a whole number; rounding. "
            "Zoom levels may not be exact multiples of each other.",
            stacklevel=3,
        )
    return int(rounded)


def gpkg_tiles_to_cog(
    gpkg_path: str | Path,
    cog_path: str | Path,
    table: str | None = None,
    *,
    bbox: Sequence[float] | None = None,
    bbox_crs: str | CRS | None = None,
    min_zoom: int | None = None,
    max_zoom: int | None = None,
    bands: str = "RGBA",
    compress: str = "DEFLATE",
    blocksize: int | None = None,
    overwrite: bool = False,
) -> Path:
    """Convert a GeoPackage tile layer to a COG, using zoom levels as overviews.

    Args:
        gpkg_path: Path to the .gpkg file.
        cog_path: Output GeoTIFF path.
        table: Tile table name. Optional if the GeoPackage has exactly one.
        bbox: (min_x, min_y, max_x, max_y) to clip to. Defaults to the extent
            of the tiles present at max_zoom.
        bbox_crs: CRS of bbox (e.g. "EPSG:4326"). Defaults to the layer's CRS.
        min_zoom: Coarsest zoom level to include as an overview. Defaults to
            the level at which the extent is about one tile across.
        max_zoom: Zoom level used for full resolution. Defaults to the
            highest zoom level that has tiles.
        bands: "RGBA" (missing tiles become transparent) or "RGB" (missing
            tiles become black; required for JPEG compression).
        compress: COG compression, e.g. "DEFLATE", "ZSTD", "LZW", "WEBP", "JPEG".
        blocksize: COG internal tile size. Defaults to the GeoPackage tile width.
        overwrite: Replace an existing output file.

    Returns:
        Path to the written COG.
    """
    if bands not in SUPPORTED_BANDS:
        raise ValueError(f"bands must be one of {sorted(SUPPORTED_BANDS)}")
    if compress.upper() == "JPEG" and bands != "RGB":
        raise ValueError('JPEG compression requires bands="RGB"')
    n_bands = SUPPORTED_BANDS[bands]

    cog_path = Path(cog_path)
    if cog_path.exists() and not overwrite:
        raise FileExistsError(f"{cog_path} exists; pass overwrite=True")

    uri = Path(gpkg_path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        # --- Tile table, tile matrix set and CRS ----------------------------
        tables = [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type = 'tiles'"
            )
        ]
        if table is None:
            if len(tables) != 1:
                raise ValueError(f"Specify table=; tile tables found: {tables}")
            table = tables[0]
        elif table not in tables:
            raise ValueError(f"{table!r} is not a tile table; found: {tables}")
        qtable = _quote_ident(table)

        srs_id, tms_min_x, tms_min_y, tms_max_x, tms_max_y = con.execute(
            "SELECT srs_id, min_x, min_y, max_x, max_y "
            "FROM gpkg_tile_matrix_set WHERE table_name = ?",
            (table,),
        ).fetchone()
        org, org_id, wkt = con.execute(
            "SELECT organization, organization_coordsys_id, definition "
            "FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
            (srs_id,),
        ).fetchone()
        if org and org.upper() == "EPSG":
            crs = CRS.from_epsg(int(org_id))
        else:
            crs = CRS.from_wkt(wkt)

        # --- Zoom levels that actually contain tiles ------------------------
        present = {
            z
            for (z,) in con.execute(f"SELECT DISTINCT zoom_level FROM {qtable}")
        }
        levels = {
            row[0]: _Level(*row)
            for row in con.execute(
                "SELECT zoom_level, matrix_width, matrix_height, tile_width, "
                "tile_height, pixel_x_size, pixel_y_size "
                "FROM gpkg_tile_matrix WHERE table_name = ? ORDER BY zoom_level",
                (table,),
            )
            if row[0] in present
        }
        if not levels:
            raise ValueError(f"Table {table!r} contains no tiles")

        if max_zoom is None:
            max_zoom = max(levels)
        if max_zoom not in levels:
            raise ValueError(f"max_zoom {max_zoom} has no tiles; have {sorted(levels)}")
        base = levels[max_zoom]

        # --- Requested extent, in the layer's CRS ---------------------------
        if bbox is None:
            cmin, cmax, rmin, rmax = con.execute(
                f"SELECT MIN(tile_column), MAX(tile_column), MIN(tile_row), "
                f"MAX(tile_row) FROM {qtable} WHERE zoom_level = ?",
                (max_zoom,),
            ).fetchone()
            bx0 = tms_min_x + cmin * base.tile_width * base.px
            bx1 = tms_min_x + (cmax + 1) * base.tile_width * base.px
            by1 = tms_max_y - rmin * base.tile_height * base.py
            by0 = tms_max_y - (rmax + 1) * base.tile_height * base.py
        else:
            bx0, by0, bx1, by1 = bbox
            if bbox_crs is not None and CRS.from_user_input(bbox_crs) != crs:
                bx0, by0, bx1, by1 = transform_bounds(
                    bbox_crs, crs, bx0, by0, bx1, by1, densify_pts=21
                )
        bx0, by0 = max(bx0, tms_min_x), max(by0, tms_min_y)
        bx1, by1 = min(bx1, tms_max_x), min(by1, tms_max_y)
        if bx0 >= bx1 or by0 >= by1:
            raise ValueError("bbox does not overlap the tile matrix set")

        # --- Choose the coarsest level --------------------------------------
        candidates = sorted(z for z in levels if z <= max_zoom)
        if min_zoom is None:
            # Coarsest level at which the extent is still at least ~one tile.
            min_zoom = max_zoom
            for z in reversed(candidates):
                lv = levels[z]
                min_zoom = z
                if (bx1 - bx0) / lv.px <= lv.tile_width and (
                    by1 - by0
                ) / lv.py <= lv.tile_height:
                    break
        selected = [z for z in candidates if z >= min_zoom]
        coarse = levels[selected[0]]

        # --- Snap the extent to the coarsest level's pixel grid -------------
        x0 = tms_min_x + math.floor((bx0 - tms_min_x) / coarse.px + _EPS) * coarse.px
        x1 = tms_min_x + math.ceil((bx1 - tms_min_x) / coarse.px - _EPS) * coarse.px
        y1 = tms_max_y - math.floor((tms_max_y - by1) / coarse.py + _EPS) * coarse.py
        y0 = tms_max_y - math.ceil((tms_max_y - by0) / coarse.py - _EPS) * coarse.py

        if blocksize is None:
            blocksize = base.tile_width

        with tempfile.TemporaryDirectory(prefix="gpkg2cog_") as tmp:
            tmpdir = Path(tmp)
            level_files: list[tuple[Path, int, int]] = []

            # Finest first: base level, then overviews in decreasing size.
            for z in sorted(selected, reverse=True):
                lv = levels[z]
                col_off = _as_int((x0 - tms_min_x) / lv.px, f"z{z} column offset")
                row_off = _as_int((tms_max_y - y1) / lv.py, f"z{z} row offset")
                width = _as_int((x1 - x0) / lv.px, f"z{z} width")
                height = _as_int((y1 - y0) / lv.py, f"z{z} height")
                path = tmpdir / f"z{z}.tif"
                _mosaic_level(
                    con, qtable, lv, path, crs,
                    col_off, row_off, width, height,
                    x0, y1, bands, n_bands,
                )
                level_files.append((path, width, height))

            vrt_path = tmpdir / "pyramid.vrt"
            vrt_path.write_text(
                _pyramid_vrt(level_files, crs, (x0, base.px, 0, y1, 0, -base.py), n_bands)
            )

            options = {
                "COMPRESS": compress,
                "BLOCKSIZE": blocksize,
                "OVERVIEWS": "FORCE_USE_EXISTING",
                "BIGTIFF": "IF_SAFER",
            }
            if compress.upper() in {"DEFLATE", "ZSTD", "LZW"}:
                options["PREDICTOR"] = "YES"
            if cog_path.exists():
                cog_path.unlink()
            rasterio.shutil.copy(str(vrt_path), str(cog_path), driver="COG", **options)
    finally:
        con.close()

    return cog_path


def _mosaic_level(
    con: sqlite3.Connection,
    qtable: str,
    lv: _Level,
    path: Path,
    crs: CRS,
    col_off: int,
    row_off: int,
    width: int,
    height: int,
    x0: float,
    y1: float,
    bands: str,
    n_bands: int,
) -> None:
    """Write the tiles of one zoom level that fall inside the window to a GeoTIFF."""
    tw, th = lv.tile_width, lv.tile_height
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": n_bands,
        "dtype": "uint8",
        "crs": crs,
        "transform": from_origin(x0, y1, lv.px, lv.py),
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "compress": "DEFLATE",
        "sparse_ok": True,  # leave missing tiles unwritten
        "bigtiff": "IF_SAFER",
    }
    if bands == "RGBA":
        profile["photometric"] = "RGB"
        profile["alpha"] = "UNASSOCIATED"

    first_col, last_col = col_off // tw, (col_off + width - 1) // tw
    first_row, last_row = row_off // th, (row_off + height - 1) // th

    with rasterio.open(path, "w", **profile) as dst:
        rows = con.execute(
            f"SELECT tile_column, tile_row, tile_data FROM {qtable} "
            "WHERE zoom_level = ? AND tile_column BETWEEN ? AND ? "
            "AND tile_row BETWEEN ? AND ?",
            (lv.zoom, first_col, last_col, first_row, last_row),
        )
        for col, row, blob in rows:
            with Image.open(io.BytesIO(blob)) as img:
                if img.size != (tw, th):
                    raise ValueError(
                        f"Tile z={lv.zoom} col={col} row={row} is {img.size}, "
                        f"expected {(tw, th)}"
                    )
                pixels = np.asarray(img.convert(bands))

            # Tile position relative to the output window, then clip to it.
            tx, ty = col * tw - col_off, row * th - row_off
            dx0, dy0 = max(tx, 0), max(ty, 0)
            dx1, dy1 = min(tx + tw, width), min(ty + th, height)
            if dx0 >= dx1 or dy0 >= dy1:
                continue
            block = pixels[dy0 - ty : dy1 - ty, dx0 - tx : dx1 - tx]
            dst.write(
                np.moveaxis(block, -1, 0),
                window=Window(dx0, dy0, dx1 - dx0, dy1 - dy0),
            )


def _pyramid_vrt(
    level_files: list[tuple[Path, int, int]],
    crs: CRS,
    geotransform: tuple[float, ...],
    n_bands: int,
) -> str:
    """VRT whose bands read the first file and expose the rest as overviews."""
    (base_path, width, height), overviews = level_files[0], level_files[1:]
    gt = ", ".join(repr(v) for v in geotransform)
    parts = [
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">',
        f"  <SRS>{escape(crs.to_wkt())}</SRS>",
        f"  <GeoTransform>{gt}</GeoTransform>",
    ]
    for b in range(1, n_bands + 1):
        parts += [
            f'  <VRTRasterBand dataType="Byte" band="{b}">',
            f"    <ColorInterp>{COLOR_INTERP[b - 1]}</ColorInterp>",
            "    <SimpleSource>",
            f'      <SourceFilename relativeToVRT="0">{escape(str(base_path))}</SourceFilename>',
            f"      <SourceBand>{b}</SourceBand>",
            "    </SimpleSource>",
        ]
        for ov_path, _, _ in overviews:
            parts += [
                "    <Overview>",
                f'      <SourceFilename relativeToVRT="0">{escape(str(ov_path))}</SourceFilename>',
                f"      <SourceBand>{b}</SourceBand>",
                "    </Overview>",
            ]
        parts.append("  </VRTRasterBand>")
    parts.append("</VRTDataset>")
    return "\n".join(parts)
    