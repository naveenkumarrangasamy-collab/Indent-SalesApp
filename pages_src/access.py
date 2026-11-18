"""Owner only: who can sign in, PINs, sheet setup and master-data checks."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import auth, config, importer, masters
from core.auth import User
from core.schema import (ACCESS_ACTIVE, ACCESS_REVOKED, OWNER_ROLES, ROLE_OWNER_FULL, ROLE_SALES,
                         ROLES, TABS, role_name)
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

    from pages_src import mail_admin
    names = ["Users & PINs", "E-mails", "Add SKUs"] + (["Import indents"] if user.is_full_owner else []) \
        + ["Sheet setup & checks"]
    tabs = dict(zip(names, st.tabs(names)))
    t_users, t_mail, t_setup = tabs["Users & PINs"], tabs["E-mails"], tabs["Sheet setup & checks"]
    with t_users:
        if m is not None:
            _users(m, user)
    with t_mail:
        if m is not None:
            mail_admin.emails_tab(m, user)
    with tabs["Add SKUs"]:
        from pages_src import add_skus
        add_skus.render(m, user)
    if "Import indents" in tabs:
        with tabs["Import indents"]:
            from pages_src import import_indents
            import_indents.render(m, user)
    with t_setup:
        _setup(m, user)


# ------------------------------------------------------------------ users

ROLE_HELP = {r: role_name(r) for r in ROLES}   # just the name in the role pickers


def _no_full_owner(acc: pd.DataFrame) -> bool:
    if acc.empty:
        return True
    active = acc[acc["Status"].str.lower() == ACCESS_ACTIVE]
    return not (active["Role"].str.strip().str.lower() == ROLE_OWNER_FULL).any()


def _roles_for(me: User, acc: pd.DataFrame) -> list[str]:
    """Only a full owner can make someone a full owner (any owner may, until
    the first full owner exists)."""
    if me.is_full_owner or _no_full_owner(acc):
        return ROLES
    return [r for r in ROLES if r != ROLE_OWNER_FULL]

def _users(m: masters.Masters, me: User) -> None:
    acc = m.access
    if not acc.empty:
        show = pd.DataFrame({"Email": acc["Email"], "Name": acc["Name"], "Role": acc["Role"].map(role_name),
                             "Status": acc["Status"],
                             "City": [("all cities" if str(r).lower() in OWNER_ROLES else
                                       (c or ("all cities" if str(r).lower() == "warehouse" else "— (own indents only)")))
                                      for r, c in zip(acc["Role"], acc["City"])],
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
        role = st.selectbox("Role", _roles_for(me, acc), format_func=ROLE_HELP.get)
        cities = st.multiselect("City", m.cities(), placeholder="Choose one or more cities",
                                help="Sales: places indents only in these cities and can see and edit "
                                     "every indent there (empty: own indents only). Warehouse: production "
                                     "and batching for these cities (empty: all cities). Owners see everything.")
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
                                                 status=ACCESS_ACTIVE, pin=pin,
                                                 cities=cities if role not in OWNER_ROLES else [], stores=[]),
                      f"{email_n} added as {role_name(role)}" + (f" for {', '.join(cities)}" if cities and role not in OWNER_ROLES
                                                      else "")
                      + ". Share the PIN with them privately.")

    with c2:
        st.markdown("**Manage a user**")
        emails = list(acc["Email"]) if not acc.empty else []
        if not emails:
            st.caption("Nobody to manage yet.")
            return
        target = st.selectbox("User", emails, key="acc_target")
        row = auth.access_row(acc, target)
        is_secret_owner = auth.norm_email(target) == config.owner_email()
        role_now = str(row.get("Role", "")).lower()
        role_now = role_now if role_now in ROLES else ROLE_SALES
        locked = (is_secret_owner and not me.is_full_owner) or target == me.email \
            or (role_now == ROLE_OWNER_FULL and not me.is_full_owner)
        locked = locked and not (_no_full_owner(acc) and target != me.email)
        choices = ROLES if locked else _roles_for(me, acc)
        with st.form(f"role_{target}"):
            new_role = st.selectbox("Role", choices, index=choices.index(role_now), format_func=ROLE_HELP.get,
                                    disabled=locked,
                                    help="You cannot change your own role. Only a full owner can change the "
                                         "owner from the app secrets or a full owner." if locked else None)
            current = auth.parse_cities(row.get("City", ""))
            options = list(dict.fromkeys(m.cities() + current))
            new_cities = st.multiselect("City", options, default=current,
                                        help="Sales: indents in these cities (empty: own indents only). "
                                             "Warehouse: production for these cities (empty: all). "
                                             "Owners always see every city.")
            if st.form_submit_button("Save role and city", icon=":material/save:", type="primary"):
                role_set = None if locked else new_role
                _save(lambda: auth.upsert_access(target, by=me.email, role=role_set,
                                                 cities=new_cities if (role_set or role_now) not in OWNER_ROLES else [],
                                                 stores=[]),
                      f"{target}: {role_name(role_set or role_now)}"
                      + (f", cities {', '.join(new_cities) or 'none'}" if (role_set or role_now) not in OWNER_ROLES
                         else ", all cities") + ".")
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

def _start_fresh(me: User) -> None:
    """Owner: back up and clear every indent (Indent_Lines, Change_Log, PO_Freeze, Drafts)."""
    from core import indents
    with st.expander("🧹 Start fresh: clear all indents", expanded=False):
        try:
            df = indents.read_lines(fresh=True)
            n = df["indent_id"].nunique() if not df.empty else 0
        except SheetError as e:
            common.sheet_error(e)
            return
        st.markdown(
            f"There are **{n} indents** in the sheet. This copies Indent_Lines, Change_Log, PO_Freeze and "
            "Drafts into new **Backup_…** tabs, then empties them (headers stay). Users, stores, SKU "
            "mapping, e-mail lists and the e-mail log are not touched. Numbering starts again at **IN-001**.")
        typed = st.text_input("Type CLEAR to confirm", key="fresh_confirm", placeholder="CLEAR")
        if st.button("Back up and clear all indents", icon=":material/delete_sweep:", type="primary",
                     disabled=typed.strip() != "CLEAR", key="fresh_btn"):
            try:
                with st.spinner("Backing up and clearing…"):
                    done = indents.backup_and_clear(me.email)
            except SheetError as e:
                st.error(f"Not cleared. {e}")
                return
            from pages_src import state
            state.start_new()
            st.session_state.pop("fresh_confirm", None)
            common.flash("success", "Cleared: " + ", ".join(f"{t} {r} rows" for t, r in done.items())
                         + ". Backups are in the Backup_… tabs of the Google Sheet.")
            st.rerun()


def _setup(m: masters.Masters | None, me: User) -> None:
    backend = get_backend()
    if backend.mode == "gsheets":
        st.markdown(f"Connected to [the Google Sheet]({backend.sheet_url()}) as service account "
                    f"`{backend.service_email}`.")
    else:
        st.markdown(f"**Local mode**: data lives in CSV files in `{backend.sheet_url()}`.")

    if me.is_full_owner:
        _start_fresh(me)

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
                    f"{config.master_cache_seconds() // 60} min, or at once with ↻ Refresh data.")
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
        warn = m.active_warnings() if config.show_spec() else m.active_warnings().iloc[0:0]
        if warn.empty and not config.show_spec():
            st.caption("Spec (origin / size) is switched off, so Active-origin checks are skipped.")
        elif warn.empty:
            st.success("Every SKU name has exactly one Active origin (or a single row).")
        else:
            st.warning(f"{len(warn)} SKU name(s) need exactly one row with Active = Y in SKU_Map:")
            st.dataframe(warn, hide_index=True, width="stretch")
        pairs = m.sku[["City", "Customer"]].drop_duplicates()
        no_store = [f"{r.City} / {r.Customer}" for r in pairs.itertuples()
                    if r.City and r.Customer and not m.stores_for(r.City, r.Customer)]
        if no_store:
            st.warning("No stores in 'Customer List' for: " + ", ".join(no_store)
                       + ". Users cannot raise indents for these until stores are added.")
