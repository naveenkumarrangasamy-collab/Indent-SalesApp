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
    if not user.opens_access:
        st.error("You don't have access to this page.")
        return
    st.markdown("### Access")
    try:
        m = masters.load_masters()
    except SheetError as e:
        common.sheet_error(e)
        m = None

    from pages_src import mail_admin
    full = user.is_full_owner
    names = ["Users & PINs"] + (["E-mails"] if full else []) + ["Add SKUs"] + (["Import indents"] if full else []) \
        + ["Duplicate names", "Sheet setup & checks"]
    tabs = dict(zip(names, st.tabs(names)))
    t_users, t_setup = tabs["Users & PINs"], tabs["Sheet setup & checks"]
    with t_users:
        if m is not None:
            _users(m, user)
    if "E-mails" in tabs:              # Creator only (21 Nov)
        with tabs["E-mails"]:
            if m is not None:
                mail_admin.emails_tab(m, user)
    with tabs["Add SKUs"]:
        from pages_src import add_skus
        add_skus.render(m, user)
    if "Import indents" in tabs:
        with tabs["Import indents"]:
            from pages_src import import_indents
            import_indents.render(m, user)
    with tabs["Duplicate names"]:
        _duplicates(m)
        _variety_check(m)
    with t_setup:
        _setup(m, user)


