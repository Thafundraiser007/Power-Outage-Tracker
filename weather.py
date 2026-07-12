"""
OpenWeather integration -- snapshots current weather conditions so they
can be stored alongside outage records. Over time this makes it possible
to see correlations like "storms in Waigani precede outages" (see
database.get_weather_correlation_stats).

If OPENWEATHER_API_KEY isn't set, every function here returns None
gracefully rather than raising, so the rest of the app works fine
without it -- weather is an enrichment, not a hard dependency.
"""

import logging

import requests

import config

logger = logging.getLogger("weather")


def get_weather_for_suburb(suburb: str) -> dict:
    """
    Returns a dict like:
        {"condition": "Rain", "description": "moderate rain",
         "temperature_c": 27.4, "humidity_pct": 88, "wind_kph": 14.8,
         "rain_1h_mm": 2.1}
    or None if weather isn't configured or the suburb/API call fails.
    """
    if not config.ENABLE_WEATHER:
        logger.info(f"[weather disabled -- no OPENWEATHER_API_KEY set] Skipping lookup for {suburb}")
        return None

    coords = config.SUBURBS.get(suburb)
    if not coords:
        return None

    try:
        resp = requests.get(
            config.OPENWEATHER_BASE_URL,
            params={
                "lat": coords["lat"],
                "lon": coords["lon"],
                "appid": config.OPENWEATHER_API_KEY,
                "units": "metric",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"OpenWeather lookup failed for {suburb}: {e}")
        return None

    try:
        weather_block = data.get("weather", [{}])[0]
        main = data.get("main", {})
        wind = data.get("wind", {})
        rain = data.get("rain", {})

        return {
            "condition": weather_block.get("main"),           # e.g. "Rain"
            "description": weather_block.get("description"),   # e.g. "moderate rain"
            "temperature_c": main.get("temp"),
            "humidity_pct": main.get("humidity"),
            "wind_kph": round(wind.get("speed", 0) * 3.6, 1) if wind.get("speed") is not None else None,
            "rain_1h_mm": rain.get("1h"),
        }
    except Exception as e:
        logger.error(f"Failed to parse OpenWeather response for {suburb}: {e}")
        return None


def weather_summary_line(weather: dict) -> str:
    """Short human-readable line for display, e.g. 'Heavy rain, 27°C, 15 km/h wind'."""
    if not weather:
        return ""
    parts = []
    if weather.get("description"):
        parts.append(weather["description"].capitalize())
    if weather.get("temperature_c") is not None:
        parts.append(f"{weather['temperature_c']:.0f}°C")
    if weather.get("wind_kph") is not None:
        parts.append(f"{weather['wind_kph']:.0f} km/h wind")
    return ", ".join(parts)


def is_severe_weather(weather: dict) -> bool:
    """
    Rough heuristic for whether current conditions might plausibly be
    contributing to power issues (storms, heavy rain, high wind) -- used
    to surface a "weather may be affecting restoration" hint in the UI.
    """
    if not weather:
        return False
    severe_conditions = {"Thunderstorm", "Tornado", "Squall"}
    if weather.get("condition") in severe_conditions:
        return True
    if weather.get("wind_kph") and weather["wind_kph"] >= 40:
        return True
    if weather.get("rain_1h_mm") and weather["rain_1h_mm"] >= 10:
        return True
    return False
