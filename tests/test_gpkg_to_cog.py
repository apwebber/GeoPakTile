from geopaktile.gpkg_to_cog import gpkg_tiles_to_cog

def test_wembury():
    gpkg_tiles_to_cog(
        "tests/test_data/wembury.gpkg",
        "tests/out/wembury_cog.tif",
    )