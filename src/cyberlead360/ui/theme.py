"""Static CSS for a restrained B2B look. Contains no user data (safe to inject)."""

from __future__ import annotations

import streamlit as st

NAVY = "#0B1220"
BLUE = "#2563EB"
CYAN = "#06B6D4"
GREEN = "#16A34A"
AMBER = "#F59E0B"
RED = "#DC2626"
SLATE = "#64748B"
LIGHT = "#F8FAFC"

PRIORITY_COLORS = {"high": GREEN, "medium": AMBER, "low": SLATE}
CHART_SEQUENCE = [BLUE, CYAN, "#7C3AED", GREEN, AMBER, "#0EA5E9", "#DB2777", SLATE]

_CSS = f"""
<style>
  .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1400px; }}
  [data-testid="stSidebar"] {{ background: {NAVY}; }}
  [data-testid="stSidebar"] * {{ color: #E2E8F0 !important; }}
  [data-testid="stSidebar"] a[aria-current="page"] {{
      background: rgba(37,99,235,.35); border-radius: 6px; }}
  h1 {{ font-size: 1.75rem !important; font-weight: 700 !important; color: {NAVY}; }}
  h2, h3 {{ color: {NAVY}; }}
  [data-testid="stMetric"] {{
      background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px;
      padding: .75rem 1rem; box-shadow: 0 1px 2px rgba(15,23,42,.04);
  }}
  [data-testid="stMetricLabel"] p {{ color: {SLATE}; font-size: .8rem; text-transform: uppercase;
      letter-spacing: .03em; }}
  .cl-pill {{ display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem;
      font-weight: 600; border: 1px solid transparent; }}
  .cl-high {{ background:#DCFCE7; color:#166534; }}
  .cl-medium {{ background:#FEF3C7; color:#92400E; }}
  .cl-low {{ background:#F1F5F9; color:#334155; }}
  .cl-muted {{ color:{SLATE}; font-size:.85rem; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)  # static, trusted string only