def _duplicates(m) -> None:
    """The same fruit under several SKU names (or the same name on several rows) per
    customer, to clean up once in All Cux City / New (20 Nov)."""
    from core import bulk_tabs
    if m is None:
        return
    rows = bulk_tabs.duplicate_names(m.sku)
    if not rows:
        st.success("No duplicate SKU names.")
        return
    st.caption(f"{len(rows)} group(s): the same item under several names, or one name on several rows. "
               "Keep one name (the one mapped in the New tab), fix the others in All Cux City.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _variety_check(m) -> None:
    """Apple rows whose variety column disagrees with the variety written in the name
    (New, All Cux City, Mapping Whole); one button writes the name's variety (21 Nov)."""
    from core import variety_fix
    if m is None:
        return
    st.markdown("**Apple variety vs name**")
    if st.button("Check the sheet", key="vf_check"):
        try:
            st.session_state["vf_plan"] = variety_fix.plan(variety_fix.read(get_backend()),
                                                           m.varieties_for("Apple"))
        except SheetError as e:
            common.sheet_error(e)
    rows = st.session_state.get("vf_plan")
    if rows is None:
        return
    if not rows:
        st.success("Every Apple name and its variety agree.")
        return
    st.dataframe(pd.DataFrame(rows).drop(columns="_col"), hide_index=True, width="stretch")
    if st.button(f"Fix {len(rows)} row(s) in the sheet", type="primary", key="vf_fix"):
        try:
            n = variety_fix.apply(get_backend(), rows)
        except SheetError as e:
            common.sheet_error(e, "Not fixed.")
            return
        st.session_state.pop("vf_plan", None)
        masters.clear_cache()
        common.flash("success", f"{n} variety cell(s) set from the name.")
        st.rerun()


# ------------------------------------------------------------------ users

ROLE_HELP = {r: role_name(r) for r in ROLES}   # just the name in the role pickers


def _no_full_owner(acc: pd.DataFrame) -> bool:
    if acc.empty:
        return True
    active = acc[acc["Status"].str.lower() == ACCESS_ACTIVE]
    return not (active["Role"].str.strip().str.lower() == ROLE_OWNER_FULL).any()


def _roles_for(me: User, acc: pd.DataFrame) -> list[str]:
    """Creator: every role. Owner: only Warehouse and Sales (21 Nov). Before the first
    Creator exists, any owner may make one."""
    if me.is_full_owner or _no_full_owner(acc):
        return ROLES
    return [r for r in ROLES if r not in OWNER_ROLES]


ALL = "All cities"


def _city_text(role: str, cities: str) -> str:
    r = str(role or "").strip().lower()
    if r == ROLE_OWNER_FULL or (r in OWNER_ROLES and not str(cities or "").strip()):
        return ALL
    return cities or (ALL if r == "warehouse" else "— (own indents only)")


def _manageable(me: User, acc: pd.DataFrame) -> pd.DataFrame:
    """Users this person may see and edit: Creator all; an Owner only Sales and
    Warehouse users in his cities (and himself, read-only)."""
    if acc.empty or me.is_full_owner:
        return acc
    roles = acc["Role"].astype(str).str.strip().str.lower()
    mine = acc["Email"].map(auth.norm_email) == auth.norm_email(me.email)

    def in_scope(c: str) -> bool:
        cs = auth.parse_cities(c)
        return me.sees_all_cities or not cs or any(me.in_my_cities(x) for x in cs)
    return acc[mine | (~roles.isin(OWNER_ROLES) & acc["City"].map(in_scope))]


def _city_options(m: masters.Masters, me: User, current: list[str] | None = None) -> list[str]:
    allc = [c for c in m.cities() if me.sees_all_cities or me.in_my_cities(c)]
    return list(dict.fromkeys(allc + [c for c in (current or []) if me.sees_all_cities]))


def _pick_cities(key: str, options: list[str], current: list[str], all_now: bool) -> tuple[bool, list[str]]:
    """'All cities' tick + the city list (ignored when ticked)."""
    every = st.checkbox(ALL, value=all_now, key=f"{key}_all")
    picked = st.multiselect("City", options, default=[c for c in current if c in options], key=f"{key}_c",
                            placeholder="Choose one or more cities", disabled=every)
    return every, picked


def _cities_to_save(role: str, every: bool, picked: list[str], options: list[str]) -> list[str]:
    if role == ROLE_OWNER_FULL:
        return []
    if every:
        return [] if role in OWNER_ROLES else list(options)   # Owner: empty = all cities
    return picked


def _users(m: masters.Masters, me: User) -> None:
    acc = _manageable(me, m.access)
    if not acc.empty:
        show = pd.DataFrame({"Email": acc["Email"], "Name": acc["Name"], "Role": acc["Role"].map(role_name),
                             "Status": acc["Status"],
                             "City": [_city_text(r, c) for r, c in zip(acc["Role"], acc["City"])],
                             "PIN set": acc["PIN_Hash"].map(lambda v: "yes" if v else "no"),
                             "Updated": acc["Updated_At"].str[:16].str.replace("T", " "),
                             "By": acc["Updated_By"]})
        if me.is_full_owner:
            show.insert(4, "Access page", [("yes" if str(r).strip().lower() == ROLE_OWNER_FULL
                                            else ("yes" if auth.is_yes(a) else "no")
                                            if str(r).strip().lower() in OWNER_ROLES else "")
                                           for r, a in zip(acc["Role"], acc.get("Admin_Page", [""] * len(acc)))])
        st.dataframe(show, hide_index=True, width="stretch")
    else:
        st.info("No users yet. Add the first sales user below.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Add a user**")
        email = st.text_input("Work email", key="nu_email")
        name = st.text_input("Name", key="nu_name")
        role = st.selectbox("Role", _roles_for(me, m.access), format_func=ROLE_HELP.get, key="nu_role")
        options = _city_options(m, me)
        every, cities = (False, []) if role == ROLE_OWNER_FULL else _pick_cities("nu", options, [], False)
        admin = (st.radio("Access page", ["No", "Yes"], horizontal=True, key="nu_admin") == "Yes"
                 if role == "owner" and me.is_full_owner else False)
        pin = st.text_input("Initial PIN (4–6 digits)", type="password", max_chars=6, key="nu_pin")
        if st.button("Add user", type="primary", key="nu_add"):
            email_n = auth.norm_email(email)
            if not auth.valid_email(email_n):
                st.error("Enter a valid email.")
            elif auth.access_row(m.access, email_n) is not None:
                st.error("This email is already in the list. Use 'Manage a user'.")
            elif not auth.valid_pin(pin):
                st.error("PIN must be 4 to 6 digits.")
            elif role not in _roles_for(me, m.access):
                st.error("You can't give this role.")
            elif role != ROLE_OWNER_FULL and not every and not cities and not me.sees_all_cities:
                st.error("Choose a city.")
            else:
                save = _cities_to_save(role, every, cities, options)
                for k in ("nu_email", "nu_name", "nu_pin"):
                    st.session_state.pop(k, None)
                _save(lambda: auth.upsert_access(email_n, by=me.email, name=name, role=role,
                                                 status=ACCESS_ACTIVE, pin=pin, cities=save, stores=[],
                                                 admin_page=admin),
                      f"{email_n} added as {role_name(role)} ("
                      + (ALL if role == ROLE_OWNER_FULL or (every and role in OWNER_ROLES) else ", ".join(save) or "no city")
                      + "). Share the PIN with them privately.")

    with c2:
        st.markdown("**Manage a user**")
        emails = [e for e in acc["Email"] if auth.norm_email(e) != auth.norm_email(me.email)] if not acc.empty else []
        if not emails:
            st.caption("Nobody to manage yet.")
            return
        target = st.selectbox("User", emails, key="acc_target")
        row = auth.access_row(acc, target)
        is_secret_owner = auth.norm_email(target) == config.owner_email()
        role_now = str(row.get("Role", "")).lower()
        role_now = role_now if role_now in ROLES else ROLE_SALES
        locked = (is_secret_owner and not me.is_full_owner) or (role_now in OWNER_ROLES and not me.is_full_owner)
        locked = locked and not _no_full_owner(m.access)
        choices = ROLES if locked else _roles_for(me, m.access)
        new_role = st.selectbox("Role", choices, index=choices.index(role_now), format_func=ROLE_HELP.get,
                                disabled=locked, key=f"mu_role_{target}")
        current = auth.parse_cities(row.get("City", ""))
        options = _city_options(m, me, current)
        all_now = (new_role in OWNER_ROLES and not current) or (bool(options) and set(options) <= set(current))
        every, new_cities = ((False, []) if new_role == ROLE_OWNER_FULL
                             else _pick_cities(f"mu_{target}", options, current, all_now))
        admin = None
        if new_role == "owner" and me.is_full_owner:
            admin = st.radio("Access page", ["No", "Yes"], horizontal=True, key=f"mu_admin_{target}",
                             index=1 if auth.is_yes(row.get("Admin_Page", "")) else 0) == "Yes"
        if st.button("Save", icon=":material/save:", type="primary", key=f"mu_save_{target}"):
            if not locked and new_role not in _roles_for(me, m.access):
                st.error("You can't give this role.")
            else:
                role_set = None if locked else new_role
                eff = role_set or role_now
                if not me.sees_all_cities:     # an Owner keeps the user's cities outside his own
                    outside = [c for c in current if not me.in_my_cities(c)]
                else:
                    outside = []
                save = _cities_to_save(eff, every, new_cities, options)
                save = list(dict.fromkeys(save + outside)) if eff not in OWNER_ROLES else save
                _save(lambda: auth.upsert_access(target, by=me.email, role=role_set, cities=save, stores=[],
                                                 admin_page=admin if eff == "owner" else None),
                      f"{target}: {role_name(eff)} ("
                      + (ALL if eff == ROLE_OWNER_FULL or (every and eff in OWNER_ROLES) else ", ".join(save) or "no city")
                      + ").")
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
            if b[0].button("Revoke access", disabled=is_secret_owner or locked, width="stretch"):
                _save(lambda: auth.upsert_access(target, by=me.email, status=ACCESS_REVOKED),
                      f"{target} can no longer sign in.")
        else:
            if b[0].button("Restore access", width="stretch", disabled=locked):
                _save(lambda: auth.upsert_access(target, by=me.email, status=ACCESS_ACTIVE),
                      f"{target} can sign in again.")
        if is_secret_owner:
            st.caption("The Creator email from the app secrets; it can always sign in.")


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
