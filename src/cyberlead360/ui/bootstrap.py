"""Streamlit glue: cached database, page setup and safe action execution.

Pages call ``page_setup()`` first, then use ``db().session()`` for reads and
``run_action()`` for writes. Business logic stays in the services.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import streamlit as st
from pydantic import ValidationError
from sqlalchemy.orm import Session

from cyberlead360.config.logging import configure_logging, get_logger
from cyberlead360.config.settings import Settings, get_settings
from cyberlead360.database.session import Database
from cyberlead360.domain.exceptions import CyberLeadError
from cyberlead360.integrations.llm.base import LLMProvider
from cyberlead360.integrations.llm.factory import build_provider
from cyberlead360.ui.theme import inject_css

T = TypeVar("T")
log = get_logger("ui")


@st.cache_resource(show_spinner="Preparing database…")
def _database() -> Database:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    database = Database(settings)
    database.ensure_schema()
    from cyberlead360.services.scoring_service import ScoringService

    with database.session() as s:
        ScoringService(s, settings.operator_name).ensure_default_rules()
    return database


@st.cache_resource
def _provider() -> LLMProvider | None:
    return build_provider(get_settings())


def db() -> Database:
    return _database()


def settings() -> Settings:
    return get_settings()


def llm_provider() -> LLMProvider | None:
    return _provider()


def actor() -> str:
    return get_settings().operator_name


def page_setup(title: str, icon: str, wide: bool = True) -> None:
    st.set_page_config(
        page_title=f"{title} · CyberLead 360",
        page_icon=icon,
        layout="wide" if wide else "centered",
        initial_sidebar_state="expanded",
    )
    inject_css()
    try:
        db()
    except Exception as exc:  # pragma: no cover - surfaced in UI
        log.exception("database initialization failed")
        st.error(f"Database initialization failed: {type(exc).__name__}. See the server logs.")
        st.stop()
    with st.sidebar:
        st.markdown("### 🛡️ CyberLead 360")
        st.caption("Cybersecurity B2B sales intelligence")
        mode = (
            "LLM: " + (settings().active_model or "")
            if llm_provider()
            else "Template mode (no API key)"
        )
        st.caption(f"AI · {mode}")
        st.caption(f"Operator · {actor()} (single-user demo)")
    st.title(title)


def format_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "input"
        parts.append(f"• {field}: {err['msg'].removeprefix('Value error, ')}")
    return "Please correct the following:\n\n" + "\n".join(parts)


def run_action[T](
    fn: Callable[[Session], T], success: str | None = None, *, rerun: bool = False
) -> T | None:
    """Execute a write in one transaction and report the outcome in the UI."""
    try:
        with db().session() as s:
            result = fn(s)
    except ValidationError as exc:
        st.error(format_validation_error(exc))
        return None
    except CyberLeadError as exc:
        st.error(str(exc))
        return None
    except ValueError as exc:
        st.error(str(exc))
        return None
    except Exception:
        log.exception("unexpected error during action")
        st.error("Unexpected error. The operation was rolled back; see the server logs.")
        return None
    if success:
        st.toast(success, icon="✅")
    if rerun:
        st.session_state["_flash"] = success
        st.rerun()
    return result


def flash() -> None:
    """Show a success message stored before an ``st.rerun()``."""
    message = st.session_state.pop("_flash", None)
    if message:
        st.success(message)
