"""Indent screen: delivery details, then items. Autosaves the draft."""
from __future__ import annotations

import streamlit as st

from datetime import date

from core import config, indents, masters
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


def _fmt_d(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%a, %d %b")
    except ValueError:
        return iso


def _open(indent_id: str) -> None:
    df = indents.read_lines(fresh=True)
    cur = indents.snapshot(df, indent_id)
    if cur is not None:
        state.open_for_edit(cur, None, created_at=indents.created_at(df, indent_id))
        common.flash("info", f"{indent_id} opened for editing. Change what you need, then press Update indent.")


@st.dialog("Replace the form?", dismissible=False)
def _confirm_open(indent_id: str) -> None:
    st.write(f"You have unsaved entries on this page. Opening **{indent_id}** will replace them.")
    c = st.columns(2)
    if c[0].button("Open " + indent_id, type="primary", width="stretch"):
        st.session_state.pop("home_open", None)
        _open(indent_id)
        st.rerun()
    if c[1].button("Cancel", width="stretch"):
        st.session_state.pop("home_open", None)
        st.rerun()


def _placed(user: User) -> None:
    """Home screen: indents already placed for today onwards (customer, store, date)."""
    try:
        df = indents.read_lines()
    except SheetError:
        return
    summ = indents.summary(df)
    summ = indents.visible_to(summ, user)
    today = config.now_ist().date().isoformat()
    up = indents.open_first(summ[summ["delivery_date"].astype(str) >= today],
                            then=["delivery_date", "customer", "store"], ascending=[True, True, True])
    if up.empty:
        return
    up = up[up["status"] != "Cancelled"]
    if up.empty:
        return
    ind = state.get()
    label = f"Indents placed · {len(up)} upcoming" + (f" · {', '.join(user.cities)}" if user.city_scoped else "")
    with st.expander(label, expanded=True, icon=":material/inventory_2:"):
        w = [1.0, 0.9, 2.0, 1.8, 0.5, 0.9, 0.8, 0.8, 0.9, 1.05]
        head = st.columns(w)
        for col, label in zip(head, ["Delivery", "Customer", "Store", "Indent", "Items", "Amount",
                                     "Status", "", "", ""]):
            col.markdown(f"<span class='mt-muted'>{label}</span>", unsafe_allow_html=True)
        for r in up.head(30).itertuples():
            c = st.columns(w, vertical_alignment="center")
            c[0].write(_fmt_d(r.delivery_date))
            c[1].write(r.customer)
            c[2].write(r.store)
            c[3].write(r.indent_id)
            c[4].write(str(r.lines))
            c[5].markdown(f"<span class='num'>₹ {r.total_amount:,.0f}</span>", unsafe_allow_html=True)
            c[6].markdown(common.badge(r.status), unsafe_allow_html=True)
            editing = ind["mode"] == "edit" and ind["indent_id"] == r.indent_id
            ok = bool(r.can_edit)
            frozen = r.status == "Frozen"
            why = "Frozen with a PO" if frozen else "Edit window closed"
            if c[7].button("Editing" if editing else "Edit", icon=":material/edit:",
                           key=f"home_{r.indent_id}", disabled=editing or not ok, width="stretch",
                           help="Open this indent to change it" if ok else why):
                if state.has_unsaved_work():
                    st.session_state["home_open"] = r.indent_id
                else:
                    _open(r.indent_id)
                st.rerun()
            if c[8].button("Delete", icon=":material/delete:", key=f"homedel_{r.indent_id}",
                           disabled=not ok, width="stretch",
                           help="Delete this indent (asks first)" if ok else why):
                indent_actions.ask("delete", r.indent_id)
            if c[9].button("PO" if not frozen else "PO done", icon=":material/upload_file:",
                           key=f"homepo_{r.indent_id}", disabled=frozen, width="stretch",
                           help="Upload the customer's PO (PDF) and freeze this indent"
                           if not frozen else "PO already uploaded"):
                indent_actions.ask("po", r.indent_id)
        if len(up) > 30:
            st.caption(f"Showing 30 of {len(up)}. See All indents for the rest.")
    if st.session_state.get("home_open"):
        _confirm_open(st.session_state["home_open"])
    else:
        indent_actions.show_dialog(user)


def render(user: User) -> None:
    common.show_flash()
    _placed(user)
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
