"""Indent screen: delivery details, then items. Autosaves the draft."""
from __future__ import annotations

import streamlit as st

from core import masters
from core.auth import User
from core.sheets import SheetError
from pages_src import common, delivery, indent_actions, items, state


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
    """Indent page: delivery choices (pills) on top, items right below."""
    common.show_flash()
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "Master data could not be loaded.")
        return

    gone = state.drop_closed_edit()
    if gone:
        st.info(f"The open edit of {gone} was cleared: its edit time has closed. Start a new indent below.")
    ind = state.get()
    top = st.columns([4, 1.4], vertical_alignment="bottom")
    if ind["mode"] == "edit":
        top[0].markdown(f"### Correct indent {ind['indent_id']}")
        top[0].caption(f"Editing on top of version {ind['base_version']}. "
                       "Saving creates a new version; the old one stays in the sheet.")
    else:
        top[0].markdown("### Create indent")
        top[0].caption("Pick the delivery day, customer and store, then add the items.")
    with top[1]:
        _autosave_tick()

    ready = delivery.render(m)
    if ready:
        items.render(m, user)
    elif ind["mode"] == "edit":
        c = st.columns([1, 3])
        if c[0].button("Discard changes", icon=":material/close:"):
            st.session_state["pending_action"] = "discard"
        items.dialogs_only(m, user)
    state.autosave()
    indent_actions.show_dialog(user)
