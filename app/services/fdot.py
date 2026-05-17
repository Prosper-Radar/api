"""
FDOT (Florida Department of Transportation) AADT service.

Queries the public FDOT GIS ArcGIS Feature Service to find the road segment
with the highest Annual Average Daily Traffic within 200 m of a parcel centroid.

No API key required — FDOT GIS is a public open-data portal.
Endpoint: https://gis.fdot.gov/arcgis/rest/services/AADT/AADT_Current/FeatureServer/0

Docs: https://gis.fdot.gov/arcgis/rest/services/AADT/
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_FDOT_AADT_URL = (
    "https://gis.fdot.gov/arcgis/rest/services/"
    "AADT/AADT_Current/FeatureServer/0/query"
)

# Search radius in metres — ~200 m is enough to capture the nearest arterial.
_SEARCH_RADIUS_M = 200


def _build_envelope(lon: float, lat: float, buffer_deg: float = 0.002) -> str:
    """Return a small bounding-box envelope string for the ArcGIS geometry param."""
    return (
        f"{lon - buffer_deg},{lat - buffer_deg},"
        f"{lon + buffer_deg},{lat + buffer_deg}"
    )


async def get_aadt(lon: float, lat: float) -> Optional[int]:
    """
    Returns the maximum AADT value found on road segments within 200 m of
    the given coordinate pair.

    Returns None on any error or if no road segment is found nearby.
    """
    params = {
        "geometry": _build_envelope(lon, lat),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "AADT_Final,AADT_Year",
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(_FDOT_AADT_URL, params=params)
            r.raise_for_status()
            data = r.json()

        features = data.get("features", [])
        if not features:
            return None

        aadt_values = [
            f["attributes"].get("AADT_Final")
            for f in features
            if f.get("attributes", {}).get("AADT_Final") is not None
        ]
        if not aadt_values:
            return None

        return int(max(aadt_values))

    except httpx.HTTPStatusError as exc:
        logger.warning("FDOT AADT HTTP error (%s) at (%.4f, %.4f): %s",
                       exc.response.status_code, lon, lat, exc)
        return None
    except Exception as exc:
        logger.warning("FDOT AADT failed at (%.4f, %.4f): %s", lon, lat, exc)
        return None
