"""Reads settings from Streamlit secrets with safe defaults.

Works outside a running Streamlit app too (tests), where secrets are empty.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from core.schema import TIMEZONE

IST = ZoneInfo(TIMEZONE)


def _secrets() -> dict:
    try:
        import streamlit as st
        return dict(st.secrets)
    except Exception:  # no secrets.toml, or not running inside Streamlit
        return {}


def get(key: str, default=None):
    return _secrets().get(key, default)


def sheet_id() -> str:
    """Accepts either `sheet_id` or a full `sheet_url` in secrets."""
    raw = str(get("sheet_id", "") or get("sheet_url", "") or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw)
    return m.group(1) if m else raw


def service_account_info() -> dict | None:
    info = get("gcp_service_account")
    if not info:
        return None
    info = dict(info)
    if not info.get("private_key") or not info.get("client_email"):
        return None
    return info


def use_google() -> bool:
    return bool(sheet_id() and service_account_info())


_SA_REQUIRED = ("type", "project_id", "private_key", "client_email", "token_uri")


def google_status() -> tuple[bool, str]:
    """(connected_config_ok, reason). Explains why the app would fall back to
    local mode, so a missing secret is never silent."""
    if not sheet_id():
        return False, "`sheet_id` is missing from the app secrets."
    info = get("gcp_service_account")
    if not info:
        return False, "The `[gcp_service_account]` section is missing from the app secrets."
    info = dict(info)
    missing = [k for k in _SA_REQUIRED if not str(info.get(k, "")).strip()]
    if missing:
        return False, "`[gcp_service_account]` is missing: " + ", ".join(missing) + "."
    if "BEGIN PRIVATE KEY" not in str(info.get("private_key", "")):
        return False, "`private_key` in `[gcp_service_account]` does not look like a key (paste it whole)."
    return True, ""


def show_spec() -> bool:
    """Origin / size are not used for now (set show_spec = true to bring them back)."""
    return bool(get("show_spec", False))


def edit_cutoff_days() -> int:
    try:
        return int(get("edit_cutoff_days", 1))
    except (TypeError, ValueError):
        return 1


def edit_cutoff_hour() -> int:
    try:
        return min(23, max(0, int(get("edit_cutoff_hour", 12))))
    except (TypeError, ValueError):
        return 12


def owner_email() -> str:
    return str(get("owner_email", "") or "").strip().lower()


def owner_initial_pin() -> str:
    return str(get("owner_initial_pin", "") or "").strip()


def pin_pepper() -> str:
    # Secret mixed into every PIN hash, so a copy of the Access tab alone is
    # not enough to guess PINs offline. Keep it stable once users exist.
    return str(get("pin_pepper", "") or "dev-only-pepper-change-me")


def master_cache_seconds() -> int:
    try:
        return max(10, int(get("master_cache_seconds", 60)))
    except (TypeError, ValueError):
        return 60


def now_ist() -> datetime:
    return datetime.now(IST).replace(microsecond=0)


def now_iso() -> str:
    return now_ist().isoformat()
