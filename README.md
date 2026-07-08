# PyGeopkgXYZ

```
with GPKGXYZ(test_gpkg, tms=create_web_mercator_tms(), mode='rwc') as gpkg:
    gpkg.add_tiles(tiles)
```

where tiles is a list of (z, x, y, bytes)

tms is a `TileMatrixSet` - the default web mercator can be produced with `create_web_mercator_tms()`