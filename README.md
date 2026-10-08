# GeoPakTile

For writing geopackage XYZ raster tile layers, with support for using arbitrary grid systems.

Geopackage XYZ files can use any tile grid system, this is often defined by a server's GetCapabilities response where a TileMatrixSet defines the data co-ordinate system, the extent, the number of rows and columns in each zoom lever, and the corner co-ordinates for each zoom level. This package contains a tool for parsing the GetCapabilities XML into a [morecantile](https://github.com/developmentseed/morecantile) `TileMatrixSet`, and then for writing tiles to a new or existing geopackage.

## Examples

Write tiles to a new geopackage using web mercator (similar to mbtiles), where tiles is a list of (z, x, y, bytes). `tms` is a morecantile `TileMatrixSet` - the standard web mercator can be obtained with `morecantile.tms.get('WebMercatorQuad')`

```
with GeoPakTile(test_gpkg, tms=morecantile.tms.get('WebMercatorQuad'), mode='rwc') as gpkg:
    gpkg.add_tiles(tiles)
```

Parse a GetCapabilties xml to provide the TileMatrixSet for writing a geopackage:

```
tms_set = parse_capabilities(xml)
tms = tms_set[0] # you'll need to know which one you want, or use:

tms = get_tile_matrix_set(xml, identifier = '1km') # an identifier that you know is defined in the xml

with GeoPakTile(test_gpkg, tms=tms, mode='rwc') as gpkg:
    gpkg.add_tiles(tiles)
```


### TileMatrixSet models

Tile Matrix definitions use the [morecantile](https://github.com/developmentseed/morecantile) package (`morecantile.TileMatrixSet`, `TileMatrix`, etc.) so any morecantile TileMatrixSet (built-in or custom-loaded) can be passed to `GeoPakTile`. The XML parser returns morecantile `TileMatrixSet` objects.

### XML Parser

The xml parser has been tested on NASA GetCapabilties XML and some others, if you come across any that doesn't work then please raise an issue or fix and pull request.

