import httpx
from typing import Any

BASE_URL = "https://api-proxy.miamidade.gov/property/v1"


async def fetch_parcels(
    api_key: str,
    offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch parcels from Miami-Dade Property Appraiser API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/parcels",
            headers={"x-api-key": api_key},
            params={"offset": offset, "limit": limit},
        )
        resp.raise_for_status()
        return resp.json().get("parcels", [])


def normalize_parcel(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize Miami-Dade parcel to internal schema."""
    return {
        "parcel_id": raw.get("parcelNumber", ""),
        "county": "miami-dade",
        "owner_name": raw.get("ownerName1", ""),
        "owner_address": raw.get("mailingAddress1", ""),
        "address": raw.get("propertyAddress", ""),
        "land_value": int(raw.get("landValue", 0) or 0),
        "building_value": int(raw.get("buildingValue", 0) or 0),
        "total_value": int(raw.get("totalValue", 0) or 0),
        "lot_size_sqft": float(raw.get("lotSizeSquareFeet", 0) or 0),
        "zoning_code": raw.get("zoningCode", ""),
        "last_sale_date": raw.get("lastSaleDate"),
        "last_sale_price": int(raw.get("lastSalePrice", 0) or 0),
    }
