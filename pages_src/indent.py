"""Indent screen: delivery details, then items. Autosaves the draft."""
from __future__ import annotations

import streamlit as st

from core import masters
from core.auth import User
from core.sheets import SheetError
from pages_src import common, delivery, items, state


@st.fragment(run_every=state.THROTTLE_SECONDS)
def _autosave_tick() -> None:
    """Flushes throttled qty/price edits even when the user stops clicking."""
    state.autosave()
    saved = st.session_state.get("draft_saved_at")
    err = st.session_state.get("draft_error")
    if err:
        st.caption(f"⚠️ Draft not saved to the sheet: {err}")
    elif saved:
        st.caption(f"Autosaved {saved[11:19]}")


def render(user: User) -> None:
    common.show_flash()
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "Master data could not be loaded.")
        return

    ind = state.get()
    top = st.columns([4, 1.4])
    if ind["mode"] == "edit":
        top[0].markdown(f"### Correct indent {ind['indent_id']}")
        top[0].caption(f"Editing on top of version {ind['base_version']}. "
                       "Saving creates a new version; the old one stays in the sheet.")
    else:
        top[0].markdown("### New indent")
    step = ind["step"]
    top[0].caption(("**① Delivery** → ② Items" if step == "delivery" else "① Delivery → **② Items**"))
    with top[1]:
        _autosave_tick()

    if step == "items" and state.header().is_complete():
        items.render(m, user)
    else:
        if step == "items":  # header incomplete (e.g. restored draft): go back
            ind["step"] = "delivery"
        delivery.render(m)

    state.autosave()
