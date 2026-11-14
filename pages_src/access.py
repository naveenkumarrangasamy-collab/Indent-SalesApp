"""Owner only: who can sign in, PINs, sheet setup and master-data checks."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import auth, config, importer, masters
from core.auth import User
from core.schema import ACCESS_ACTIVE, ACCESS_REVOKED, ROLE_OWNER, ROLE_SALES, TABS
from core.sheets import SheetError, get_backend
from pages_src import common


def render(user: User) -> None:
    common.show_flash()
    if not user.is_owner:
        st.error("Only the indent owner can open this page.")
        return
    st.markdown("### Access")
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e)
        m = None

    t_users, t_setup = st.tabs(["Users & PINs", "Sheet setup & checks"])
    with t_users:
        if m is not None:
            _users(m, user)
    with t_setup:
        _setup(m, user)


# ------------------------------------------------------------------ users

def _users(m: masters.Masters, me: User) -> None:
    acc = m.access
    if not acc.empty:
        show = pd.DataFrame({"Email": acc["Email"], "Name": acc["Name"], "Role": acc["Role"],
                             "Status": acc["Status"],
                             "PIN set": acc["PIN_Hash"].map(lambda v: "yes" if v else "no"),
                             "Updated": acc["Updated_At"].str[:16].str.replace("T", " "),
                             "By": acc["Updated_By"]})
        st.dataframe(show, hide_index=True, width="stretch")
    else:
        st.info("No users yet. Add the first sales user below.")

    c1, c2 = st.columns(2)
    with c1, st.form("add_user", clear_on_submit=True):
        st.markdown("**Add a user**")
        email = st.text_input("Work email")
        name = st.text_input("Name")
        role = st.selectbox("Role", [ROLE_SALES, ROLE_OWNER])
        pin = st.text_input("Initial PIN (4–6 digits)", type="password", max_chars=6)
        if st.form_submit_button("Add user", type="primary"):
            email_n = auth.norm_email(email)
            if not auth.valid_email(email_n):
                st.error("Enter a valid email.")
            elif auth.access_row(acc, email_n) is not None:
                st.error("This email is already in the list. Use 'Manage a user'.")
            elif not auth.valid_pin(pin):
                st.error("PIN must be 4 to 6 digits.")
            else:
                _save(lambda: auth.upsert_access(email_n, by=me.email, name=name, role=role,
                                                 status=ACCESS_ACTIVE, pin=pin),
                      f"{email_n} added. Share the PIN with them privately.")

    with c2:
        st.markdown("**Manage a user**")
        emails = list(acc["Email"]) if not acc.empty else []
        if not emails:
            st.caption("Nobody to manage yet.")
            return
        target = st.selectbox("User", emails, key="acc_target")
        row = auth.access_row(acc, target)
        is_secret_owner = auth.norm_email(target) == config.owner_email()
        with st.form("reset_pin", clear_on_submit=True):
            new_pin = st.text_input("New PIN for this user", type="password", max_chars=6)
            if st.form_submit_button("Reset PIN"):
                if not auth.valid_pin(new_pin):
                    st.error("PIN must be 4 to 6 digits.")
                else:
                    _save(lambda: auth.upsert_access(target, by=me.email, pin=new_pin),
                          f"PIN reset for {target}.")
        b = st.columns(2)
        status = str(row.get("Status", "")).lower()
        if status == ACCESS_ACTIVE:
            if b[0].button("Revoke access", disabled=is_secret_owner or target == me.email,
                           width="stretch"):
                _save(lambda: auth.upsert_access(target, by=me.email, status=ACCESS_REVOKED),
                      f"{target} can no longer sign in.")
        else:
            if b[0].button("Restore access", width="stretch"):
                _save(lambda: auth.upsert_access(target, by=me.email, status=ACCESS_ACTIVE),
                      f"{target} can sign in again.")
        role_now = str(row.get("Role", "")).lower()
        other = ROLE_OWNER if role_now != ROLE_OWNER else ROLE_SALES
        if b[1].button(f"Make {other}", disabled=is_secret_owner or target == me.email,
                       width="stretch"):
            _save(lambda: auth.upsert_access(target, by=me.email, role=other),
                  f"{target} is now {other}.")
        if is_secret_owner:
            st.caption("This is the owner email from the app secrets; it is always an active owner.")


def _save(fn, ok_msg: str) -> None:
    try:
        fn()
    except SheetError as e:
        common.sheet_error(e, "Not saved.")
        return
    masters.clear_cache()
    common.flash("success", ok_msg)
    st.rerun()


# ------------------------------------------------------------------ setup

def _setup(m: masters.Masters | None, me: User) -> None:
    backend = get_backend()
    if backend.mode == "gsheets":
        st.markdown(f"Connected to [the Google Sheet]({backend.sheet_url()}) as service account "
                    f"`{backend.service_email}`.")
    else:
        st.markdown(f"**Local mode**: data lives in CSV files in `{backend.sheet_url()}`.")

    try:
        tabs = backend.list_tabs()
    except SheetError as e:
        common.sheet_error(e)
        return
    missing = [t for t in TABS if t not in tabs]
    st.markdown("**App tabs**")
    st.dataframe(pd.DataFrame({"Tab": list(TABS), "Present": ["yes" if t in tabs else "missing" for t in TABS]}),
                 hide_index=True)
    if st.button("Create missing tabs", disabled=not missing, type="primary" if missing else "secondary"):
        try:
            created = backend.ensure_tabs()
        except SheetError as e:
            common.sheet_error(e)
            return
        common.refresh_data()
        common.flash("success", f"Created: {', '.join(created) or 'nothing (all present)'}.")
        st.rerun()

    if m is not None:
        st.markdown("**SKU mapping**")
        st.markdown(f"Source: **{m.sku_source}**. {m.sku['Customer SKU Name'].nunique()} SKU names, "
                    f"{len(m.varieties)} varieties. Changes in the sheet show within "
                    f"{config.master_cache_seconds()} s, or at once with ↻ Refresh data.")
        if m.sku_source.startswith("live"):
            st.caption(f"SKU names, parents and Apple varieties come from '{importer.ALL_CUX_CITY}'; "
                       f"origin and size from '{importer.MAPPING_WHOLE}'. Optional columns you can add: "
                       "'Lot' (or 'UOM') to fix the lot of a SKU, and 'Active' in "
                       f"'{importer.MAPPING_WHOLE}' (Y) to choose the origin being sourced.")
        no_lot = sorted({r["Customer SKU Name"] for _, r in m.sku.iterrows()
                         if not m.lot_for(r["City"], r["Customer"], r["Customer SKU Name"])})
        if no_lot:
            st.warning("No lot for these SKU names (no unit in the name and no Lot column). "
                       "They cannot be added until a Lot is set: " + ", ".join(no_lot))

    if m is not None:
        st.markdown("**Master data checks**")
        warn = m.active_warnings()
        if warn.empty:
            st.success("Every SKU name has exactly one Active origin (or a single row).")
        else:
            st.warning(f"{len(warn)} SKU name(s) need exactly one row with Active = Y in SKU_Map:")
            st.dataframe(warn, hide_index=True, width="stretch")
        pairs = m.sku[["City", "Customer"]].drop_duplicates()
        no_store = [f"{r.City} / {r.Customer}" for r in pairs.itertuples()
                    if r.City and r.Customer and not m.stores_for(r.City, r.Customer)]
        if no_store:
            st.warning("No stores in Store_Map for: " + ", ".join(no_store)
                       + ". Users cannot raise indents for these until stores are added.")
