# GeoPakTile

For writing geopackage XYZ raster tile layers, with support for using arbitrary grid systems.

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


### TileMatrixSet models

Tile Matrix definitions use the [morecantile](https://github.com/developmentseed/morecantile) package (`morecantile.TileMatrixSet`, `TileMatrix`, etc.) so any morecantile TileMatrixSet (built-in or custom-loaded) can be passed to `GeoPakTile`. The XML parser returns morecantile `TileMatrixSet` objects.

### XML Parser

The xml parser has been tested on NASA GetCapabilties XML and some others, if you come across any that doesn't work then please raise an issue or fix and pull request.