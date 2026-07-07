from __future__ import annotations

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

OGC_PIXEL_SIZE_M = 0.00028


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


class TileMatrixSet(BaseModel):
    """
    A full tile pyramid for one CRS, e.g. the OS Maps API EPSG:27700 set.
    """

    identifier: str = Field(..., description="e.g. 'EPSG:27700'")
    epsg: int
    tile_matrices: list[TileMatrix] = Field(..., min_length=1)

    @field_validator("tile_matrices")
    @classmethod
    def _sorted_by_zoom(cls, v: list[TileMatrix]) -> list[TileMatrix]:
        return sorted(v, key=lambda tm: tm.zoom_level)

    @model_validator(mode="after")
    def _check_consistent_top_left(self) -> "TileMatrixSet":
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
    def _check_zoom_levels_contiguous(self) -> "TileMatrixSet":
        levels = [tm.zoom_level for tm in self.tile_matrices]
        expected = list(range(levels[0], levels[0] + len(levels)))
        if levels != expected:
            raise ValueError(
                f"zoom_level values must be contiguous starting from a base "
                f"level, got {levels}"
            )
        return self

    def get_level(self, zoom_level: int) -> TileMatrix:
        for tm in self.tile_matrices:
            if tm.zoom_level == zoom_level:
                return tm
        raise KeyError(f"No TileMatrix for zoom_level={zoom_level}")

    @property
    def overall_bounds(self) -> tuple[float, float, float, float]:
        """
        Bounding box of the coarsest (lowest zoom) level, which is the
        widest extent in a standard pyramid — suitable for
        gpkg_tile_matrix_set / gpkg_contents.
        """
        return self.tile_matrices[0].bounds
