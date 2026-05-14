import httpx
from typing import Any

BASE_URL = "https://gis.hcpafl.org/api"


async def fetch_parcels(
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch parcels from Hillsborough County Property Appraiser API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/parcels",
            params={"offset": offset, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json().get("features", [])


def normalize_parcel(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize Hillsborough parcel to internal schema."""
    props = raw.get("properties", raw)
    return {
        "parcel_id": props.get("PARCEL_ID", ""),
        "county": "hillsborough",
        "owner_name": props.get("OWNER_NAME", ""),
        "owner_address": props.get("MAIL_ADDR", ""),
        "address": props.get("SITE_ADDR", ""),
        "land_value": int(props.get("LAND_VALUE", 0) or 0),
        "building_value": int(props.get("BLDG_VALUE", 0) or 0),
        "total_value": int(props.get("TOTAL_VALUE", 0) or 0),
        "lot_size_sqft": float(props.get("LAND_AREA", 0) or 0),
        "zoning_code": props.get("ZONING", ""),
        "last_sale_date": props.get("SALE_DATE"),
        "last_sale_price": int(props.get("SALE_PRICE", 0) or 0),
    }
