import asyncio
import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai_sdk import tool as ai_tool
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from pydantic import BaseModel, Field

from bot.config import settings

router = Router()
COMMANDS = {"github": "Show latest releases from your starred GitHub repos"}

_GH_API = "https://api.github.com"
_MAX_MSG = 4096


def _gh_headers() -> dict:
    h = {
        "User-Agent": "madbot/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _gh_get(path: str) -> dict | list | None:
    req = Request(f"{_GH_API}{path}", headers=_gh_headers())
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError):
        return None


def _get_starred_repos(limit: int = 30) -> list[dict]:
    repos: list[dict] = []
    page = 1
    per_page = min(limit, 30)
    while len(repos) < limit:
        chunk = _gh_get(f"/user/starred?per_page={per_page}&page={page}&sort=created&direction=desc")
        if not chunk or not isinstance(chunk, list):
            break
        repos.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1
    return repos[:limit]


def _get_latest_release(owner: str, repo: str) -> dict | None:
    return _gh_get(f"/repos/{owner}/{repo}/releases/latest")


def _format_release_body(body: str, max_chars: int = 300) -> str:
    if not body:
        return ""
    text = re.sub(r"^#{1,6}\s+.*$", "", body, flags=re.MULTILINE)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = " ".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"
    return text


def _format_entry(repo: dict, release: dict, published_dt: datetime) -> str:
    owner = repo["owner"]["login"]
    name = repo["name"]
    description = html.escape(repo.get("description") or "")
    tag = html.escape(release.get("tag_name") or "")
    date_str = published_dt.strftime("%b %-d %Y")
    release_url = release.get("html_url") or f"https://github.com/{owner}/{name}/releases"
    body_snippet = html.escape(_format_release_body(release.get("body") or ""))

    lines = [f"<b>{html.escape(owner)}/{html.escape(name)}</b>"]
    if description:
        lines[0] += f" — {description}"
    lines.append(f"🏷 {tag} · {date_str}")
    if body_snippet:
        lines.append(body_snippet)
    lines.append(release_url)
    return "\n".join(lines)


def _get_starred_releases(limit: int = 10, days: int = 90) -> str:
    if not settings.github_token:
        return (
            "GitHub token is not configured. "
            "Set GITHUB_TOKEN in your .env file (needs read:user scope) to use this feature."
        )

    repos = _get_starred_repos(30)
    if not repos:
        return "Could not fetch starred repos — check your GitHub token or connectivity."

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries: list[tuple[datetime, str]] = []

    for repo in repos:
        if len(entries) >= limit:
            break
        owner = repo["owner"]["login"]
        name = repo["name"]
        release = _get_latest_release(owner, name)
        if release is None:
            continue
        if release.get("draft") or release.get("prerelease"):
            continue
        published_str = release.get("published_at", "")
        try:
            published_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if published_dt < cutoff:
            continue
        entries.append((published_dt, _format_entry(repo, release, published_dt)))

    if not entries:
        return f"No releases found in the last {days} days across your {len(repos)} most recently starred repos."

    entries.sort(key=lambda x: x[0], reverse=True)
    header = f"<b>GitHub releases — last {days} days</b> ({len(entries)} found)\n"
    return header + "\n\n".join(text for _, text in entries)


def _chunk(text: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = (current + "\n\n" + paragraph).lstrip("\n") if current else paragraph
        if len(candidate) <= _MAX_MSG:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(paragraph) > _MAX_MSG:
                chunks.append(paragraph[:_MAX_MSG])
                paragraph = paragraph[_MAX_MSG:]
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


class _Params(BaseModel):
    limit: int = Field(default=10, ge=1, le=30, description="Max repos with releases to show.")
    days: int = Field(default=90, ge=1, le=365, description="Only show releases published within this many days.")


AI_TOOLS = [
    ai_tool(
        name="get_starred_repos_releases",
        description=(
            "Fetch the latest release for each of the user's starred GitHub repos. "
            "Returns release names, dates, and changelog snippets for repos with a new "
            "release within the requested timeframe. Use when the user asks what's new "
            "in their starred repos, wants a GitHub release digest, or asks about software updates."
        ),
        parameters=_Params,
        execute=_get_starred_releases,
    )
]


@router.message(Command("github"))
async def cmd_github(message: Message) -> None:
    await message.answer("Fetching latest releases from your starred GitHub repos…")
    result = await asyncio.to_thread(_get_starred_releases)
    for chunk in _chunk(result):
        await message.answer(chunk)
