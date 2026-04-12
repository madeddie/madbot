import logging

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from bot import db
from bot.utils import md_to_tg

router = Router()
logger = logging.getLogger(__name__)

COMMANDS = {"briefing": "Generate your personalised daily briefing"}

_KEY_LOCATION = "briefing_location"
_KEY_SECTIONS = "briefing_sections"
_KEY_TIMEZONE = "briefing_timezone"
_VALID_SECTIONS = {"weather", "time", "news", "schedules", "orders"}
_DEFAULT_SECTIONS = "weather,time,schedules"


# ---- Briefing query builder ----

def _build_briefing_query(user_id: int) -> str:
    """Build a structured multi-tool prompt for the user's daily briefing."""
    facts = db.get_facts(user_id)
    location = facts.get(_KEY_LOCATION)
    sections_raw = facts.get(_KEY_SECTIONS, _DEFAULT_SECTIONS)
    sections = [s.strip() for s in sections_raw.split(",") if s.strip()]
    tz = facts.get(_KEY_TIMEZONE) or facts.get("timezone", "UTC")

    parts = [
        "Please generate my daily briefing. Follow these instructions exactly and call "
        "each relevant tool before composing your reply:\n"
    ]

    step = 1
    parts.append(f"{step}. Call get_time to get the current date and time.")
    step += 1

    if "weather" in sections:
        if location:
            parts.append(f"{step}. Call get_weather for {location!r} to get current conditions.")
            step += 1
            parts.append(f"{step}. Call get_weather_forecast for {location!r} to get the 3-day forecast.")
            step += 1
        else:
            parts.append(
                f"{step}. (Weather section requested but no location is configured — skip weather tools "
                "and include a friendly tip asking the user to set their briefing location, "
                "e.g. 'Tell me your city to add a weather section to future briefings.')"
            )
            step += 1

    if "news" in sections:
        parts.append(
            f"{step}. Call get_news_headlines to fetch today's top headlines from AP News and BBC News. "
            "Present the results as a numbered list under a News section."
        )
        step += 1

    if "schedules" in sections:
        parts.append(f"{step}. Call list_schedules to show any upcoming scheduled tasks.")
        step += 1

    if "orders" in sections:
        parts.append(f"{step}. Call list_amazon_orders to check recent and upcoming deliveries.")
        step += 1

    parts.append(
        f"\nAfter calling all the above tools, compile their results into a well-formatted daily briefing. "
        f"Use Markdown with clear section headings. Display times in the {tz} timezone. "
        "Start with a friendly greeting that includes today's date. Keep it concise but complete."
    )

    return "\n".join(parts)


# ---- Configure briefing tool ----

# Plain dict schema: all fields are optional plain strings (no null).
# Using str | None / anyOf:[string,null] confuses some models into passing null.
_CONFIGURE_BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "location": {
            "type": "string",
            "description": "City for weather in the briefing, e.g. 'London'. Omit to leave unchanged.",
        },
        "sections": {
            "type": "string",
            "description": (
                "Comma-separated list of sections to include. "
                "Valid values: weather, time, news, schedules, orders. "
                "Example: 'weather,time,schedules'. Omit to leave unchanged."
            ),
        },
        "timezone": {
            "type": "string",
            "description": "IANA timezone for displaying times, e.g. 'America/New_York'. Omit to leave unchanged.",
        },
    },
    "required": [],
}


def make_briefing_tools(user_id: int) -> list:
    """Return AI tools for configuring the briefing, with user_id pre-bound."""

    def _do_configure_briefing(
        location: str = "",
        sections: str = "",
        timezone: str = "",
    ) -> str:
        changed = []

        if location:
            db.set_fact(user_id, _KEY_LOCATION, location)
            changed.append(f"location → {location!r}")

        if sections:
            requested = [s.strip() for s in sections.split(",") if s.strip()]
            invalid = [s for s in requested if s not in _VALID_SECTIONS]
            valid = [s for s in requested if s in _VALID_SECTIONS]
            if invalid:
                return (
                    f"Unknown section(s): {', '.join(invalid)}. "
                    f"Valid options are: {', '.join(sorted(_VALID_SECTIONS))}."
                )
            db.set_fact(user_id, _KEY_SECTIONS, ",".join(valid))
            changed.append(f"sections → {', '.join(valid)}")

        if timezone:
            db.set_fact(user_id, _KEY_TIMEZONE, timezone)
            changed.append(f"timezone → {timezone!r}")

        if not changed:
            return "No changes were specified."

        facts = db.get_facts(user_id)
        current_location = facts.get(_KEY_LOCATION, "(not set)")
        current_sections = facts.get(_KEY_SECTIONS, _DEFAULT_SECTIONS)
        current_tz = facts.get(_KEY_TIMEZONE) or facts.get("timezone", "UTC")
        return (
            f"Briefing configured: {'; '.join(changed)}.\n"
            f"Current settings — location: {current_location}, "
            f"sections: {current_sections}, timezone: {current_tz}."
        )

    return [
        ai_tool(
            name="configure_briefing",
            description=(
                "Configure the user's daily briefing preferences. "
                "Call this when the user wants to set up or change their briefing, "
                "e.g. 'set my briefing location to Paris' or "
                "'include news in my daily briefing'. "
                "Pass only the fields the user mentioned."
            ),
            parameters=_CONFIGURE_BRIEFING_SCHEMA,
            execute=_do_configure_briefing,
        )
    ]


# ---- aiogram command handler ----

@router.message(Command("briefing"))
async def cmd_briefing(message: Message) -> None:
    from bot.ai.chat import one_shot  # late import — avoids circular at module level

    user_id = message.from_user.id
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        query = _build_briefing_query(user_id)
        reply = await one_shot(user_id, query)
        await message.answer(md_to_tg(reply), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception:
        logger.exception("Briefing failed for user %d", user_id)
        await message.answer("Something went wrong generating your briefing. Please try again in a moment.")
