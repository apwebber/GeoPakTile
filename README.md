# GeoPakTile

For writing geopackage XYZ raster tile layers, with support for using arbitrary grid systems, and for converting them to Cloud Optimized GeoTIFFs (COGs).

Geopackage XYZ files can use any tile grid system, this is often defined by a server's GetCapabilities response where a TileMatrixSet defines the data co-ordinate system, the extent, the number of rows and columns in each zoom lever, and the corner co-ordinates for each zoom level. This package contains a tool for parsing the GetCapabilities XML into a [morecantile](https://github.com/developmentseed/morecantile) `TileMatrixSet`, and then for writing tiles to a new or existing geopackage.

## Examples

Write tiles to a new geopackage using web mercator (similar to mbtiles), where tiles is a list of (z, x, y, bytes). `tms` is a morecantile `TileMatrixSet` - the standard web mercator can be obtained with `morecantile.tms.get('WebMercatorQuad')`

```python
from geopaktile import GeoPakTile

# Here, a list of tiles are read from a local path, the bytes and co-ordinates are stored as tuples in a list:
# You might get these tiles from a tile server or anywhere else. Adjust accordingly.

tiles = [
    (z, x, y, path.read_bytes()),
    (z2, x2, y2, path2.read_bytes()),
    (z3, x3, y3, path3.read_bytes()),
    ...
]

with GeoPakTile(test_gpkg, tms=morecantile.tms.get('WebMercatorQuad'), mode='rwc') as gpkg:
    gpkg.add_tiles(tiles)
```

Open a geopackage in read only mode and see if it contains certain tiles. A TileMatrixSet isn't required for read-only mode.

```python
from geopaktile import GeoPakTile

with GeoPakTile(test_gpkg, mode='ro') as gpkg:
    assert gpkg.has_tile(z, x, y)
    result = gpkg.has_tiles([(z, x, y), (z1, x1, y1)])
```


Parse a GetCapabilties xml to provide the TileMatrixSet for writing a geopackage:

```python
from geopaktile import parse_capabilities

tms_set = parse_capabilities(xml)
tms = tms_set[0] # you'll need to know which one you want, or use:

tms = get_tile_matrix_set(xml, identifier = '1km') # an identifier that you know is defined in the xml
```


Convert a geopackage tile layer to a Cloud Optimized GeoTIFF. The highest zoom level becomes the full resolution image, and the lower zoom levels become the COG's overviews:

```python
from geopaktile import gpkg_tiles_to_cog

gpkg_tiles_to_cog("tiles.gpkg", "tiles.tif")

# Clip to a bounding box, given here in longitude/latitude
gpkg_tiles_to_cog(
    "tiles.gpkg",
    "clipped.tif",
    bbox=(-0.1, 51.45, 0.05, 51.52),
    bbox_crs="EPSG:4326",
)
```

### TileMatrixSet models

Tile Matrix definitions use the [morecantile](https://github.com/developmentseed/morecantile) package (`morecantile.TileMatrixSet`, `TileMatrix`, etc.) so any morecantile TileMatrixSet (built-in or custom-loaded) can be passed to `GeoPakTile`. The XML parser returns morecantile `TileMatrixSet` objects.

### XML Parser

The xml parser has been tested on NASA GetCapabilties XML and some others, if you come across any that doesn't work then please raise an issue or fix and pull request.

### Converting to COG

`gpkg_tiles_to_cog` copies each zoom level's own pixels into the COG as an overview, rather than letting GDAL resample new overviews from the full resolution image, so every overview keeps the scale of the zoom level it came from. It works with any tile grid where each zoom level halves the pixel size of the one below, such as `WebMercatorQuad` and most grids from GetCapabilities documents.

The output extent defaults to the tiles present at the highest zoom level, or can be set with `bbox` (in the layer's CRS, or in `bbox_crs` if given). The extent is expanded slightly so that it lines up with whole pixels at the zoom levels used as overviews.

A zoom level can only be copied directly if its pixel grid lines up with the output extent. For small extents, the coarsest zoom levels often don't line up, and are left out by default. Pass `resample_unaligned=True` to include them by resampling them onto the extent, down to an overview 1 pixel across. A warning lists any zoom levels that were resampled. The method is set with `resampling` (`"bilinear"` by default; any [rasterio Resampling](https://rasterio.readthedocs.io/en/stable/api/rasterio.enums.html#rasterio.enums.Resampling) name such as `"nearest"` or `"average"` works).

Other options:

| Argument | Default | Description |
| --- | --- | --- |
| `table` | the only tile table | Tile table to convert, needed if the geopackage has more than one. |
| `min_zoom`, `max_zoom` | all zoom levels with tiles | Zoom levels to include. `max_zoom` sets the full resolution. Without `resample_unaligned`, setting `min_zoom` expands the extent to line up with that zoom level's pixels, which can make the output much larger. |
| `bands` | `"RGBA"` | `"RGBA"` makes missing tiles transparent. `"RGB"` makes them black, and is required for JPEG compression. |
| `compress` | `"DEFLATE"` | Any GDAL COG compression, such as `"ZSTD"`, `"LZW"`, `"WEBP"` or `"JPEG"`. |
| `blocksize` | the geopackage tile width | Internal tile size of the COG. |
| `overwrite` | `False` | Replace an existing output file. |

COG conversion requires [rasterio](https://rasterio.readthedocs.io/), which includes GDAL's COG driver in its wheels.