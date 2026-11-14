"""The working indent kept in st.session_state, and its autosave.

Shape of st.session_state["indent"] (also the Drafts payload):
    mode           "new" or "edit"
    indent_id      id being corrected ("" for new)
    base_version   current version when it was opened for correction
    base           {"header": {...}, "lines": [...]} of that version
    step           "delivery" or "items"
    header         IndentHeader as dict
    lines          list of IndentLine dicts
"""
from __future__ import annotations

import copy
import time

import streamlit as st

from core import changelog, drafts
from core.models import IndentHeader, IndentLine, IndentSnapshot
from core.sheets import SheetError

KEY = "indent"
THROTTLE_SECONDS = 15
WIDGET_PREFIXES = ("w_", "a_", "ed_")


def blank() -> dict:
    return {"mode": "new", "indent_id": "", "base_version": 0, "base": None, "step": "delivery",
            "created_at": "", "header": IndentHeader().to_dict(), "lines": []}


def get() -> dict:
    if KEY not in st.session_state:
        st.session_state[KEY] = blank()
    return st.session_state[KEY]


def header() -> IndentHeader:
    return IndentHeader.from_dict(get()["header"])


def set_header_field(field: str, value: str) -> None:
    get()["header"][field] = value or ""
    mark_dirty()


def lines() -> list[IndentLine]:
    return [IndentLine.from_dict(d) for d in get()["lines"]]


def set_lines(new_lines: list[IndentLine], structural: bool) -> None:
    """structural=True for add/remove (saved at once and resets the table)."""
    get()["lines"] = [line.to_dict() for line in new_lines]
    if structural:
        bump_editor()
    mark_dirty(force=structural)


def set_step(step: str) -> None:
    get()["step"] = step
    mark_dirty(force=True)


def bump_editor() -> None:
    st.session_state["editor_rev"] = st.session_state.get("editor_rev", 0) + 1


def reset_widgets() -> None:
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(WIDGET_PREFIXES):
            del st.session_state[k]
    bump_editor()


def has_work() -> bool:
    ind = get()
    return bool(ind["lines"]) or any(ind["header"].values())


def base_snapshot() -> tuple[IndentHeader, list[IndentLine]] | None:
    base = get().get("base")
    if not base:
        return None
    return IndentHeader.from_dict(base["header"]), [IndentLine.from_dict(d) for d in base["lines"]]


def changed_vs_base() -> bool:
    b = base_snapshot()
    if b is None:
        return False
    return changelog.has_changes(b[0], b[1], header(), lines())


def min_delivery_date():
    from core.indents import min_delivery_date as _min
    ind = get()
    return _min(ind.get("created_at") or None) if ind["mode"] == "edit" else _min()


def has_unsaved_work() -> bool:
    ind = get()
    if ind["mode"] == "edit":
        return changed_vs_base()
    return has_work()


# ---------------------------------------------------------------- transitions

def start_new() -> None:
    st.session_state[KEY] = blank()
    reset_widgets()
    mark_dirty(force=True)


def open_for_edit(current: IndentSnapshot, load: IndentSnapshot | None = None,
                  created_at: str = "") -> None:
    """Load an indent into the form. `load` is an older version to copy in;
    the comparison base is always the current version."""
    src = load or current
    st.session_state[KEY] = {
        "mode": "edit", "indent_id": current.indent_id, "base_version": current.version,
        "base": {"header": current.header.to_dict(), "lines": [x.to_dict() for x in current.lines]},
        "step": "items",
        "created_at": created_at,
        "header": src.header.to_dict(),
        "lines": [x.to_dict() for x in src.lines],
    }
    reset_widgets()
    mark_dirty(force=True)


# ---------------------------------------------------------------- autosave

def mark_dirty(force: bool = False) -> None:
    st.session_state["draft_dirty"] = True
    if force:
        st.session_state["draft_force"] = True


def autosave(force: bool = False) -> None:
    """Save the draft to the Drafts tab when it changed: at once for
    structural changes, otherwise at most every 15 seconds."""
    s = st.session_state
    user = s.get("user")
    if not user or not s.get("draft_dirty"):
        return
    due = force or s.get("draft_force") or time.time() - s.get("draft_saved_ts", 0) >= THROTTLE_SECONDS
    if not due:
        return
    payload = copy.deepcopy(get())
    try:
        row, stamp = drafts.save(user["email"], payload, s.get("draft_row"))
    except SheetError as e:
        s["draft_error"] = str(e)
        return
    s["draft_row"] = row
    s["draft_saved_at"] = stamp
    s["draft_saved_ts"] = time.time()
    s["draft_dirty"] = False
    s["draft_force"] = False
    s.pop("draft_error", None)


def restore_from_sheet(email: str) -> bool:
    """On sign-in: load this user's saved draft into the form, if any."""
    try:
        row, payload, updated = drafts.load(email)
    except SheetError:
        return False
    st.session_state["draft_row"] = row
    if not payload or not isinstance(payload, dict) or "header" not in payload:
        return False
    ind = blank()
    ind.update({k: payload[k] for k in ind if k in payload})
    st.session_state[KEY] = ind
    st.session_state["draft_saved_at"] = updated
    reset_widgets()
    return bool(ind["lines"]) or any(ind["header"].values())


def clear_after_submit() -> None:
    st.session_state[KEY] = blank()
    reset_widgets()
    s = st.session_state
    try:
        drafts.clear(s["user"]["email"], s.get("draft_row"))
        s["draft_saved_at"] = None
    except SheetError as e:
        s["draft_error"] = str(e)
    s["draft_dirty"] = False
    s["draft_force"] = False
