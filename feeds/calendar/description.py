"""Calendar descriptions as plain text. Google Calendar writes the description of an event edited in its web app as
HTML into the ICS feed, which Discord shows as is; plain text is left alone."""

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

# A description with one of the tags Google Calendar writes is HTML; "a < b" or "<name>" in plain text is not
_TAG = re.compile(
    r"</?(?:a|b|i|u|s|br|p|div|span|strong|em|ul|ol|li|h[1-6]|table|tr|td|html-blob)(?:\s[^<>]*)?/?>", re.IGNORECASE
)
# Tags that start and end on a line of their own; <br> and <li> are handled apart
_BLOCKS = {"p", "div", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr"}


def plain_text(description: str) -> str:
    """`description` with its HTML turned into plain text: line breaks kept, links written as their URL (or as
    "text (URL)" when the text differs), other tags dropped and entities decoded."""
    if not _TAG.search(description):
        return description

    parser = _PlainText()
    parser.feed(description)
    parser.close()
    lines = [re.sub(" {2,}", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        # The URL of the link being read and where its text starts in `parts`
        self._link: tuple[str, int] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCKS:
            self.parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href")
            self._link = None if not href else (_unwrapped(href), len(self.parts))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCKS:
            self.parts.append("\n")
        elif tag == "a" and self._link is not None:
            url, start = self._link
            self._link = None
            text = "".join(self.parts[start:]).strip()
            del self.parts[start:]
            self.parts.append(url if _same(text, url) else f"{text} ({url})")

    def handle_data(self, data: str) -> None:
        # Whitespace in HTML is no line break, that is what the tags above are for (&nbsp; becomes a space too)
        self.parts.append(re.sub(r"\s+", " ", data))


def _unwrapped(href: str) -> str:
    """The real URL of a link Google rewrote to go through google.com/url?q=<URL>."""
    parsed = urlparse(href)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q")
        if target:
            return target[0]
    return href


def _same(text: str, url: str) -> bool:
    """Whether the link text is the URL itself, maybe without its scheme or trailing slash."""

    def bare(link: str) -> str:
        return re.sub(r"^[a-z]+://", "", link.strip(), flags=re.IGNORECASE).rstrip("/")

    return not text or bare(text) == bare(url)
