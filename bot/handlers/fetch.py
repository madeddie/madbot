"""
Web page fetcher — AI tool only (no slash command).
Fetches a URL and returns cleaned plain-text content for the AI to summarise.
"""

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from ai_sdk import tool as ai_tool
from pydantic import BaseModel, Field

_MAX_CHARS = 8000
_TIMEOUT = 15  # seconds

_SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "nav", "footer", "header", "aside", "form"}
)

_HEADERS = {
    "User-Agent": "madbot/1.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "identity",
}


class _TextExtractor(HTMLParser):
    """HTMLParser subclass that strips tags and skips noise subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        raw = "\n".join(self._parts)
        raw = re.sub(r"[^\S\n]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _fetch_webpage(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "Error: unsupported URL scheme. Only http:// and https:// are allowed."

    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            content_type = resp.headers.get_content_type()
            if content_type and not content_type.startswith("text/"):
                return (
                    f"Error: cannot extract text from non-text content "
                    f"(content-type: {content_type})."
                )
            raw_bytes = resp.read()
    except urllib.error.HTTPError as e:
        return f"Error fetching {url}: HTTP {e.code} {e.reason}"
    except urllib.error.URLError as e:
        return f"Error fetching {url}: {e.reason}"
    except UnicodeDecodeError:
        return f"Error: page at {url} returned non-text or non-UTF-8 content."
    except ValueError as e:
        return f"Error: invalid URL — {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error fetching {url}: {e}"

    html = raw_bytes.decode("utf-8", errors="replace")

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return html[:_MAX_CHARS]

    text = parser.get_text()

    if not text:
        return f"No readable text content found at {url}."

    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n[... truncated]"

    return text


class _FetchParams(BaseModel):
    url: str = Field(
        description="The full URL of the web page to fetch (must begin with http:// or https://)."
    )


AI_TOOLS = [
    ai_tool(
        name="fetch_webpage",
        description=(
            "Fetch the text content of a web page at the given URL. "
            "Returns the readable plain-text body of the page (HTML tags removed), "
            "truncated to 8000 characters. Use this to read articles, documentation, "
            "or any page the user links to, then summarise or extract information from "
            "the returned text."
        ),
        parameters=_FetchParams,
        execute=_fetch_webpage,
    )
]
