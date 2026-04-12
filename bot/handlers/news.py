"""
News headlines fetcher — AI tool only (no slash command).
Scrapes AP News and Reuters frontpages and returns the top 5 headlines from each.
"""

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from ai_sdk import tool as ai_tool

_TIMEOUT = 15  # seconds

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})
_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "nav", "footer", "header", "aside", "form"}
)

_MIN_LEN = 20
_MAX_LEN = 250

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",
}

_SOURCES = [
    ("AP News", "https://apnews.com"),
    ("Reuters", "https://www.reuters.com"),
]


class _HeadingsExtractor(HTMLParser):
    """HTMLParser subclass that extracts text from h1–h4 tags, skipping noise subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._headings: list[str] = []
        self._in_heading: bool = False
        self._current: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth == 0 and tag in _HEADING_TAGS:
            self._in_heading = True
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in _HEADING_TAGS and self._in_heading:
            self._in_heading = False
            text = re.sub(r"\s+", " ", " ".join(self._current)).strip()
            if _MIN_LEN <= len(text) <= _MAX_LEN:
                self._headings.append(text)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and self._in_heading:
            stripped = data.strip()
            if stripped:
                self._current.append(stripped)


def _fetch_headlines(url: str, limit: int = 5) -> list[str]:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw_bytes = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, Exception):
        return []

    html = raw_bytes.decode("utf-8", errors="replace")
    parser = _HeadingsExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []

    seen: set[str] = set()
    unique: list[str] = []
    for heading in parser._headings:
        lo = heading.lower()
        if lo not in seen:
            seen.add(lo)
            unique.append(heading)
        if len(unique) >= limit:
            break
    return unique


def _get_news_headlines() -> str:
    sections: list[str] = []
    for source_name, url in _SOURCES:
        headlines = _fetch_headlines(url, limit=5)
        if headlines:
            lines = [f"**{source_name}:**"]
            for i, h in enumerate(headlines, 1):
                lines.append(f"{i}. {h}")
            sections.append("\n".join(lines))
        else:
            sections.append(f"**{source_name}:** (headlines unavailable)")
    return "\n\n".join(sections) if sections else "Could not fetch headlines from any source."


AI_TOOLS = [
    ai_tool(
        name="get_news_headlines",
        description=(
            "Fetch the top 5 news headlines from AP News and Reuters frontpages. "
            "Returns a numbered list of today's top stories from each source. "
            "Use this for the news section of the daily briefing."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        execute=_get_news_headlines,
    )
]
