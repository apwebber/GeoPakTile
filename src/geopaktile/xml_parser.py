"""Parse OGC WMTS GetCapabilities XML into TileMatrix / TileMatrixSet models."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import pyproj
from morecantile.models import CRS, TileMatrix, TileMatrixSet, TMSBoundingBox
from morecantile.utils import meters_per_unit

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


def _parse_crs(crs_text: str) -> str:
    """Parse a SupportedCRS string into a CRS string pyproj/morecantile accept.

    Returns "OGC:CRS84" for CRS84 and "EPSG:<code>" otherwise.
    """
    crs_text = crs_text.strip()
    if _CRS84_RE.search(crs_text):
        return "OGC:CRS84"

    match = _EPSG_RE.search(crs_text)
    if not match:
        raise ValueError(f"Could not parse EPSG code from SupportedCRS: {crs_text!r}")
    return f"EPSG:{int(match.group(1))}"


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


def _parse_tile_matrix(elem: ET.Element, fallback_zoom: int, meters_per_crs_unit: float) -> TileMatrix:
    """Parse a single <TileMatrix> element.

    The WMTS spec doesn't require ows:Identifier to be an integer zoom
    level, just a unique label. morecantile requires an integer id, so we
    try the identifier first and fall back to the element's position in the
    (already document-ordered) TileMatrixSet.

    pointOfOrigin is kept in the order written in the capabilities (the
    CRS axis order); TileMatrixSet handles any lat/lon inversion itself.
    """
    raw_id = _text(elem, "ows:Identifier")
    try:
        zoom_level = int(raw_id)
    except ValueError:
        zoom_level = fallback_zoom

    first, second = _text_any_ns(elem, "TopLeftCorner").split()
    scale_denominator = float(_text_any_ns(elem, "ScaleDenominator"))

    return TileMatrix(
        id=str(zoom_level),
        scaleDenominator=scale_denominator,
        cellSize=scale_denominator * 0.28e-3 / meters_per_crs_unit,
        cornerOfOrigin="topLeft",
        pointOfOrigin=(float(first), float(second)),
        tileWidth=int(_text_any_ns(elem, "TileWidth")),
        tileHeight=int(_text_any_ns(elem, "TileHeight")),
        matrixWidth=int(_text_any_ns(elem, "MatrixWidth")),
        matrixHeight=int(_text_any_ns(elem, "MatrixHeight")),
    )


def _parse_bounding_box(elem: ET.Element) -> TMSBoundingBox | None:
    """Parse an optional ows:BoundingBox (coordinates in CRS axis order)."""
    bbox = elem.find("ows:BoundingBox", NS)
    if bbox is None:
        return None
    lower = tuple(float(v) for v in _text(bbox, "ows:LowerCorner").split())
    upper = tuple(float(v) for v in _text(bbox, "ows:UpperCorner").split())
    return TMSBoundingBox(lowerLeft=lower, upperRight=upper)  # type: ignore morecantile uses NumType = int | float


def parse_tile_matrix_set(elem: ET.Element, swap_xy: bool | None = None) -> TileMatrixSet:
    """Parse a single <TileMatrixSet> element (found under <Contents>).

    Parameters
    ----------
    swap_xy : bool | None
        Whether TopLeftCorner/BoundingBox coordinates are written as
        (lat, lon) instead of (lon, lat) / (x, y). If None (default),
        morecantile infers this from the CRS's axis order (e.g. True for
        EPSG:4326, False for CRS84). WMTS servers are inconsistent about
        this in practice, so if your parsed bounds look implausible, try
        passing the opposite explicitly; this sets the TileMatrixSet's
        orderedAxes.
    """
    identifier = _text(elem, "ows:Identifier")
    crs_str = _parse_crs(_text(elem, "ows:SupportedCRS"))
    mpu = meters_per_unit(pyproj.CRS.from_user_input(crs_str))

    tile_matrix_elems = elem.findall("wmts:TileMatrix", NS) or elem.findall("TileMatrix")
    if not tile_matrix_elems:
        raise ValueError(f"TileMatrixSet {identifier!r} has no TileMatrix levels")

    tile_matrices = [
        _parse_tile_matrix(tm_elem, fallback_zoom=i, meters_per_crs_unit=mpu)
        for i, tm_elem in enumerate(tile_matrix_elems)
    ]
    tile_matrices.sort(key=lambda tm: int(tm.id))

    ordered_axes = None if swap_xy is None else (["Y", "X"] if swap_xy else ["X", "Y"])

    return TileMatrixSet(
        # morecantile restricts ids to [\w\d_-]; keep the original as title.
        id=re.sub(r"[^\w\-]", "_", identifier),
        title=identifier,
        crs=CRS(crs_str),
        orderedAxes=ordered_axes,
        boundingBox=_parse_bounding_box(elem),
        tileMatrices=tile_matrices,
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
        if identifier in (tms.id, tms.title):
            return tms
    available = [tms.title or tms.id for tms in all_sets]
    raise KeyError(f"No TileMatrixSet {identifier!r} found. Available: {available}")