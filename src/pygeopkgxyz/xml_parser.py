"""Parse OGC WMTS GetCapabilities XML into TileMatrix / TileMatrixSet models."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from pygeopkgxyz.tilematrix_models import TileMatrix, TileMatrixSet

NS = {
    "wmts": "http://www.opengis.net/wmts/1.0",
    "ows": "http://www.opengis.net/ows/1.1",
}

# Matches the EPSG code out of any of the common ways a CRS URN/URI is
# written in WMTS capabilities, e.g.:
#   "urn:ogc:def:crs:EPSG::27700"
#   "urn:ogc:def:crs:EPSG:6.3:27700"
#   "urn:ogc:def:crs:EPSG:6.18:3:3857"   (multiple version/codespace segments)
#   "EPSG:27700"
#   "http://www.opengis.net/def/crs/EPSG/0/27700"
# The middle segment is repeated (*, not ?) since some URN authorities
# chain more than one version/codespace token before the actual code.
_EPSG_RE = re.compile(r"EPSG[:/]+(?:[\w.]+[:/]+)*(\d+)\s*$", re.IGNORECASE)

# CRS84 ("urn:ogc:def:crs:OGC:1.3:CRS84") is WGS84 with (lon, lat) axis
# order
_CRS84_RE = re.compile(r"\bCRS84\b", re.IGNORECASE)

# CRS whose official EPSG axis order is (lat, lon) / (northing, easting)
# rather than (x, y).
_LAT_LON_ORDER_EPSG = {4326}


def _parse_crs(crs_text: str) -> tuple[int, bool]:
    """Parse a SupportedCRS string into (epsg_code, default_swap_xy).

    default_swap_xy is our best guess, based purely on the CRS identifier,
    of whether coordinates in this TileMatrixSet are written (lat, lon)
    rather than (lon, lat)/(x, y).
    """
    crs_text = crs_text.strip()
    if _CRS84_RE.search(crs_text):
        return 4326, False

    match = _EPSG_RE.search(crs_text)
    if not match:
        raise ValueError(f"Could not parse EPSG code from SupportedCRS: {crs_text!r}")
    epsg = int(match.group(1))
    return epsg, epsg in _LAT_LON_ORDER_EPSG


def _text(elem: ET.Element, path: str, ns: dict[str, str] = NS) -> str:
    found = elem.find(path, ns)
    if found is None or found.text is None:
        raise ValueError(f"Missing required element {path!r} in {elem.tag}")
    return found.text.strip()


def _text_any_ns(elem: ET.Element, local_name: str) -> str:
    """Look up a WMTS-namespaced child, tolerating servers that omit the
    default xmlns declaration and emit bare (no-namespace) element names."""
    found = elem.find(f"wmts:{local_name}", NS)
    if found is None:
        found = elem.find(local_name)
    if found is None or found.text is None:
        raise ValueError(f"Missing required element {local_name!r} in {elem.tag}")
    return found.text.strip()


def _parse_tile_matrix(
    elem: ET.Element, tms_identifier: str, fallback_zoom: int, swap_xy: bool
) -> TileMatrix:
    """Parse a single <TileMatrix> element.

    The WMTS spec doesn't require ows:Identifier to be an integer zoom
    level, just a unique label. Most XYZ-style pyramids do use "0", "1",
    "2", ... in document order, so we try that first and fall back to the
    element's position in the (already document-ordered) TileMatrixSet.
    """
    raw_id = _text(elem, "ows:Identifier")
    try:
        zoom_level = int(raw_id)
    except ValueError:
        zoom_level = fallback_zoom

    first, second = _text_any_ns(elem, "TopLeftCorner").split()
    top_left_x, top_left_y = (float(second), float(first)) if swap_xy else (float(first), float(second))

    return TileMatrix(
        identifier=f"{tms_identifier}:{raw_id}",
        zoom_level=zoom_level,
        scale_denominator=float(_text_any_ns(elem, "ScaleDenominator")),
        top_left_x=top_left_x,
        top_left_y=top_left_y,
        tile_width=int(_text_any_ns(elem, "TileWidth")),
        tile_height=int(_text_any_ns(elem, "TileHeight")),
        matrix_width=int(_text_any_ns(elem, "MatrixWidth")),
        matrix_height=int(_text_any_ns(elem, "MatrixHeight")),
    )


def _parse_bounding_box(elem: ET.Element, swap_xy: bool) -> tuple[float, float, float, float] | None:
    """Parse an optional ows:BoundingBox into (min_x, min_y, max_x, max_y)."""
    bbox = elem.find("ows:BoundingBox", NS)
    if bbox is None:
        return None
    lc_first, lc_second = _text(bbox, "ows:LowerCorner").split()
    uc_first, uc_second = _text(bbox, "ows:UpperCorner").split()
    if swap_xy:
        min_x, min_y = float(lc_second), float(lc_first)
        max_x, max_y = float(uc_second), float(uc_first)
    else:
        min_x, min_y = float(lc_first), float(lc_second)
        max_x, max_y = float(uc_first), float(uc_second)
    return min_x, min_y, max_x, max_y


# CRS whose official EPSG axis order is (lat, lon) / (northing, easting)
# rather than (x, y). WMTS servers commonly follow the official order for
# these, so TopLeftCorner/BoundingBox corners come as (lat, lon) pairs.
# This list covers the common case (geographic CRS); it is not exhaustive
# -- pass swap_xy explicitly to parse_tile_matrix_set/parse_capabilities
# if you hit a CRS not covered here, or if a particular server doesn't
# follow the official order despite using this CRS.
_LAT_LON_ORDER_EPSG = {4326}


def parse_tile_matrix_set(elem: ET.Element, swap_xy: bool | None = None) -> TileMatrixSet:
    """Parse a single <TileMatrixSet> element (found under <Contents>).

    Parameters
    ----------
    swap_xy : bool | None
        Whether TopLeftCorner/BoundingBox coordinates are written as
        (lat, lon) instead of (lon, lat) / (x, y). If None (default),
        this is guessed from the CRS (True for URN-form EPSG:4326, False
        for CRS84). WMTS servers are inconsistent about this in practice,
        so if your parsed bounds look implausible (e.g. inverted or
        wildly out of range), try passing the opposite explicitly.
    """
    identifier = _text(elem, "ows:Identifier")
    epsg, default_swap_xy = _parse_crs(_text(elem, "ows:SupportedCRS"))

    if swap_xy is None:
        swap_xy = default_swap_xy

    tile_matrix_elems = elem.findall("wmts:TileMatrix", NS) or elem.findall("TileMatrix")
    if not tile_matrix_elems:
        raise ValueError(f"TileMatrixSet {identifier!r} has no TileMatrix levels")

    tile_matrices = [
        _parse_tile_matrix(tm_elem, identifier, fallback_zoom=i, swap_xy=swap_xy)
        for i, tm_elem in enumerate(tile_matrix_elems)
    ]

    bbox = _parse_bounding_box(elem, swap_xy=swap_xy)
    if bbox is None:
        # Not every service includes ows:BoundingBox on the TileMatrixSet
        # itself. Fall back to the coarsest level's implied bounds, which
        # is the same convention TileMatrixSet.overall_bounds uses.
        levels_by_zoom = sorted(tile_matrices, key=lambda tm: tm.zoom_level)
        bbox = levels_by_zoom[0].bounds

    min_x, min_y, max_x, max_y = bbox

    return TileMatrixSet(
        identifier=identifier,
        epsg=epsg,
        bbox_min_x=min_x,
        bbox_max_x=max_x,
        bbox_min_y=min_y,
        bbox_max_y=max_y,
        tile_matrices=tile_matrices,
    )


def parse_capabilities(xml_source: str | bytes, swap_xy: bool | None = None) -> list[TileMatrixSet]:
    """Parse a full WMTS GetCapabilities document into its TileMatrixSets.

    Parameters
    ----------
    xml_source : str | bytes
        The raw GetCapabilities XML, as returned by the WMTS endpoint.
    swap_xy : bool | None
        See parse_tile_matrix_set. Applied to every TileMatrixSet found;
        pass None (default) to auto-detect per-set based on CRS.

    Returns
    -------
    list[TileMatrixSet]
        One entry per <TileMatrixSet> found under <Contents>. A capabilities
        document commonly advertises several (e.g. one per CRS, or several
        resolutions of the same CRS) even if you only care about one.
    """
    root = ET.fromstring(xml_source)
    contents = root.find("wmts:Contents", NS)
    if contents is None:
        raise ValueError("GetCapabilities document has no <Contents> element")

    tms_elems = contents.findall("wmts:TileMatrixSet", NS)
    return [parse_tile_matrix_set(elem, swap_xy=swap_xy) for elem in tms_elems]


def get_tile_matrix_set(
    xml_source: str | bytes, identifier: str, swap_xy: bool | None = None
) -> TileMatrixSet:
    """Convenience wrapper: parse and return one named TileMatrixSet.

    Raises KeyError if no TileMatrixSet with that identifier is present,
    listing what was actually found so mismatches (e.g. guessing "2km"
    when the service calls it "2km_epsg4326") are easy to debug.
    """
    all_sets = parse_capabilities(xml_source, swap_xy=swap_xy)
    for tms in all_sets:
        if tms.identifier == identifier:
            return tms
    available = [tms.identifier for tms in all_sets]
    raise KeyError(f"No TileMatrixSet {identifier!r} found. Available: {available}")