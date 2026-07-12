"""
LocationIQ integration -- converts a free-text address ("Gordons Market")
into coordinates, so users reporting an outage aren't limited to picking
from the fixed suburb list. Also resolves a geocoded point back to the
nearest known suburb, so it still fits into the suburb-based map/search/
notification system the rest of the app uses.

If LOCATIONIQ_API_KEY isn't set, geocode_address() returns None so the
report form falls back to the plain suburb dropdown instead.
"""

import logging
import math

import requests

import config

logger = logging.getLogger("geocode")


def geocode_address(query: str) -> dict:
    """
    Returns {"latitude": ..., "longitude": ..., "display_name": ...}
    for the best match, or None if geocoding is disabled, the query is
    empty, or nothing was found.
    """
    if not config.ENABLE_GEOCODING or not query or not query.strip():
        return None

    try:
        resp = requests.get(
            config.LOCATIONIQ_BASE_URL,
            params={
                "key": config.LOCATIONIQ_API_KEY,
                "q": f"{query}, Port Moresby, Papua New Guinea",
                "format": "json",
                "limit": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        logger.error(f"LocationIQ geocode failed for '{query}': {e}")
        return None

    if not results:
        return None

    try:
        top = results[0]
        return {
            "latitude": float(top["lat"]),
            "longitude": float(top["lon"]),
            "display_name": top.get("display_name", query),
        }
    except (KeyError, ValueError, IndexError) as e:
        logger.error(f"Unexpected LocationIQ response shape for '{query}': {e}")
        return None


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_suburb(latitude: float, longitude: float) -> str:
    """
    Finds the closest suburb (from config.SUBURBS) to a geocoded point --
    this is how a free-text address gets slotted back into the app's
    suburb-based map markers, search, and per-suburb notifications.
    """
    best_suburb, best_distance = None, float("inf")
    for suburb, coords in config.SUBURBS.items():
        d = _haversine_km(latitude, longitude, coords["lat"], coords["lon"])
        if d < best_distance:
            best_suburb, best_distance = suburb, d
    return best_suburb
