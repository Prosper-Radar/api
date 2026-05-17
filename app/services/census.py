"""
Census ACS 5-year population growth service.

Flow per parcel centroid (lat, lng):
 1. Census Geocoder → state / county / tract FIPS
 2. ACS 5-year 2022 → total population (B01003_001E)
 3. ACS 5-year 2019 → total population (B01003_001E)
 4. CAGR = (pop22 / pop19)^(1/3) - 1

Results are cached in-process by tract FIPS to avoid redundant API calls.
Requires CENSUS_API_KEY (free from api.census.gov/signup.html).
"""
import logging
from typing import Optional
from functools import lru_cache

import httpx

logger = logging.getLogger(__name__)

_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
)
_ACS_URL = "https://api.census.gov/data/{year}/acs/acs5"

# Simple in-process cache: (state, county, tract) → CAGR
_TRACT_CACHE: dict[tuple[str, str, str], Optional[float]] = {}


async def _get_tract(lon: float, lat: float) -> Optional[tuple[str, str, str]]:
    """Return (state_fips, county_fips, tract_fips) for a coordinate pair."""
    params = {
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Census2020_Current",
        "layers": "10",
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(_GEOCODER_URL, params=params)
        r.raise_for_status()
        data = r.json()

    try:
        geo = data["result"]["geographies"]["Census Tracts"][0]
        return geo["STATE"], geo["COUNTY"], geo["TRACT"]
    except (KeyError, IndexError):
        return None


@lru_cache(maxsize=2048)
def _pop_cache_key(state: str, county: str, tract: str, year: int) -> str:
    return f"{state}:{county}:{tract}:{year}"


async def _get_tract_population(
    state: str,
    county: str,
    tract: str,
    year: int,
    api_key: str,
) -> Optional[int]:
    url = _ACS_URL.format(year=year)
    params = {
        "get": "B01003_001E",
        "for": f"tract:{tract}",
        "in": f"state:{state} county:{county}",
        "key": api_key,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        rows = r.json()

    # rows = [["B01003_001E","state","county","tract"], ["12345","12","086","000100"]]
    if len(rows) < 2:
        return None
    try:
        return int(rows[1][0])
    except (IndexError, ValueError):
        return None


async def get_population_growth_rate(
    lon: float,
    lat: float,
    api_key: str,
) -> Optional[float]:
    """
    Returns 3-year population CAGR (decimal) for the census tract at (lon, lat).
    Returns None on any error or if the Census API key is not configured.
    """
    if not api_key:
        logger.debug("CENSUS_API_KEY not set — skipping population growth")
        return None

    try:
        tract_info = await _get_tract(lon, lat)
        if tract_info is None:
            return None

        state, county, tract = tract_info

        # Check in-process cache first
        cache_key = (state, county, tract)
        if cache_key in _TRACT_CACHE:
            return _TRACT_CACHE[cache_key]

        pop22, pop19 = await _get_tract_population(
            state, county, tract, 2022, api_key
        ), await _get_tract_population(state, county, tract, 2019, api_key)

        if pop22 is None or pop19 is None or pop19 == 0:
            _TRACT_CACHE[cache_key] = None
            return None

        cagr = (pop22 / pop19) ** (1 / 3) - 1
        _TRACT_CACHE[cache_key] = cagr
        return cagr

    except httpx.HTTPStatusError as exc:
        logger.warning("Census API HTTP error (%s): %s", exc.response.status_code, exc)
        return None
    except Exception as exc:
        logger.warning("Census population growth failed at (%.4f, %.4f): %s", lon, lat, exc)
        return None
