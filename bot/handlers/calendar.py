import asyncio
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

import recurring_ical_events
from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from icalendar import Calendar
from pydantic import BaseModel, Field

from bot.config import settings
from bot.utils import md_to_tg

router = Router()

COMMANDS = {"calendar": "Show upcoming calendar events — /calendar [days] [personal|business|all]"}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_GSHEET_ID_RE = re.compile(r"/spreadsheets/d/([^/]+)")


# ---- Personal calendar (iCal) ----

def _fetch_ical() -> Calendar:
    req = Request(settings.ical_url, headers={"User-Agent": "madbot/1.0"})
    with urlopen(req, timeout=15) as resp:
        return Calendar.from_ical(resp.read())


def _ical_start_dt(event) -> datetime:
    dt = event.get("DTSTART").dt
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _format_ical_event(event) -> str:
    summary = str(event.get("SUMMARY", "No title"))
    dtstart = event.get("DTSTART").dt
    dtend_prop = event.get("DTEND") or event.get("DTSTART")
    dtend = dtend_prop.dt
    if isinstance(dtstart, datetime):
        start_str = dtstart.strftime("%Y-%m-%d %H:%M")
        if isinstance(dtend, datetime) and dtstart.date() == dtend.date():
            return f"- {summary}: {start_str}–{dtend.strftime('%H:%M')}"
        return f"- {summary}: {start_str}"
    return f"- {summary}: {dtstart} (all day)"


def _get_personal_events(days: int) -> list[tuple[datetime, str]]:
    cal = _fetch_ical()
    now = datetime.now(timezone.utc)
    events = recurring_ical_events.of(cal).between(now, now + timedelta(days=days))
    return sorted(
        [(_ical_start_dt(ev), _format_ical_event(ev)) for ev in events],
        key=lambda x: x[0],
    )


# ---- Business calendar (Google Sheet) ----

def _gsheet_csv_url(url: str) -> str:
    if "/export" in url:
        return url
    m = _GSHEET_ID_RE.search(url)
    if not m:
        raise ValueError(f"Cannot extract sheet ID from URL: {url!r}")
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"


def _get_business_events(days: int) -> list[tuple[datetime, str]]:
    url = _gsheet_csv_url(settings.gsheet_calendar_url)
    req = Request(url, headers={"User-Agent": "madbot/1.0"})
    with urlopen(req, timeout=15) as resp:
        content = resp.read().decode("utf-8")

    now = datetime.now(timezone.utc)
    today = now.date()
    end_date = (now + timedelta(days=days)).date()

    results = []
    for i, row in enumerate(csv.reader(io.StringIO(content))):
        if i == 0 or len(row) < 3:  # first row is empty header
            continue
        _, title, start_str, *_ = row
        title = title.strip()
        if not title or not start_str.strip():
            continue
        try:
            start_date = datetime.strptime(start_str.strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        if start_date < today or start_date > end_date:
            continue
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        results.append((start_dt, f"- {title}: {start_date} (all day)"))

    return sorted(results, key=lambda x: x[0])


# ---- Combined fetch ----

def _get_upcoming_events(days: int = 7, source: str = "all") -> str:
    has_personal = bool(settings.ical_url)
    has_business = bool(settings.gsheet_calendar_url)

    if not has_personal and not has_business:
        return "No calendar sources configured (set ICAL_URL and/or GSHEET_CALENDAR_URL)."

    want_personal = source in ("personal", "all") and has_personal
    want_business = source in ("business", "all") and has_business

    if not want_personal and not want_business:
        available = []
        if has_personal:
            available.append("personal")
        if has_business:
            available.append("business")
        return f"Source {source!r} not available. Available: {', '.join(available)}."

    errors: list[str] = []
    personal_events: list[tuple[datetime, str]] = []
    business_events: list[tuple[datetime, str]] = []

    if want_personal:
        try:
            personal_events = _get_personal_events(days)
        except (URLError, Exception) as e:
            errors.append(f"Personal calendar error: {e}")

    if want_business:
        try:
            business_events = _get_business_events(days)
        except (URLError, Exception) as e:
            errors.append(f"Business calendar error: {e}")

    day_str = f"{days} day{'s' if days != 1 else ''}"
    lines: list[str] = []

    if source == "all" and want_personal and want_business:
        lines.append(f"**Calendar — next {day_str}:**")
        lines.append("\n**Personal:**")
        lines.extend(fmt for _, fmt in personal_events) if personal_events else lines.append("No events.")
        lines.append("\n**Business:**")
        lines.extend(fmt for _, fmt in business_events) if business_events else lines.append("No events.")
    else:
        label = "Personal" if source == "personal" else "Business"
        lines.append(f"**{label} calendar — next {day_str}:**")
        events = personal_events if want_personal else business_events
        if events:
            lines.extend(fmt for _, fmt in events)
        else:
            lines.append(f"No events in the next {day_str}.")

    if errors:
        lines.append("")
        lines.extend(errors)

    return "\n".join(lines)


# ---- AI tool ----

class _UpcomingParams(BaseModel):
    days: int = Field(default=7, ge=1, le=90, description="Days ahead to look (default 7, max 90).")
    source: str = Field(
        default="all",
        description="Which calendar: 'personal' (iCal), 'business' (Google Sheet), or 'all' (both, default).",
    )


AI_TOOLS = [
    ai_tool(
        name="get_upcoming_calendar_events",
        description=(
            "Get upcoming calendar events. source='personal' for the personal iCal calendar, "
            "'business' for the business Google Sheet, 'all' for both (default). "
            "Use when asked about schedule, appointments, meetings, or what's coming up."
        ),
        parameters=_UpcomingParams,
        execute=_get_upcoming_events,
    ),
]


# ---- Telegram command ----

@router.message(Command("calendar"))
async def cmd_calendar(message: Message) -> None:
    args = message.text.removeprefix("/calendar").strip().split()
    days = 7
    source = "all"

    for arg in args:
        if arg.isdigit():
            days = max(1, min(90, int(arg)))
        elif arg.lower() in ("personal", "business", "all"):
            source = arg.lower()
        else:
            await message.answer("Usage: /calendar [days] [personal|business|all]")
            return

    result = await asyncio.to_thread(_get_upcoming_events, days, source)
    await message.answer(md_to_tg(result), parse_mode="MarkdownV2")
