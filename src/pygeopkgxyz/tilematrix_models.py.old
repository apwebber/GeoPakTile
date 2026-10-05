from __future__ import annotations

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

OGC_PIXEL_SIZE_M = 0.00028

WEB_MERCATOR_EXTENT = 20037508.342789244  # half-width of the world in meters
WEB_MERCATOR_TILE_SIZE = 256


class TileMatrix(BaseModel):
    """
    A single zoom level of a WMTS/GeoPackage tile matrix set.

    Mirrors the fields of an OGC WMTS <TileMatrix> element. pixel_x_size
    and pixel_y_size are derived from scale_denominator rather than stored,
    so they can never drift out of sync with the source scale.
    """

    identifier: str = Field(..., description="e.g. 'EPSG:27700:0'")
    zoom_level: int = Field(..., ge=0)
    scale_denominator: float = Field(..., gt=0)
    top_left_x: float
    top_left_y: float
    tile_width: int = Field(..., gt=0)
    tile_height: int = Field(..., gt=0)
    matrix_width: int = Field(..., gt=0)
    matrix_height: int = Field(..., gt=0)

    @computed_field  # type: ignore[misc]
    @property
    def pixel_x_size(self) -> float:
        return self.scale_denominator * OGC_PIXEL_SIZE_M

    @computed_field  # type: ignore[misc]
    @property
    def pixel_y_size(self) -> float:
        return self.scale_denominator * OGC_PIXEL_SIZE_M

    @computed_field  # type: ignore[misc]
    @property
    def extent_width(self) -> float:
        return self.matrix_width * self.tile_width * self.pixel_x_size

    @computed_field  # type: ignore[misc]
    @property
    def extent_height(self) -> float:
        return self.matrix_height * self.tile_height * self.pixel_y_size

    @computed_field  # type: ignore[misc]
    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) implied by this matrix level."""
        min_x = self.top_left_x
        max_y = self.top_left_y
        max_x = min_x + self.extent_width
        min_y = max_y - self.extent_height
        return (min_x, min_y, max_x, max_y)
    
    def tile_bounds(self, x: int, y: int) -> tuple[float, float, float, float]:
        """
        Return the bounding box of the tile at (x, y).

        Parameters
        ----------
        x : int
            Tile column (0 <= x < matrix_width).
        y : int
            Tile row (0 <= y < matrix_height).

        Returns
        -------
        tuple[float, float, float, float]
            (min_x, min_y, max_x, max_y)
        """
        if not (0 <= x < self.matrix_width):
            raise ValueError(f"x={x} outside tile matrix")

        if not (0 <= y < self.matrix_height):
            raise ValueError(f"y={y} outside tile matrix")

        tile_width_map = self.tile_width * self.pixel_x_size
        tile_height_map = self.tile_height * self.pixel_y_size

        min_x = self.top_left_x + x * tile_width_map
        max_x = min_x + tile_width_map

        max_y = self.top_left_y - y * tile_height_map
        min_y = max_y - tile_height_map

        return (min_x, min_y, max_x, max_y)


class TileMatrixSet(BaseModel):
    """
    A full tile pyramid for one CRS, e.g. the OS Maps API EPSG:27700 set.
    """

    identifier: str = Field(..., description="e.g. 'EPSG:27700'")
    epsg: int
    bbox_min_x: float
    bbox_max_x: float
    bbox_min_y: float
    bbox_max_y: float
    tile_matrices: list[TileMatrix] = Field(..., min_length=1)

    @field_validator("tile_matrices")
    @classmethod
    def _sorted_by_zoom(cls, v: list[TileMatrix]) -> list[TileMatrix]:
        return sorted(v, key=lambda tm: tm.zoom_level)

    @model_validator(mode="after")
    def _check_consistent_top_left(self) -> TileMatrixSet:
        """
        All levels in a pyramid should share the same origin. This doesn't
        hold for every WMTS service, but it does for standard XYZ-style
        pyramids (including OS's 27700 tile sets) and it's worth failing
        loudly if it's ever violated, since callers may assume it.
        """
        origins = {(tm.top_left_x, tm.top_left_y) for tm in self.tile_matrices}
        if len(origins) > 1:
            raise ValueError(
                f"TileMatrix levels have inconsistent TopLeftCorner values: "
                f"{origins}. Each level should share the same origin."
            )
        return self

    @model_validator(mode="after")
    def _check_zoom_levels_contiguous(self) -> TileMatrixSet:
        levels = [tm.zoom_level for tm in self.tile_matrices]
        expected = list(range(levels[0], levels[0] + len(levels)))
        if levels != expected:
            raise ValueError(
                f"zoom_level values must be contiguous starting from a base "
                f"level, got {levels}"
            )
        return self
    
    @model_validator(mode="after")
    def _check_bbox_ordering(self) -> TileMatrixSet:
        if self.bbox_min_x >= self.bbox_max_x or self.bbox_min_y >= self.bbox_max_y:
            raise ValueError(
                f"bbox is inverted or zero-area: "
                f"x=[{self.bbox_min_x}, {self.bbox_max_x}], "
                f"y=[{self.bbox_min_y}, {self.bbox_max_y}]"
            )
        return self

    def get_level(self, zoom_level: int) -> TileMatrix:
        for tm in self.tile_matrices:
            if tm.zoom_level == zoom_level:
                return tm
        raise KeyError(f"No TileMatrix for zoom_level={zoom_level}")
    
    def tile_bounds(self, z: int, x: int, y: int):
        """Wraps the TileMatrix tile_bounds method"""
        tm = self.get_level(z)
        return tm.tile_bounds(x, y)

    @property
    def overall_bounds(self) -> tuple[float, float, float, float]:
        """
        Bounding box of the coarsest (lowest zoom) level, which is the
        widest extent in a standard pyramid — suitable for
        gpkg_tile_matrix_set / gpkg_contents.
        """
        return self.tile_matrices[0].bounds
    




def create_web_mercator_tms(
    min_zoom: int = 0,
    max_zoom: int = 19,
    tile_size: int = WEB_MERCATOR_TILE_SIZE,
) -> TileMatrixSet:
    """
    Build the standard XYZ / Web Mercator (EPSG:3857) TileMatrixSet.

    This is the doubling pyramid used by OSM, Google/Bing Maps, MapLibre,
    Leaflet, etc: one root tile at zoom 0 covering the whole world square,
    each level doubling matrix_width/matrix_height.
    """
    if min_zoom < 0 or max_zoom < min_zoom:
        raise ValueError(f"Invalid zoom range: min_zoom={min_zoom}, max_zoom={max_zoom}")

    top_left_x = -WEB_MERCATOR_EXTENT
    top_left_y = WEB_MERCATOR_EXTENT

    # Pixel size at zoom 0: one tile (tile_size px) covers the full
    # world width (2 * WEB_MERCATOR_EXTENT meters).
    pixel_size_z0 = (2 * WEB_MERCATOR_EXTENT) / tile_size

    tile_matrices = []
    for z in range(min_zoom, max_zoom + 1):
        matrix_size = 2 ** z
        pixel_size = pixel_size_z0 / matrix_size
        scale_denominator = pixel_size / OGC_PIXEL_SIZE_M

        tile_matrices.append(
            TileMatrix(
                identifier=f"EPSG:3857:{z}",
                zoom_level=z,
                scale_denominator=scale_denominator,
                top_left_x=top_left_x,
                top_left_y=top_left_y,
                tile_width=tile_size,
                tile_height=tile_size,
                matrix_width=matrix_size,
                matrix_height=matrix_size,
            )
        )

    return TileMatrixSet(
        identifier="EPSG:3857",
        epsg=3857,
        bbox_min_x=-WEB_MERCATOR_EXTENT,
        bbox_max_x=WEB_MERCATOR_EXTENT,
        bbox_min_y=-WEB_MERCATOR_EXTENT,
        bbox_max_y=WEB_MERCATOR_EXTENT,
        tile_matrices=tile_matrices,
    )
