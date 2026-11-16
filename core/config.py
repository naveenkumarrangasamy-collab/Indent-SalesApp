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
    conn = dict(get("connections") or {}).get("gsheets") or {}
    raw = str(get("sheet_id", "") or get("sheet_url", "") or dict(conn).get("spreadsheet", "") or "").strip()
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", raw)
    return m.group(1) if m else raw


def _raw_service_account() -> tuple[dict | None, str]:
    """The service account from the secrets, in any of three forms:
    1. gcp_service_account_json = the whole JSON key file pasted as text
    2. [gcp_service_account] with one line per field
    3. [connections.gsheets] (the st-gsheets-connection layout)
    Returns (info or None, error text)."""
    import json

    raw = get("gcp_service_account_json")
    if raw:
        try:
            info = json.loads(str(raw))
        except json.JSONDecodeError as e:
            return None, ("`gcp_service_account_json` is not valid JSON (line "
                          f"{e.lineno}). Paste the whole key file between the triple quotes.")
        return (info if isinstance(info, dict) else None), ""
    info = get("gcp_service_account")
    if info:
        return dict(info), ""
    conn = (get("connections") or {})
    gs = dict(conn).get("gsheets") if conn else None
    if gs:
        return {k: v for k, v in dict(gs).items() if k not in ("spreadsheet", "worksheet")}, ""
    return None, ""


def service_account_info() -> dict | None:
    info, _ = _raw_service_account()
    if not info or not info.get("private_key") or not info.get("client_email"):
        return None
    return info


_SA_REQUIRED = ("type", "project_id", "private_key", "client_email", "token_uri")


def google_status() -> tuple[bool, str]:
    """(connected_config_ok, reason). Explains why the app would fall back to
    local mode, so a missing secret is never silent."""
    if not sheet_id():
        return False, "`sheet_id` is missing from the app secrets."
    info, err = _raw_service_account()
    if err:
        return False, err
    if not info:
        return False, ("The service account key is missing from the app secrets "
                       "(add `gcp_service_account_json` with the key file, see README).")
    missing = [k for k in _SA_REQUIRED if not str(info.get(k, "")).strip()]
    if missing:
        return False, "The service account key is missing: " + ", ".join(missing) + "."
    if "BEGIN PRIVATE KEY" not in str(info.get("private_key", "")):
        return False, "`private_key` in the service account key does not look like a key (paste it whole)."
    return True, ""


def secret_names() -> list[str]:
    """Names (never values) of the top-level secrets, to help fix setup."""
    return sorted(_secrets().keys())


DEFAULT_APPLE_VARIETIES = ["Gala", "Granny Smith", "Queen", "RD", "Pink Lady", "Crispy Pink",
                           "Braeburn", "Sonya", "Fuji", "Jazz"]


def variety_parents() -> list[str]:
    """Only these parent SKUs ask for a variety (default: Apple)."""
    v = get("variety_parents", ["Apple"])
    return [str(x) for x in (v if isinstance(v, (list, tuple)) else [v])]


def delivery_days_ahead() -> int:
    """Latest delivery date = today + this many days (default 1: T and T+1)."""
    try:
        return max(0, int(get("delivery_days_ahead", 1)))
    except (TypeError, ValueError):
        return 1


def delivery_window() -> tuple[str, str]:
    """Earliest and latest expected delivery time (HH:MM), default 10 AM-8 PM."""
    return str(get("delivery_from", "10:00")), str(get("delivery_to", "20:00"))


def po_drive_folder_id() -> str:
    """Google Drive folder (in a Shared drive) where uploaded PO PDFs are kept.
    Empty: only the file name is recorded."""
    raw = str(get("po_drive_folder_id", "") or "").strip()
    import re as _re
    m = _re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    return m.group(1) if m else raw


def show_spec() -> bool:
    """Origin / size are not used for now (set show_spec = true to bring them back)."""
    return bool(get("show_spec", False))


def edit_cutoff_days() -> int:
    """Days after the DELIVERY date on which editing closes (0 = on the delivery date)."""
    try:
        return int(get("edit_cutoff_days", 0))
    except (TypeError, ValueError):
        return 0


def edit_cutoff_hour() -> int:
    try:
        return min(23, max(0, int(get("edit_cutoff_hour", 14))))
    except (TypeError, ValueError):
        return 14


def owner_email() -> str:
    return str(get("owner_email", "") or "").strip().lower()


def owner_initial_pin() -> str:
    return str(get("owner_initial_pin", "") or "").strip()


def pin_pepper() -> str:
    # Secret mixed into every PIN hash, so a copy of the Access tab alone is
    # not enough to guess PINs offline. Keep it stable once users exist.
    return str(get("pin_pepper", "") or "dev-only-pepper-change-me")


def master_cache_seconds() -> int:
    """How long Google Sheet master data (SKUs, stores, varieties, access) is
    kept before it is read again: `master_refresh_minutes` (default 5)."""
    try:
        return max(60, int(float(get("master_refresh_minutes", 5)) * 60))
    except (TypeError, ValueError):
        return 300


def session_hours() -> int:
    """How long a sign-in lasts (refresh / closing the tab keeps you in); after
    that the PIN is asked again. `session_hours` (default 24); an old
    `session_days` setting still works."""
    try:
        if get("session_hours", None) not in (None, ""):
            return max(1, int(float(get("session_hours"))))
        if get("session_days", None) not in (None, ""):
            return max(1, int(float(get("session_days")))) * 24
    except (TypeError, ValueError):
        pass
    return 24


def now_ist() -> datetime:
    return datetime.now(IST).replace(microsecond=0)


def now_iso() -> str:
    return now_ist().isoformat()
