"""
DuckDuckGo web search — AI tool only (no slash command).
Scrapes https://html.duckduckgo.com/html, no API key required.
"""

import re
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from ai_sdk import tool as ai_tool
from pydantic import BaseModel, Field

_DDG_ENDPOINT = "https://html.duckduckgo.com/html"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&apos;": "'", "&#39;": "'", "&#x27;": "'", "&#x2F;": "/",
    "&nbsp;": " ", "&ndash;": "-", "&mdash;": "--", "&hellip;": "...",
}

_ENTITY_RE = re.compile(
    "|".join(re.escape(k) for k in _HTML_ENTITIES) + r"|&#(\d+);|&#x([0-9a-fA-F]+);"
)


def _decode_entities(text: str) -> str:
    def replace(m: re.Match) -> str:
        if m.group(0) in _HTML_ENTITIES:
            return _HTML_ENTITIES[m.group(0)]
        if m.group(1):
            return chr(int(m.group(1)))
        return chr(int(m.group(2), 16))
    return _ENTITY_RE.sub(replace, text)


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _decode_ddg_url(raw: str) -> str:
    """Extract real URL from DuckDuckGo redirect links."""
    try:
        normalized = f"https:{raw}" if raw.startswith("//") else raw
        parsed = urlparse(normalized)
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return uddg[0]
    except Exception:
        pass
    return raw


def _is_bot_challenge(html: str) -> bool:
    if re.search(r'class="[^"]*\bresult__a\b[^"]*"', html, re.I):
        return False
    return bool(re.search(r'g-recaptcha|are you a human|id="challenge-form"|name="challenge"', html, re.I))


def _parse_ddg_html(html: str, count: int) -> list[dict]:
    results = []
    title_re = re.compile(
        r'<a\b(?=[^>]*\bclass="[^"]*\bresult__a\b[^"]*")([^>]*)>([\s\S]*?)<\/a>', re.I
    )
    snippet_re = re.compile(
        r'<a\b(?=[^>]*\bclass="[^"]*\bresult__snippet\b[^"]*")[^>]*>([\s\S]*?)<\/a>', re.I
    )
    next_title_re = re.compile(r'<a\b(?=[^>]*\bclass="[^"]*\bresult__a\b[^"]*")[^>]*>', re.I)

    for m in title_re.finditer(html):
        if len(results) >= count:
            break
        attrs = m.group(1)
        raw_title = m.group(2)
        href_m = re.search(r'\bhref="([^"]*)"', attrs, re.I)
        if not href_m:
            continue
        raw_url = href_m.group(1)
        # Find the snippet between this result__a and the next one
        tail = html[m.end():]
        next_m = next_title_re.search(tail)
        scope = tail[: next_m.start()] if next_m else tail
        snip_m = snippet_re.search(scope)
        raw_snippet = snip_m.group(1) if snip_m else ""

        title = _decode_entities(_strip_tags(raw_title))
        url = _decode_ddg_url(_decode_entities(raw_url))
        snippet = _decode_entities(_strip_tags(raw_snippet))
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})

    return results


class _SearchParams(BaseModel):
    query: str = Field(description="Search query string.")
    count: int = Field(default=5, ge=1, le=10, description="Number of results to return (1–10).")


def _search(query: str, count: int = 5) -> str:
    params = urlencode({"q": query, "kp": "-1"})  # kp=-1 = moderate safe search
    req = Request(
        f"{_DDG_ENDPOINT}?{params}",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8")
    except URLError as e:
        return f"Web search failed: {e.reason}"

    if _is_bot_challenge(html):
        return "Web search unavailable: DuckDuckGo returned a bot-detection challenge."

    results = _parse_ddg_html(html, count)
    if not results:
        return f"No results found for: {query}"

    lines = [f'Results for "{query}":']
    for i, r in enumerate(results, 1):
        lines.append(f'\n{i}. {r["title"]}\n   {r["url"]}')
        if r["snippet"]:
            lines.append(f'   {r["snippet"]}')

    return "\n".join(lines)


AI_TOOLS = [
    ai_tool(
        name="web_search",
        description=(
            "Search the web using DuckDuckGo. Returns titles, URLs, and snippets. "
            "Use this to find current information, news, documentation, or anything "
            "that may not be in your training data."
        ),
        parameters=_SearchParams,
        execute=_search,
    )
]
