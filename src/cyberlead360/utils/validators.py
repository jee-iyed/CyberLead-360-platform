"""Validation and sanitization helpers for untrusted input and output."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKDOWN_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]<>()#+\-.!|~$])")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def strip_control_chars(value: str) -> str:
    return _CONTROL_CHARS_RE.sub("", value)


def clean_text(value: str | None, max_length: int | None = None) -> str | None:
    """Trim, remove control characters and optionally truncate. Empty -> None."""
    if value is None:
        return None
    text = strip_control_chars(str(value)).strip()
    if not text:
        return None
    if max_length is not None and len(text) > max_length:
        text = text[:max_length].rstrip()
    return text


def is_safe_http_url(url: str | None) -> bool:
    """True if ``url`` is an absolute http(s) URL with a host and no credentials."""
    if not url:
        return False
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return (
        parts.scheme in {"http", "https"}
        and bool(parts.hostname)
        and not parts.username
        and not parts.password
    )


def escape_markdown(text: str) -> str:
    """Escape Markdown/HTML-significant characters so untrusted text renders literally."""
    return _MARKDOWN_SPECIAL_RE.sub(r"\\\1", text)


def neutralize_csv_formula(value: object) -> object:
    """Prevent CSV/Excel formula injection by prefixing risky strings with a quote."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value
