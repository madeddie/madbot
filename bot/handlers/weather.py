import asyncio
import json
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from pydantic import BaseModel, Field

router = Router()

COMMANDS = {"weather": "Get current weather or forecast — /weather [forecast] &lt;location&gt;"}

_WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Light snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


class _WeatherParams(BaseModel):
    location: str = Field(description="City name or airport code, e.g. 'London' or 'JFK'.")


def _fetch_url(url: str, retries: int = 3, delay: float = 1.0) -> bytes | str:
    """Fetch a URL with retry. Returns raw bytes on success, error string on failure."""
    req = Request(url, headers={"User-Agent": "madbot/1.0"})
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.read()
        except URLError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return f"Network error after {retries} attempts: {getattr(last_err, 'reason', last_err)}"


def _fetch_wttr(location: str) -> dict | str:
    """Fetch wttr.in JSON for a location. Returns parsed dict or an error string."""
    url = f"https://wttr.in/{quote(location)}?format=j1"
    raw = _fetch_url(url)
    if isinstance(raw, str):
        return f"Could not fetch weather for {location!r}: {raw}"
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        return f"Could not parse weather data for {location!r}: {e}"


def _geocode(location: str) -> tuple[float, float, str, str] | str:
    """Resolve a location name to (lat, lon, city, country) via open-meteo geocoding."""
    url = (
        f"https://geocoding-api.open-meteo.com/v1/search"
        f"?name={quote(location)}&count=1&language=en&format=json"
    )
    raw = _fetch_url(url)
    if isinstance(raw, str):
        return raw
    try:
        result = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return f"Could not parse geocoding response: {e}"
    if not result.get("results"):
        return f"Location {location!r} not found."
    r = result["results"][0]
    return r["latitude"], r["longitude"], r.get("name", location), r.get("country", "")


def _fetch_open_meteo_weather(location: str) -> str:
    """Fetch current weather from open-meteo as a fallback."""
    geo = _geocode(location)
    if isinstance(geo, str):
        return geo
    lat, lon, city, country = geo
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,apparent_temperature,weather_code,precipitation_probability"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=auto&forecast_days=1"
    )
    raw = _fetch_url(url)
    if isinstance(raw, str):
        return raw
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return f"Could not parse open-meteo response: {e}"
    cur = d["current"]
    daily = d["daily"]
    temp = cur["temperature_2m"]
    feels = cur["apparent_temperature"]
    desc = _WMO_CODES.get(cur["weather_code"], f"Code {cur['weather_code']}")
    low = daily["temperature_2m_min"][0]
    high = daily["temperature_2m_max"][0]
    rain = daily["precipitation_probability_max"][0] or 0
    return (
        f"<b>{city}, {country}</b> — {desc}\n"
        f"🌡 {temp}°C (feels like {feels}°C)\n"
        f"↕ {low}°C / {high}°C\n"
        f"🌧 {rain}% chance of rain"
    )


def _fetch_open_meteo_forecast(location: str) -> str:
    """Fetch 3-day forecast from open-meteo as a fallback."""
    geo = _geocode(location)
    if isinstance(geo, str):
        return geo
    lat, lon, city, country = geo
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=auto&forecast_days=3"
    )
    raw = _fetch_url(url)
    if isinstance(raw, str):
        return raw
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as e:
        return f"Could not parse open-meteo response: {e}"
    daily = d["daily"]
    lines = [f"<b>{city}, {country} — 3-day forecast</b>"]
    for i, date in enumerate(daily["time"]):
        desc = _WMO_CODES.get(daily["weather_code"][i], f"Code {daily['weather_code'][i]}")
        low = daily["temperature_2m_min"][i]
        high = daily["temperature_2m_max"][i]
        rain = daily["precipitation_probability_max"][i] or 0
        lines.append(f"\n📅 {date} — {desc}\n↕ {low}°C / {high}°C  🌧 {rain}%")
    return "\n".join(lines)


def _get_weather(location: str) -> str:
    data = _fetch_wttr(location)
    if isinstance(data, str):
        return _fetch_open_meteo_weather(location)

    cur = data["current_condition"][0]
    today = data["weather"][0]
    area = data["nearest_area"][0]

    city = area["areaName"][0]["value"]
    country = area["country"][0]["value"]
    desc = cur["weatherDesc"][0]["value"]
    temp = cur["temp_C"]
    feels = cur["FeelsLikeC"]
    low = today["mintempC"]
    high = today["maxtempC"]
    rain_chance = max(int(h["chanceofrain"]) for h in today["hourly"])

    return (
        f"<b>{city}, {country}</b> — {desc}\n"
        f"🌡 {temp}°C (feels like {feels}°C)\n"
        f"↕ {low}°C / {high}°C\n"
        f"🌧 {rain_chance}% chance of rain"
    )


def _get_weather_forecast(location: str) -> str:
    data = _fetch_wttr(location)
    if isinstance(data, str):
        return _fetch_open_meteo_forecast(location)

    area = data["nearest_area"][0]
    city = area["areaName"][0]["value"]
    country = area["country"][0]["value"]

    lines = [f"<b>{city}, {country} — 3-day forecast</b>"]
    for day in data["weather"]:
        date = day["date"]
        desc = day["hourly"][4]["weatherDesc"][0]["value"]
        low = day["mintempC"]
        high = day["maxtempC"]
        rain_chance = max(int(h["chanceofrain"]) for h in day["hourly"])
        lines.append(f"\n📅 {date} — {desc}\n↕ {low}°C / {high}°C  🌧 {rain_chance}%")

    return "\n".join(lines)


AI_TOOLS = [
    ai_tool(
        name="get_weather",
        description="Get current weather conditions for a city or location.",
        parameters=_WeatherParams,
        execute=_get_weather,
    ),
    ai_tool(
        name="get_weather_forecast",
        description="Get a 3-day weather forecast for a city or location.",
        parameters=_WeatherParams,
        execute=_get_weather_forecast,
    ),
]


@router.message(Command("weather"))
async def cmd_weather(message: Message) -> None:
    args = message.text.removeprefix("/weather").strip()
    if not args:
        await message.answer("Usage: /weather &lt;location&gt; or /weather forecast &lt;location&gt;")
        return
    if args.lower().startswith("forecast "):
        location = args[9:].strip()
        result = await asyncio.to_thread(_get_weather_forecast, location)
    else:
        result = await asyncio.to_thread(_get_weather, args)
    await message.answer(result)
