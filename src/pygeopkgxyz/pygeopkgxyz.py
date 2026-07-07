import re
import sqlite3
from pathlib import Path
from typing import Iterable, Optional
from pyproj import CRS

from pygeopkgxyz.tilematrix_models import TileMatrixSet

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_table_name(table_name: str) -> None:
    """Ensure table_name is safe to interpolate into SQL and spec-compliant."""
    if not _IDENTIFIER_RE.match(table_name):
        raise ValueError(
            f"Invalid table_name {table_name!r}: must match "
            f"[A-Za-z_][A-Za-z0-9_]* (letters, digits, underscore only, "
            f"not starting with a digit)."
        )
    if table_name.lower().startswith("gpkg_"):
        raise ValueError(
            f"Invalid table_name {table_name!r}: the 'gpkg_' prefix is "
            f"reserved by the GeoPackage spec."
        )


def create_tile_geopackage(
    gpkg_path: str | Path,
    table_name: str = "tiles",
    epsg: int = 3857,
    min_x: float = -20037508.342789244,
    min_y: float = -20037508.342789244,
    max_x: float = 20037508.342789244,
    max_y: float = 20037508.342789244,
    overwrite: bool = False,
) -> None:
    """
    Create a GeoPackage tile pyramid table.

    Defaults are for standard Web Mercator XYZ tiles, EPSG:3857.
    """

    _validate_table_name(table_name)

    gpkg_path = Path(gpkg_path)

    if overwrite and gpkg_path.exists():
        gpkg_path.unlink()

    conn = sqlite3.connect(gpkg_path)

    try:
        cur = conn.cursor()

        cur.execute("PRAGMA application_id = 1196437808")
        cur.execute("PRAGMA user_version = 10400")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
                srs_name TEXT NOT NULL,
                srs_id INTEGER NOT NULL PRIMARY KEY,
                organization TEXT NOT NULL,
                organization_coordsys_id INTEGER NOT NULL,
                definition TEXT NOT NULL,
                description TEXT
            )
            """
        )

        cur.execute(
            """
            INSERT OR IGNORE INTO gpkg_spatial_ref_sys
            VALUES
            (
                'Undefined Cartesian SRS',
                -1,
                'NONE',
                -1,
                'undefined',
                'undefined Cartesian coordinate reference system'
            )
            """
        )

        cur.execute(
            """
            INSERT OR IGNORE INTO gpkg_spatial_ref_sys
            VALUES
            (
                'Undefined Geographic SRS',
                0,
                'NONE',
                0,
                'undefined',
                'undefined geographic coordinate reference system'
            )
            """
        )

        crs = CRS.from_epsg(epsg)
        srs_name = crs.name
        definition = crs.to_wkt()

        cur.execute(
            """
            INSERT OR IGNORE INTO gpkg_spatial_ref_sys
            (
                srs_name,
                srs_id,
                organization,
                organization_coordsys_id,
                definition,
                description
            )
            VALUES (?, ?, 'EPSG', ?, ?, ?)
            """,
            (
                srs_name,
                epsg,
                epsg,
                definition,
                srs_name,
            ),
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gpkg_contents (
                table_name TEXT NOT NULL PRIMARY KEY,
                data_type TEXT NOT NULL,
                identifier TEXT UNIQUE,
                description TEXT DEFAULT '',
                last_change DATETIME NOT NULL DEFAULT
                    (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                min_x DOUBLE,
                min_y DOUBLE,
                max_x DOUBLE,
                max_y DOUBLE,
                srs_id INTEGER,
                CONSTRAINT fk_gc_r_srs_id
                    FOREIGN KEY (srs_id)
                    REFERENCES gpkg_spatial_ref_sys(srs_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gpkg_tile_matrix_set (
                table_name TEXT NOT NULL PRIMARY KEY,
                srs_id INTEGER NOT NULL,
                min_x DOUBLE NOT NULL,
                min_y DOUBLE NOT NULL,
                max_x DOUBLE NOT NULL,
                max_y DOUBLE NOT NULL,
                CONSTRAINT fk_gtms_table_name
                    FOREIGN KEY (table_name)
                    REFERENCES gpkg_contents(table_name),
                CONSTRAINT fk_gtms_srs
                    FOREIGN KEY (srs_id)
                    REFERENCES gpkg_spatial_ref_sys(srs_id)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS gpkg_tile_matrix (
                table_name TEXT NOT NULL,
                zoom_level INTEGER NOT NULL,
                matrix_width INTEGER NOT NULL,
                matrix_height INTEGER NOT NULL,
                tile_width INTEGER NOT NULL,
                tile_height INTEGER NOT NULL,
                pixel_x_size DOUBLE NOT NULL,
                pixel_y_size DOUBLE NOT NULL,
                CONSTRAINT pk_ttm PRIMARY KEY (table_name, zoom_level),
                CONSTRAINT fk_tmm_table_name
                    FOREIGN KEY (table_name)
                    REFERENCES gpkg_contents(table_name)
            )
            """
        )

        # table_name has been validated by _validate_table_name(), so it is
        # safe to interpolate here (parameter binding doesn't work for
        # identifiers).
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{table_name}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zoom_level INTEGER NOT NULL,
                tile_column INTEGER NOT NULL,
                tile_row INTEGER NOT NULL,
                tile_data BLOB NOT NULL,
                UNIQUE (zoom_level, tile_column, tile_row)
            )
            """
        )

        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS "{table_name}_zxy_idx"
            ON "{table_name}" (zoom_level, tile_column, tile_row)
            """
        )

        cur.execute(
            """
            INSERT OR REPLACE INTO gpkg_contents
            (
                table_name,
                data_type,
                identifier,
                description,
                min_x,
                min_y,
                max_x,
                max_y,
                srs_id
            )
            VALUES (?, 'tiles', ?, '', ?, ?, ?, ?, ?)
            """,
            (
                table_name,
                table_name,
                min_x,
                min_y,
                max_x,
                max_y,
                epsg,
            ),
        )

        cur.execute(
            """
            INSERT OR REPLACE INTO gpkg_tile_matrix_set
            (
                table_name,
                srs_id,
                min_x,
                min_y,
                max_x,
                max_y
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                table_name,
                epsg,
                min_x,
                min_y,
                max_x,
                max_y,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def ensure_zoom_level(
    conn: sqlite3.Connection,
    table_name: str,
    z: int,
    tile_size: int = 256,
    extent_width: float = 40075016.68557849,
    extent_height: float = 40075016.68557849,
    tms: Optional[TileMatrixSet] = None,
) -> None:
    """
    Add one gpkg_tile_matrix row for a zoom level.

    For standard XYZ/Web Mercator:
    matrix_width = matrix_height = 2 ** z
    """

    if tms is not None:
        tm = tms.get_level(z)
        conn.execute(
            """
            INSERT OR IGNORE INTO gpkg_tile_matrix
            (
                table_name,
                zoom_level,
                matrix_width,
                matrix_height,
                tile_width,
                tile_height,
                pixel_x_size,
                pixel_y_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                table_name,
                z,
                tm.matrix_width,
                tm.matrix_height,
                tm.tile_width,
                tm.tile_height,
                tm.pixel_x_size,
                tm.pixel_y_size,
            ),
        )
    else:
        # Fall back on standard levels
        matrix_width = 2**z
        matrix_height = 2**z

        pixel_x_size = extent_width / matrix_width / tile_size
        pixel_y_size = extent_height / matrix_height / tile_size

        conn.execute(
            """
            INSERT OR IGNORE INTO gpkg_tile_matrix
            (
                table_name,
                zoom_level,
                matrix_width,
                matrix_height,
                tile_width,
                tile_height,
                pixel_x_size,
                pixel_y_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                table_name,
                z,
                matrix_width,
                matrix_height,
                tile_size,
                tile_size,
                pixel_x_size,
                pixel_y_size,
            ),
        )


def add_xyz_tiles_to_geopackage(
    gpkg_path: str | Path,
    tiles: Iterable[tuple[int, int, int, bytes]],
    table_name: str = "tiles",
    batch_size: int = 1000,
    tile_size: int = 256,
    replace: bool = True,
    tms: Optional[TileMatrixSet] = None,
) -> None:
    """
    Add XYZ tiles to an existing GeoPackage tile table.

    Parameters
    ----------
    gpkg_path:
        Path to the GeoPackage.

    tiles:
        Iterable of:

            (z, x, y, tile_bytes)

    table_name:
        Tile table name.

    batch_size:
        Number of tiles inserted per transaction.

    tile_size:
        Tile pixel size, usually 256.

    replace:
        If True, overwrite existing z/x/y tiles.
        If False, ignore duplicates.
    """

    gpkg_path = Path(gpkg_path)

    if replace:
        insert_sql = f"""
            INSERT OR REPLACE INTO "{table_name}"
            (
                zoom_level,
                tile_column,
                tile_row,
                tile_data
            )
            VALUES (?, ?, ?, ?)
        """
    else:
        insert_sql = f"""
            INSERT OR IGNORE INTO "{table_name}"
            (
                zoom_level,
                tile_column,
                tile_row,
                tile_data
            )
            VALUES (?, ?, ?, ?)
        """

    conn = sqlite3.connect(gpkg_path)

    try:
        batch = []
        for z, x, y, tile_bytes in tiles:
            z = int(z)
            x = int(x)
            y = int(y)

            ensure_zoom_level(
                conn=conn, table_name=table_name, z=z, tile_size=tile_size, tms=tms
            )

            batch.append((z, x, y, sqlite3.Binary(tile_bytes)))

            if len(batch) >= batch_size:
                conn.executemany(insert_sql, batch)
                conn.commit()
                batch.clear()

        if batch:
            conn.executemany(insert_sql, batch)
            conn.commit()

    finally:
        conn.close()


def create_and_add_xyz_tiles_geopackage(
    gpkg_path: str | Path,
    tiles: Iterable[tuple[int, int, int, bytes]],
    table_name: str = "tiles",
    epsg: int = 3857,
    batch_size: int = 1000,
    tile_size: int = 256,
    overwrite: bool = False,
) -> None:
    """
    Convenience wrapper: create GeoPackage, then add tiles.
    """

    create_tile_geopackage(
        gpkg_path=gpkg_path,
        table_name=table_name,
        epsg=epsg,
        overwrite=overwrite,
    )

    add_xyz_tiles_to_geopackage(
        gpkg_path=gpkg_path,
        tiles=tiles,
        table_name=table_name,
        batch_size=batch_size,
        tile_size=tile_size,
    )
