"""
Miami-Dade Property Appraiser scraper.

Uses the official Miami-Dade GIS ArcGIS Feature Service (PA layer).
Endpoint verified 2025: publicly accessible, no API key required for read.

Reference:
  https://gisws.miamidade.gov/arcgis/rest/services/PA/PA_Parcels/FeatureServer/0
  Query docs: https://developers.arcgis.com/rest/services-reference/feature-service/
"""
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

# Public ArcGIS REST endpoint — Miami-Dade Property Appraiser parcels layer
_BASE_URL = (
    "https://gisws.miamidade.gov/arcgis/rest/services/"
    "PA/PA_Parcels/FeatureServer/0/query"
)

_OUT_FIELDS = ",".join([
    "PARCELNO",        # folio / parcel number
    "OWNER1",          # primary owner name
    "MAILADD",         # mailing address
    "ADDRESS",         # property address
    "LANDVAL",         # assessed land value ($)
    "BLDGVAL",         # assessed building value ($)
    "DОРАL",           # total assessed value — field name varies; we try TOTALVAL too
    "TOTALVAL",
    "ACREAGE",         # lot size in acres → converted to sqft
    "ZONINGCD",        # zoning code
    "SALESDATE",       # last sale date (MM/DD/YYYY)
    "SALESPRICE",      # last sale price ($)
])


@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
async def fetch_parcels(
    api_key: str = "",        # kept for interface compatibility; not required
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Fetch parcels from Miami-Dade GIS ArcGIS Feature Service.
    Returns a list of raw feature dicts (ArcGIS JSON format).
    """
    params = {
        "where": "ACREAGE > 0",        # basic filter — skip empty records
        "outFields": _OUT_FIELDS,
        "resultOffset": offset,
        "resultRecordCount": limit,
        "orderByFields": "PARCELNO ASC",
        "returnGeometry": "true",
        "outSR": "4326",
        "geometryType": "esriGeometryPolygon",
        "f": "json",
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.get(_BASE_URL, params=params)
        resp.raise_for_status()

    data = resp.json()

    # ArcGIS error block (200 OK but error payload)
    if "error" in data:
        raise RuntimeError(f"Miami-Dade ArcGIS error: {data['error']}")

    return data.get("features", [])


def normalize_parcel(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise an ArcGIS feature dict to the internal Parcel schema.

    ArcGIS format:
      { "attributes": { ... }, "geometry": { "rings": [...] } }
    """
    attrs = raw.get("attributes", raw)
    geom  = raw.get("geometry")

    # WKT polygon from rings list (first ring = exterior)
    geometry_wkt = None
    if geom and geom.get("rings"):
        ring = geom["rings"][0]
        coords = ", ".join(f"{x} {y}" for x, y in ring)
        geometry_wkt = f"SRID=4326;POLYGON(({coords}))"

    # Acre → sqft (1 acre = 43 560 sqft)
    acreage = float(attrs.get("ACREAGE") or 0)
    lot_size_sqft = acreage * 43_560

    # Total value — field name may differ
    total_val = int(attrs.get("TOTALVAL") or attrs.get("DОРАL") or 0)

    return {
        "parcel_id":      attrs.get("PARCELNO", ""),
        "county":         "miami-dade",
        "owner_name":     attrs.get("OWNER1", ""),
        "owner_address":  attrs.get("MAILADD", ""),
        "address":        attrs.get("ADDRESS", ""),
        "land_value":     int(attrs.get("LANDVAL") or 0),
        "building_value": int(attrs.get("BLDGVAL") or 0),
        "total_value":    total_val,
        "lot_size_sqft":  lot_size_sqft,
        "zoning_code":    attrs.get("ZONINGCD", ""),
        "last_sale_date": attrs.get("SALESDATE"),
        "last_sale_price": int(attrs.get("SALESPRICE") or 0),
        "geometry":       geometry_wkt,
        "raw_data":       str(attrs),
    }
