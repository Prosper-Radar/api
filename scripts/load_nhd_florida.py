"""
Load NHD (National Hydrography Dataset) Florida water bodies into PostGIS.

Source:
  USGS NHD Best Resolution for Florida — NHDWaterbody layer (area features)
  Download: https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/State/GPKG/NHD_H_Florida_State_GPKG.zip

Usage:
  python scripts/load_nhd_florida.py --db postgresql://... --input NHD_H_Florida_State_GPKG.gpkg

Requirements: pip install geopandas sqlalchemy geoalchemy2 asyncpg psycopg2-binary
"""
import argparse
import sys
import os

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Load NHD Florida water bodies into PostGIS")
parser.add_argument("--db", required=True, help="Synchronous SQLAlchemy DATABASE_URL (postgresql://...)")
parser.add_argument("--input", required=True, help="Path to the NHD GPKG file")
parser.add_argument("--layer", default="NHDWaterbody", help="GeoPackage layer name (default: NHDWaterbody)")
parser.add_argument("--chunk-size", type=int, default=1000, help="Rows per batch insert")
args = parser.parse_args()

try:
    import geopandas as gpd
    from sqlalchemy import create_engine, text
    from geoalchemy2 import Geometry
except ImportError:
    print("Missing deps: pip install geopandas sqlalchemy geoalchemy2 psycopg2-binary")
    sys.exit(1)

print(f"Reading {args.layer} from {args.input} ...")
gdf = gpd.read_file(args.input, layer=args.layer)
print(f"Loaded {len(gdf):,} raw features. CRS: {gdf.crs}", flush=True)

# Reproject to WGS-84 (EPSG:4326) — NHD ships in NAD83 (4269)
if gdf.crs and gdf.crs.to_epsg() != 4326:
    print(f"Reprojecting from EPSG:{gdf.crs.to_epsg()} -> 4326 ...")
    gdf = gdf.to_crs(epsg=4326)

# Detect the real column names (NHD uses lowercase in GPKG)
id_col   = next((c for c in gdf.columns if c.lower() in ("permanent_identifier", "nhdplusid")), None)
name_col = next((c for c in gdf.columns if c.lower() == "gnis_name"), None)
type_col = next((c for c in gdf.columns if c.lower() == "ftype"), None)

keep = {"geometry": "geometry"}
if id_col:   keep[id_col]   = "nhd_id"
if name_col: keep[name_col] = "name"
if type_col: keep[type_col] = "ftype"

gdf = gdf[list(keep.keys())].rename(columns=keep)
if "nhd_id" in gdf.columns:
    gdf["nhd_id"] = gdf["nhd_id"].astype(str)

# Force 2D (NHD has Z coordinates, not needed)
gdf["geometry"] = gdf["geometry"].force_2d()

# Keep only meaningful water-body types (drops tiny swamp slivers)
# FType codes: 390=LakePond, 436=Reservoir, 460=Playa, 466=SwampMarsh (coastal only), 493=Estuary
USEFUL_FTYPES = {390, 436, 460, 466, 493}
if "ftype" in gdf.columns:
    before = len(gdf)
    gdf = gdf[gdf["ftype"].isin(USEFUL_FTYPES)]
    print(f"FType filter: {before:,} -> {len(gdf):,} features retained", flush=True)

# Drop any null or empty geometries
gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]

print(f"{len(gdf):,} valid features after filter. Writing to PostGIS ...", flush=True)

engine = create_engine(args.db)

# Drop and recreate — avoids geometry column type / name conflicts
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS water_bodies CASCADE"))
    conn.commit()
print("Old water_bodies table dropped.", flush=True)

# geopandas creates the geometry column with the correct PostGIS type automatically
gdf.to_postgis(
    "water_bodies",
    engine,
    if_exists="replace",
    index=False,
    chunksize=args.chunk_size,
)
print("Data written. Adding spatial index ...", flush=True)

with engine.connect() as conn:
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_water_bodies_geom "
        "ON water_bodies USING GIST (geometry)"
    ))
    conn.commit()
    count = conn.execute(text("SELECT COUNT(*) FROM water_bodies")).scalar()

print(f"Done -- {count:,} water-body polygons in PostGIS.")
