import re
import sqlite3
import numpy as np
from pathlib import Path
from typing import Iterable, Literal
from pyproj import CRS

from pygeopkgxyz.tilematrix_models import TileMatrixSet

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GPKGXYZ:
    def __init__(
        self,
        filepath,
        tms: TileMatrixSet,
        table_name: str = "tiles",
        mode: Literal["ro", "rw", "rwc"] = "ro",
    ):
        """Create and or write tiles to a geopackage XYZ tile layer.

        A tile matrix set is required in order to get the correct co-ordinates for the tiles and data extents.
        3857 Web mercator tms set can be generated with the external function create_web_mercator_tms()

        Args:
            filepath (_type_): where the geopackage is or should be created
            tms (TileMatrixSet): Describes the tile coordinates and data extent
            table_name (str, optional): The name of the tile table/layer. Defaults to "tiles".
            mode (Literal[ro, rw, rwc], optional): Sqlite3 connection modes. ro = read only, rw is
                read-write, rwc is read, write or create. Defaults to 'ro' for safety.
        """

        self.filepath = Path(filepath)
        self.tms = tms
        self.table_name = table_name

        self._validate_table_name()

        if mode not in ("ro", "rw", "rwc"):
            raise ValueError("Mode must be ro, rw or rwc")

        if mode in ["ro", "rw"] and not self.filepath.exists():
            raise IOError("geopackage not found")

        file_string = f"{self.filepath.absolute().as_uri()}?mode={mode}"
        self._conn = sqlite3.connect(file_string, uri=True)
        self._cursor = self._conn.cursor()

        self._cursor.execute("PRAGMA synchronous=OFF")
        self._cursor.execute("PRAGMA journal_mode=OFF")
        self._cursor.execute("PRAGMA locking_mode=EXCLUSIVE")

        # initialize tables if needed and in create mode
        if mode == "rwc":
            self._create_tables()

    def __enter__(self) -> "GPKGXYZ":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the connection"""
        self._cursor.close()
        self._conn.close()

    def has_tile(self, z: int, x: int, y: int):
        """Check if a tile is present, using the zxy coordinates"""

        self._cursor.execute(
            f"SELECT EXISTS (SELECT 1 FROM {self.table_name} "
            "where zoom_level=? and tile_column=? and tile_row=? LIMIT 1)",
            (z, x, y),
        )

        row = self._cursor.fetchone()
        return row[0] == 1
    

    def has_tiles(self, zxys: list[tuple[int, int, int]] | np.ndarray) -> np.ndarray:
        """Check many tiles efficiently."""

        requested = np.asarray(zxys, dtype=np.uint64)

        self._cursor.execute(
            f"SELECT zoom_level, tile_column, tile_row FROM {self.table_name}"
        )
        rows = self._cursor.fetchall()
        existing = (
            np.array(rows, dtype=np.uint64)
            if rows
            else np.empty((0, 3), dtype=np.uint64)
        )

        # Combine z, x, y into a single array using bit shifting
        # [ 8 bits unused ][ 8 bits z ][ 28 bits x ][ 28 bits y ]
        def pack(arr: np.ndarray) -> np.ndarray:
            z, x, y = arr[:, 0], arr[:, 1], arr[:, 2]
            return (z << np.uint64(56)) | (x << np.uint64(28)) | y

        req_keys = pack(requested)
        exist_keys = pack(existing)

        return np.isin(req_keys, exist_keys, assume_unique=False)

    def add_tiles(
        self,
        tiles: Iterable[tuple[int, int, int, bytes]],
        batch_size: int = 1000,
    ) -> None:
        """Add tiles to the geopackage

        Args:
            tiles (Iterable[tuple[int, int, int, bytes]]): List of tiles - [z, x, y, image data in bytes]
            batch_size (int, optional): Add images in batches for speed. Defaults to 1000.
        """

        insert_sql = f"""
            INSERT OR IGNORE INTO "{self.table_name}"
            (
                zoom_level,
                tile_column,
                tile_row,
                tile_data
            )
            VALUES (?, ?, ?, ?)
        """

        zs = list(set([t[0] for t in tiles]))
        for z in zs:
            self._ensure_zoom_level(z)

        batch = []
        for z, x, y, tile_bytes in tiles:
            z = int(z)
            x = int(x)
            y = int(y)

            if self.has_tile(z, x, y):
                continue

            batch.append((z, x, y, sqlite3.Binary(tile_bytes)))
            if len(batch) >= batch_size:
                self._cursor.executemany(insert_sql, batch)
                self._conn.commit()
                batch.clear()

        if batch:
            self._cursor.executemany(insert_sql, batch)
            self._conn.commit()

    def _create_tables(self):
        """Create the tables for a valid geopackage XYZ layer"""

        self._cursor.execute("PRAGMA application_id = 1196437808")
        self._cursor.execute("PRAGMA user_version = 10400")

        self._cursor.execute(
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

        self._cursor.execute(
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

        self._cursor.execute(
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

        crs = CRS.from_epsg(self.tms.epsg)
        srs_name = crs.name
        definition = crs.to_wkt()

        self._cursor.execute(
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
                self.tms.epsg,
                self.tms.epsg,
                definition,
                srs_name,
            ),
        )

        self._cursor.execute(
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

        self._cursor.execute(
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

        self._cursor.execute(
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

        self._cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS "{self.table_name}" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zoom_level INTEGER NOT NULL,
                tile_column INTEGER NOT NULL,
                tile_row INTEGER NOT NULL,
                tile_data BLOB NOT NULL,
                UNIQUE (zoom_level, tile_column, tile_row)
            )
            """
        )

        self._cursor.execute(
            f"""
            CREATE INDEX IF NOT EXISTS "{self.table_name}_zxy_idx"
            ON "{self.table_name}" (zoom_level, tile_column, tile_row)
            """
        )

        self._cursor.execute(
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
                self.table_name,
                self.table_name,
                self.tms.bbox_min_x,
                self.tms.bbox_min_y,
                self.tms.bbox_max_x,
                self.tms.bbox_max_y,
                self.tms.epsg,
            ),
        )

        min_x, min_y, max_x, max_y = self.tms.overall_bounds

        self._cursor.execute(
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
                self.table_name,
                self.tms.epsg,
                min_x,
                min_y,
                max_x,
                max_y,
            ),
        )

        self._conn.commit()

    def _ensure_zoom_level(
        self,
        z: int,
    ) -> None:
        """
        Add one gpkg_tile_matrix row for a zoom level.
        """

        tm = self.tms.get_level(z)
        self._cursor.execute(
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
                self.table_name,
                z,
                tm.matrix_width,
                tm.matrix_height,
                tm.tile_width,
                tm.tile_height,
                tm.pixel_x_size,
                tm.pixel_y_size,
            ),
        )

    def _validate_table_name(self) -> None:
        """Ensure table_name is safe to interpolate into SQL and spec-compliant."""
        if not _IDENTIFIER_RE.match(self.table_name):
            raise ValueError(
                f"Invalid table_name {self.table_name!r}: must match "
                f"[A-Za-z_][A-Za-z0-9_]* (letters, digits, underscore only, "
                f"not starting with a digit)."
            )
        if self.table_name.lower().startswith("gpkg_"):
            raise ValueError(
                f"Invalid table_name {self.table_name!r}: the 'gpkg_' prefix is "
                f"reserved by the GeoPackage spec."
            )
