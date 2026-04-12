import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from pydantic import BaseModel, Field

from bot import db

router = Router()
logger = logging.getLogger(__name__)

COMMANDS = {"schedule": "Manage scheduled tasks — /schedule list | cancel &lt;id&gt;"}


# ---- Pydantic parameter models ----

class _ScheduleOnceParams(BaseModel):
    query: str = Field(description="The query or instruction to execute when the job fires.")
    delay_seconds: int = Field(description="How many seconds from now to run the job.", ge=1)


class _ScheduleRecurringParams(BaseModel):
    query: str = Field(description="The query or instruction to execute on each recurrence.")
    cron_expression: str = Field(
        description="A standard 5-field cron expression, e.g. '0 9 * * *' for daily at 9 AM."
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone name, e.g. 'America/New_York'. Defaults to UTC.",
    )


class _CancelScheduleParams(BaseModel):
    job_id: str = Field(description="The job ID to cancel, as returned by list_schedules.")


# ---- Business logic ----

def schedule_once(user_id: int, query: str, delay_seconds: int) -> str:
    from bot.scheduler import get_scheduler, _run_scheduled_job  # late import
    from apscheduler.triggers.date import DateTrigger

    run_time = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    logger.debug(
        "schedule_once: user=%d delay=%ds run_time=%s query=%r",
        user_id, delay_seconds, run_time.isoformat(), query,
    )
    scheduler = get_scheduler()
    job = scheduler.add_job(
        _run_scheduled_job,
        trigger=DateTrigger(run_date=run_time),
        kwargs={"user_id": user_id, "query": query},
        name=f"once:{user_id}:{query[:40]}",
    )
    logger.debug("schedule_once: job_id=%s next_run=%s", job.id, job.next_run_time)
    minutes, secs = divmod(delay_seconds, 60)
    human = f"{minutes}m {secs}s" if minutes else f"{secs}s"
    return f"Scheduled in {human} (job ID: <code>{job.id}</code>)."


def schedule_recurring(
    user_id: int, query: str, cron_expression: str, timezone: str = "UTC"
) -> str:
    from bot.scheduler import get_scheduler, _run_scheduled_job  # late import
    from apscheduler.triggers.cron import CronTrigger

    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return f"Unknown timezone '{timezone}'. Use an IANA name like 'America/New_York'."

    logger.debug(
        "schedule_recurring: user=%d cron=%r timezone=%r query=%r",
        user_id, cron_expression, timezone, query,
    )

    try:
        trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
    except ValueError as exc:
        return f"Invalid cron expression '{cron_expression}': {exc}"

    scheduler = get_scheduler()
    job = scheduler.add_job(
        _run_scheduled_job,
        trigger=trigger,
        kwargs={"user_id": user_id, "query": query},
        name=f"cron:{user_id}:{query[:40]}",
    )
    logger.debug(
        "schedule_recurring: job_id=%s next_run=%s trigger=%s",
        job.id, job.next_run_time, trigger,
    )
    return (
        f"Recurring job created (job ID: <code>{job.id}</code>).\n"
        f"Schedule: <code>{cron_expression}</code> ({timezone})"
    )


def list_schedules(user_id: int) -> str:
    from bot.scheduler import get_scheduler  # late import

    scheduler = get_scheduler()
    jobs = [j for j in scheduler.get_jobs() if j.kwargs.get("user_id") == user_id]
    if not jobs:
        return "You have no active scheduled jobs."
    lines = ["<b>Your scheduled jobs:</b>"]
    for job in jobs:
        tz_str = str(getattr(getattr(job, "trigger", None), "timezone", None) or "UTC")
        if job.next_run_time:
            next_run = f"{job.next_run_time.strftime('%Y-%m-%d %H:%M')} ({tz_str})"
        else:
            next_run = "paused"
        lines.append(
            f"• <code>{job.id}</code>\n"
            f"  Next: {next_run}\n"
            f"  Query: {job.kwargs.get('query', '?')}"
        )
    return "\n".join(lines)


def cancel_schedule(user_id: int, job_id: str) -> str:
    from bot.scheduler import get_scheduler  # late import
    from apscheduler.jobstores.base import JobLookupError

    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if job is None:
        return f"No job with ID <code>{job_id}</code> found."
    if job.kwargs.get("user_id") != user_id:
        return "You can only cancel your own scheduled jobs."
    scheduler.remove_job(job_id)
    return f"Job <code>{job_id}</code> has been cancelled."


# ---- Tool factory — called by chat.py with the current user_id ----

def make_schedule_tools(user_id: int) -> list:
    """Return AI tools with user_id pre-bound via closures."""
    facts = db.get_facts(user_id)
    user_tz = facts.get("timezone", "UTC")

    def _do_schedule_once(query: str, delay_seconds: int) -> str:
        return schedule_once(user_id, query, delay_seconds)

    def _do_schedule_recurring(
        query: str, cron_expression: str, timezone: str = "UTC"
    ) -> str:
        return schedule_recurring(user_id, query, cron_expression, timezone)

    def _do_list_schedules() -> str:
        return list_schedules(user_id)

    def _do_cancel_schedule(job_id: str) -> str:
        return cancel_schedule(user_id, job_id)

    return [
        ai_tool(
            name="schedule_once",
            description=(
                "Schedule a one-time task to run after a delay. "
                "Convert phrases like 'in 2 hours' to delay_seconds=7200."
            ),
            parameters=_ScheduleOnceParams,
            execute=_do_schedule_once,
        ),
        ai_tool(
            name="schedule_recurring",
            description=(
                "Schedule a recurring task using a cron expression. "
                f"Always pass a timezone. The user's stored timezone is '{user_tz}' — "
                "use it as the default if the user doesn't specify one. "
                "E.g. 'every evening at 8:50pm Eastern' → "
                "cron_expression='50 20 * * *', timezone='America/New_York'."
            ),
            parameters=_ScheduleRecurringParams,
            execute=_do_schedule_recurring,
        ),
        ai_tool(
            name="list_schedules",
            description="List the user's active scheduled jobs.",
            parameters={"type": "object", "properties": {}, "required": []},
            execute=_do_list_schedules,
        ),
        ai_tool(
            name="cancel_schedule",
            description="Cancel a scheduled job by its ID.",
            parameters=_CancelScheduleParams,
            execute=_do_cancel_schedule,
        ),
    ]


# ---- aiogram command handler ----

@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    user_id = message.from_user.id
    args = message.text.removeprefix("/schedule").strip()

    if not args or args == "list":
        await message.answer(list_schedules(user_id))
    elif args.startswith("cancel "):
        job_id = args.removeprefix("cancel ").strip()
        await message.answer(cancel_schedule(user_id, job_id))
    else:
        await message.answer(
            "Usage:\n"
            "• /schedule list — show your scheduled jobs\n"
            "• /schedule cancel &lt;job_id&gt; — cancel a job\n\n"
            "To create a scheduled job, just tell me in plain language:\n"
            "<i>e.g. 'Remind me to drink water in 30 minutes' or "
            "'Every morning at 9am UTC send me the weather for London'</i>"
        )
