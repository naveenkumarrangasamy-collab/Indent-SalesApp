"""Page 1: sign in with work email and PIN."""
from __future__ import annotations

import streamlit as st

from core import auth, masters
from core.schema import ACCESS_ACTIVE, ROLE_OWNER_FULL
from core.sheets import SheetError
from pages_src import common, state


def render() -> None:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("## MT Indent")
        st.caption("MT Direct Sales · sales-order indents")
        common.show_flash()
        with st.form("login"):
            email = st.text_input("Work email", placeholder="name@company.com")
            pin = st.text_input("PIN", type="password", max_chars=6, placeholder="4–6 digits")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            _do_login(email, pin)
        st.caption("Forgot your PIN or need access? Ask the indent owner to set one for you.")
        with st.expander("Admin: how to give someone access"):
            st.markdown(
                "1. Sign in with the **owner email** (the `owner_email` in the app secrets). "
                "The first time, use the `owner_initial_pin`, then set your own PIN in the "
                "sidebar under **Change my PIN**.\n"
                "2. Open **🔑 Access** in the left sidebar (only the owner sees it).\n"
                "3. Under **Add a user**, enter their work email, name, role (**sales**, or "
                "**owner** for another admin) and a 4–6 digit PIN, then press **Add user**.\n"
                "4. Send them the app link, their email and the PIN privately. They can change "
                "the PIN after signing in.\n"
                "5. To block someone, open **Manage a user** on the same page and press "
                "**Revoke access**; **Reset PIN** sets a new PIN if they forget it.")


def _do_login(email: str, pin: str) -> None:
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e, "Cannot sign in right now.")
        return
    res = auth.authenticate(m.access, email, pin)
    if res.user is None:
        st.error(res.message)
        return
    user = res.user
    if res.used_initial_pin:
        # First owner sign-in: record the owner in the Access tab with this PIN.
        try:
            auth.upsert_access(user.email, by=user.email, role=ROLE_OWNER_FULL,
                               status=ACCESS_ACTIVE, pin=pin)
            masters.clear_cache()
        except SheetError:
            pass
        st.session_state["must_change_pin"] = True
    common.sign_in(user)
    common.remember_login(user)
    state.restore_from_sheet(user.email)   # any unsaved draft is back on Create indent
    st.rerun()
