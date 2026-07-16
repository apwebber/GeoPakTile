# PyGeopkgXYZ

For writing geopackage XYZ raster tile layers, with support for using arbitrary grid systems.

Geopackage XYZ files can use any tile grid system, this is often defined by a server's GetCapabilities response where a TileMatrixSet defines the data co-ordinate system, the extent, the number of rows and columns in each zoom lever, and the corner co-ordinates for each zoom level. This package contains a tool for parsing the GetCapabilities XML into a `TileMatrixSet`, and then for writing tiles to a new or existing geopackage.

## Examples

Write tiles to a new geopackage using web mercator (similar to mbtiles), where tiles is a list of (z, x, y, bytes). `tms` is a `TileMatrixSet` - the default web mercator can be produced with `create_web_mercator_tms()`

```
with GPKGXYZ(test_gpkg, tms=create_web_mercator_tms(), mode='rwc') as gpkg:
    gpkg.add_tiles(tiles)
```

Parse a GetCapabilties xml to provide the TileMatrixSet for writing a geopackage:

```
tms_set = parse_capabilities(xml)
tms = tms_set[0] # you'll need to know which one you want, or use:

tms = get_tile_matrix_set(xml, identifier = '1km') # an identifier that you know is defined in the xml

with GPKGXYZ(test_gpkg, tms=tms, mode='rwc') as gpkg:
    gpkg.add_tiles(tiles)
```


### XML Parser

The xml parser has been tested on NASA GetCapabilties XML and some others, if you come across any that doesn't work then please raise an issue or fix and pull request.

