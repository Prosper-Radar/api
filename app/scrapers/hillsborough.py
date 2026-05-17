"""
Hillsborough County Property Appraiser scraper.

Uses the official HCPA ArcGIS Feature Service (publicly accessible).
Endpoint verified 2025: https://maps.hcpafl.org/server/rest/services/

Reference:
  https://maps.hcpafl.org/server/rest/services/Parcel/ParcelLayers/MapServer/0/query
  No API key required.
"""
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

_BASE_URL = (
    "https://maps.hcpafl.org/server/rest/services/"
    "Parcel/ParcelLayers/MapServer/0/query"
)

_OUT_FIELDS = ",".join([
    "PARCEL_ID",
    "OWNER_NAME",
    "MAIL_ADDR1",       # mailing address line 1
    "SITUS_ADDR",       # site/property address
    "LAND_VAL",
    "BLDG_VAL",
    "TOTAL_VAL",
    "LAND_AREA_SQFT",   # lot size in sqft
    "ZONING",
    "LAST_SALE_DT",
    "LAST_SALE_PRC",
])


@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
async def fetch_parcels(
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Fetch parcels from Hillsborough County PA ArcGIS Feature Service.
    Returns a list of raw feature dicts.
    """
    params = {
        "where": "LAND_AREA_SQFT > 0",
        "outFields": _OUT_FIELDS,
        "resultOffset": offset,
        "resultRecordCount": limit,
        "orderByFields": "PARCEL_ID ASC",
        "returnGeometry": "true",
        "outSR": "4326",
        "geometryType": "esriGeometryPolygon",
        "f": "json",
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.get(_BASE_URL, params=params)
        resp.raise_for_status()

    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"HCPA ArcGIS error: {data['error']}")

    return data.get("features", [])


def normalize_parcel(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise an ArcGIS feature dict to the internal Parcel schema.
    """
    attrs = raw.get("attributes", raw)
    geom  = raw.get("geometry")

    geometry_wkt = None
    if geom and geom.get("rings"):
        ring = geom["rings"][0]
        coords = ", ".join(f"{x} {y}" for x, y in ring)
        geometry_wkt = f"SRID=4326;POLYGON(({coords}))"

    return {
        "parcel_id":      attrs.get("PARCEL_ID", ""),
        "county":         "hillsborough",
        "owner_name":     attrs.get("OWNER_NAME", ""),
        "owner_address":  attrs.get("MAIL_ADDR1", ""),
        "address":        attrs.get("SITUS_ADDR", ""),
        "land_value":     int(attrs.get("LAND_VAL") or 0),
        "building_value": int(attrs.get("BLDG_VAL") or 0),
        "total_value":    int(attrs.get("TOTAL_VAL") or 0),
        "lot_size_sqft":  float(attrs.get("LAND_AREA_SQFT") or 0),
        "zoning_code":    attrs.get("ZONING", ""),
        "last_sale_date": attrs.get("LAST_SALE_DT"),
        "last_sale_price": int(attrs.get("LAST_SALE_PRC") or 0),
        "geometry":       geometry_wkt,
        "raw_data":       str(attrs),
    }
