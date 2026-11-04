"""Small reusable UI helpers. Untrusted text is always escaped or rendered as text."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from cyberlead360.domain.enums import Industry, ProspectStage
from cyberlead360.utils.normalization import country_name
from cyberlead360.utils.validators import escape_markdown, is_safe_http_url


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def money(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "—"
    symbol = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, currency + " ")
    return f"{symbol}{value:,.0f}"


def money_compact(value: float | None, currency: str = "EUR") -> str:
    """Short form for narrow metric cards: €228k, €1.2M."""
    if value is None:
        return "—"
    symbol = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, currency + " ")
    if abs(value) >= 1_000_000:
        return f"{symbol}{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{symbol}{value / 1_000:.0f}k"
    return f"{symbol}{value:,.0f}"


def dt(value: datetime | None, with_time: bool = False) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M UTC" if with_time else "%Y-%m-%d")


def industry_label(value: str | None) -> str:
    if not value:
        return "Unknown"
    try:
        return Industry(value).label
    except ValueError:
        return value


def stage_label(value: str | None) -> str:
    return ProspectStage(value).label if value else "—"


def country_label(code: str | None) -> str:
    return country_name(code)


def md(text: str | None) -> str:
    """Escape untrusted text for use inside st.markdown."""
    return escape_markdown(text or "")


def priority_pill(priority: str | None) -> str:
    """Returns static HTML built only from an enum value (safe)."""
    p = priority if priority in {"high", "medium", "low"} else "low"
    label = (priority or "unscored").capitalize()
    return f'<span class="cl-pill cl-{p}">{label}</span>'


def safe_link(label: str, url: str | None) -> None:
    if url and is_safe_http_url(url):
        st.link_button(label, url)
    elif url:
        st.caption("Link hidden: not a safe http(s) URL.")


def empty_state(message: str, hint: str | None = None) -> None:
    with st.container(border=True):
        st.markdown(f"**{message}**")
        if hint:
            st.caption(hint)


def company_selector(
    options: list[tuple[int, str]],
    key: str,
    label: str = "Company",
    default_id: int | None = None,
) -> int | None:
    """Selectbox over (id, name), remembering the choice across pages."""
    if not options:
        return None
    ids = [o[0] for o in options]
    names = {o[0]: o[1] for o in options}
    remembered = default_id or st.session_state.get("selected_company_id")
    index = ids.index(remembered) if remembered in ids else 0
    chosen = st.selectbox(
        label, ids, index=index, key=key, format_func=lambda i: f"{names[i]}  (#{i})"
    )
    st.session_state["selected_company_id"] = chosen
    return chosen
