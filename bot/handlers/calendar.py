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

COMMANDS = {"calendar": "Show upcoming calendar events — /calendar [days] [all|<calendar-name>]"}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ---- Personal calendars (iCal) ----

def _fetch_ical(url: str) -> Calendar:
    req = Request(url, headers={"User-Agent": "madbot/1.0"})
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


def _get_ical_events(url: str, days: int) -> list[tuple[datetime, str]]:
    cal = _fetch_ical(url)
    now = datetime.now(timezone.utc)
    events = recurring_ical_events.of(cal).between(now, now + timedelta(days=days))
    return sorted(
        [(_ical_start_dt(ev), _format_ical_event(ev)) for ev in events],
        key=lambda x: x[0],
    )


# ---- Work calendar (Google Sheet) ----

def _get_work_events(days: int) -> list[tuple[datetime, str]]:
    url = f"https://docs.google.com/spreadsheets/d/{settings.gsheet_calendar_id}/export?format=csv"
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
        _, title, start_str, *rest = row
        title = title.strip()
        start_str = start_str.strip()
        if not title or not start_str:
            continue
        end_str = rest[0].strip() if rest else ""

        try:
            start_dt = datetime.strptime(start_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
            if start_dt.date() < today or start_dt.date() > end_date:
                continue
            time_fmt = start_dt.strftime("%Y-%m-%d %H:%M")
            if end_str:
                try:
                    end_dt = datetime.strptime(end_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
                    if end_dt.date() == start_dt.date():
                        fmt = f"- {title}: {time_fmt}–{end_dt.strftime('%H:%M')}"
                    else:
                        fmt = f"- {title}: {time_fmt}"
                except ValueError:
                    fmt = f"- {title}: {time_fmt}"
            else:
                fmt = f"- {title}: {time_fmt}"
        except ValueError:
            try:
                start_date = datetime.strptime(start_str, "%m/%d/%Y").date()
            except ValueError:
                continue
            if start_date < today or start_date > end_date:
                continue
            start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
            fmt = f"- {title}: {start_date} (all day)"

        results.append((start_dt, fmt))

    return sorted(results, key=lambda x: x[0])


# ---- Combined fetch ----

def _get_upcoming_events(days: int = 7, source: str = "all") -> str:
    ical_calendars = settings.ical_calendars
    has_work = bool(settings.gsheet_calendar_id)

    if not ical_calendars and not has_work:
        return "No calendar sources configured (set ICAL_CALENDARS and/or GSHEET_CALENDAR_ID)."

    if source == "all":
        want_ical = dict(ical_calendars)
        want_work = has_work
    elif source == "work" and has_work and source not in ical_calendars:
        want_ical = {}
        want_work = True
    elif source in ical_calendars:
        want_ical = {source: ical_calendars[source]}
        want_work = False
    else:
        available = list(ical_calendars.keys()) + (["work"] if has_work else []) + ["all"]
        return f"Source {source!r} not available. Available: {', '.join(available)}."

    errors: list[str] = []
    ical_results: dict[str, list[tuple[datetime, str]]] = {}
    work_events: list[tuple[datetime, str]] = []

    for name, url in want_ical.items():
        try:
            ical_results[name] = _get_ical_events(url, days)
        except (URLError, Exception) as e:
            errors.append(f"{name!r} calendar error: {e}")

    if want_work:
        try:
            work_events = _get_work_events(days)
        except (URLError, Exception) as e:
            errors.append(f"Work calendar error: {e}")

    day_str = f"{days} day{'s' if days != 1 else ''}"
    lines: list[str] = []

    total_sources = len(ical_results) + (1 if want_work else 0)

    if total_sources == 1:
        if want_work:
            lines.append(f"**Work calendar — next {day_str}:**")
            lines.extend(fmt for _, fmt in work_events) if work_events else lines.append(f"No events in the next {day_str}.")
        else:
            name = next(iter(ical_results))
            events = ical_results[name]
            lines.append(f"**{name.capitalize()} calendar — next {day_str}:**")
            lines.extend(fmt for _, fmt in events) if events else lines.append(f"No events in the next {day_str}.")
    else:
        lines.append(f"**Calendar — next {day_str}:**")
        for name, events in ical_results.items():
            lines.append(f"\n**{name.capitalize()}:**")
            if events:
                lines.extend(fmt for _, fmt in events)
            else:
                lines.append("No events.")
        if want_work:
            lines.append("\n**Work:**")
            if work_events:
                lines.extend(fmt for _, fmt in work_events)
            else:
                lines.append("No events.")

    if errors:
        lines.append("")
        lines.extend(errors)

    return "\n".join(lines)


# ---- AI tool ----

class _UpcomingParams(BaseModel):
    days: int = Field(default=7, ge=1, le=90, description="Days ahead to look (default 7, max 90).")
    source: str = Field(
        default="all",
        description="Calendar name, 'work' (Google Sheet), or 'all' (default).",
    )


def _build_calendar_tool_description() -> str:
    names = list(settings.ical_calendars.keys())
    sources = names + (["work"] if settings.gsheet_calendar_id else []) + ["all"]
    return (
        "Get upcoming calendar events. "
        f"source can be: {', '.join(repr(s) for s in sources)}. "
        "'all' fetches every configured calendar. "
        "Use when asked about schedule, appointments, meetings, or what's coming up."
    )


AI_TOOLS = [
    ai_tool(
        name="get_upcoming_calendar_events",
        description=_build_calendar_tool_description(),
        parameters=_UpcomingParams,
        execute=_get_upcoming_events,
    ),
]


# ---- Telegram command ----

@router.message(Command("calendar"))
async def cmd_calendar(message: Message) -> None:
    has_work = bool(settings.gsheet_calendar_id)
    valid_sources = set(settings.ical_calendars.keys()) | ({"work"} if has_work else set()) | {"all"}

    args = message.text.removeprefix("/calendar").strip().split()
    days = 7
    source = "all"

    for arg in args:
        if arg.isdigit():
            days = max(1, min(90, int(arg)))
        elif arg.lower() in valid_sources:
            source = arg.lower()
        else:
            valid_str = "|".join(sorted(valid_sources))
            await message.answer(f"Usage: /calendar [days] [{valid_str}]")
            return

    result = await asyncio.to_thread(_get_upcoming_events, days, source)
    await message.answer(md_to_tg(result), parse_mode="MarkdownV2")
