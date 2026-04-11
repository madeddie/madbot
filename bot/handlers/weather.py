import asyncio
import json
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


class _WeatherParams(BaseModel):
    location: str = Field(description="City name or airport code, e.g. 'London' or 'JFK'.")


def _fetch_wttr(location: str) -> dict | str:
    """Fetch wttr.in JSON for a location. Returns parsed dict or an error string."""
    url = f"https://wttr.in/{quote(location)}?format=j1"
    req = Request(url, headers={"User-Agent": "madbot/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except URLError as e:
        return f"Could not fetch weather for {location!r}: {e.reason}"


def _get_weather(location: str) -> str:
    data = _fetch_wttr(location)
    if isinstance(data, str):
        return data

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
        return data

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
