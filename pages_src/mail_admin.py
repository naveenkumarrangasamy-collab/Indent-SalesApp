"""Access page (owner): e-mail recipients and e-mail sending."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, hourly, mailer, masters, recipients
from core.auth import User
from core.recipients import TEAMS, Recipient
from core.sheets import SheetError
from pages_src import common

NEW = "➕ New recipient"


# ------------------------------------------------------------------ recipients

def recipients_tab(m: masters.Masters, me: User) -> None:
    try:
        people = recipients.read_all()
    except SheetError as e:
        common.sheet_error(e)
        return
    st.caption("Who gets which e-mail, and which cities / customers / stores they see in it. "
               "**Ground team**: the hourly indent e-mail (8 AM–2 PM). **Central team**: the SO / PO "
               "e-mail the moment a PO is uploaded. Leave cities, customers or stores empty for *all*.")
    if people:
        st.dataframe(pd.DataFrame([{
            "Name": r.name, "Email": r.email, "Team": r.team,
            "Hourly indent": "✓" if r.hourly else "", "SO / PO": "✓" if r.so else "",
            "Cities": ", ".join(r.cities) or "all", "Customers": ", ".join(r.customers) or "all",
            "Stores": ", ".join(r.stores) or "all", "Active": "yes" if r.active else "paused"}
            for r in people]), hide_index=True, width="stretch")
    else:
        st.info("No recipients yet. Add the ground team and the central team below.")

    by_email = {r.email: r for r in people}
    pick = st.selectbox("Add or change", [NEW] + list(by_email), key="rc_pick",
                        format_func=lambda e: e if e == NEW else f"{by_email[e].name or e} · {e}")
    cur = by_email.get(pick) or Recipient(email="")
    k = f"rc_{pick}"
    with st.container(border=True):
        c = st.columns([1.4, 1.2, 1])
        email = c[0].text_input("E-mail", value=cur.email, key=f"{k}_email", disabled=pick != NEW,
                                placeholder="name@company.com")
        name = c[1].text_input("Name", value=cur.name, key=f"{k}_name")
        team = c[2].segmented_control("Team", TEAMS, default=cur.team if cur.team in TEAMS else TEAMS[0],
                                      key=f"{k}_team", required=True) or TEAMS[0]
        is_new = pick == NEW
        t = st.columns(3)
        hourly_on = t[0].toggle("Hourly indent e-mail (8 AM–2 PM)", key=f"{k}_hourly",
                                value=cur.hourly if not is_new else team == "Ground")
        so_on = t[1].toggle("SO / PO e-mail (on PO upload)", key=f"{k}_so",
                            value=cur.so if not is_new else team == "Central")
        active = t[2].toggle("Active", value=cur.active, key=f"{k}_active",
                             help="Pause e-mails without removing the person")

        all_cities = m.cities()
        cities = st.multiselect("Cities (empty = all)", all_cities,
                                default=[x for x in all_cities if x.casefold() in {c.casefold() for c in cur.cities}],
                                key=f"{k}_cities")
        city_scope = cities or all_cities
        all_customers = sorted({cu for ci in city_scope for cu in m.customers(ci)}, key=str.casefold)
        customers = st.multiselect("Customers (empty = all)", all_customers,
                                   default=[x for x in all_customers if x.casefold() in {c.casefold() for c in cur.customers}],
                                   key=f"{k}_customers")
        cust_scope = customers or all_customers
        idx = m.store_index()
        all_stores = sorted({s for ci in city_scope for cu in cust_scope for s in m.stores_for(ci, cu)},
                            key=str.casefold)
        stores = st.multiselect("Stores / facilities (empty = all)", all_stores,
                                default=[x for x in all_stores if x.casefold() in {c.casefold() for c in cur.stores}],
                                key=f"{k}_stores", format_func=lambda s: f"{s} — {idx.get(s, '')}")
        scope = Recipient("x", cities=cities, customers=customers, stores=stores).scope_text()
        st.caption(f"Sees: **{scope}**")

        b = st.columns([1, 1, 2])
        if b[0].button("Save recipient", icon=":material/save:", type="primary", width="stretch",
                       key=f"{k}_save"):
            e = email.strip().lower()
            if "@" not in e or "." not in e.split("@")[-1]:
                st.error("Enter a valid e-mail address.")
            elif not (hourly_on or so_on):
                st.error("Turn on at least one e-mail for this person.")
            else:
                try:
                    recipients.upsert(Recipient(e, name.strip(), team, hourly_on, so_on, cities, customers,
                                                stores, active), by=me.email)
                except SheetError as err:
                    st.error(f"Not saved. {err}")
                else:
                    st.session_state.pop("rc_pick", None)
                    common.flash("success", f"Saved {e} ({team} team; sees {scope}).")
                    st.rerun()
        if pick != NEW:
            confirm = st.session_state.get("rc_remove") == pick
            if b[1].button("Yes, remove" if confirm else "Remove", icon=":material/person_remove:",
                           width="stretch", key=f"{k}_rm", type="primary" if confirm else "secondary"):
                if confirm:
                    recipients.remove(pick)
                    st.session_state.pop("rc_remove", None)
                    st.session_state.pop("rc_pick", None)
                    common.flash("success", f"{pick} removed from the e-mails.")
                else:
                    st.session_state["rc_remove"] = pick
                st.rerun()
            if confirm:
                b[2].warning(f"Remove {pick} from all e-mails? Press **Yes, remove**.")


# ------------------------------------------------------------------ sending

def sending_tab(me: User) -> None:
    st.markdown("**Mail server**")
    st.caption(mailer.status_text().split(" · to:")[0])
    if not mailer.configured():
        st.warning("E-mail is not set up. Add `smtp_user` and `smtp_password` to the app secrets.")
    with st.expander("How to get the Gmail App password"):
        st.markdown(
            "Turn on **2-Step Verification** on the sending Google account, then open **Google Account → "
            "Security → App passwords**, create one (any name), and paste the 16-character code as "
            "`smtp_password`. The normal Gmail password does not work. A company (Workspace) mailbox may "
            "need the admin to allow App passwords.")
    if st.button("Send test e-mail", icon=":material/send:", disabled=not mailer.configured()):
        with st.spinner("Sending…"):
            ok, msg = mailer.send_test_mail(me.email)
        (st.success if ok else st.error)(msg)

    st.divider()
    first, last = hourly.hours()
    days = ", ".join({0: "today", 1: "tomorrow"}.get(d, f"+{d} days") for d in hourly.delivery_offsets())
    st.markdown("**Hourly indent e-mail**")
    st.caption(f"Every hour from {first}:00 to {last - 12 if last > 12 else last}:00 "
               f"{'PM' if last >= 12 else 'AM'} IST, for delivery {days}, to each active recipient with "
               "*Hourly indent e-mail* on, showing only their cities / customers / stores. Body: overall "
               "SKU indent + customer-level indent. Attached: 2 PDF + 2 Excel.")
    try:
        people = recipients.hourly_list()
    except SheetError:
        people = []
    c = st.columns([1.3, 1.3, 2])
    target = c[0].selectbox("Send to", ["Everyone on the hourly list"] + [r.email for r in people],
                            key="hm_target")
    if c[1].button("Send now", icon=":material/schedule_send:", type="primary", width="stretch",
                   disabled=not people or not mailer.configured(),
                   help="Sends this hour's e-mail now, even outside 8 AM–2 PM"):
        with st.spinner("Building and sending…"):
            res = hourly.run(force=True, only=None if target.startswith("Everyone") else target)
        for r in res:
            (st.success if r["status"] == "sent" else st.warning)(f"{r['status']}: {r['to']} {r.get('detail', '')}")
    if not people:
        c[2].caption("Add recipients with the hourly e-mail on the **E-mail recipients** tab.")

    with st.expander("Preview the 4 files (today's delivery)"):
        scope_pick = st.selectbox("As seen by", ["everyone"] + [r.email for r in people], key="hm_prev")
        if st.button("Build files", key="hm_build"):
            who = next((r for r in people if r.email == scope_pick), None)
            st.session_state["hm_files"] = hourly.preview(config.now_ist().date().isoformat(), who)
        for name, data, mime in st.session_state.get("hm_files", []):
            st.download_button(name, data, file_name=name, mime=mime, key=f"dl_{name}",
                               icon=":material/download:")

    with st.expander("Automatic sending (GitHub schedule) — one-time setup"):
        st.markdown(
            "The hourly e-mail is sent by a schedule in the GitHub repository "
            "(`.github/workflows/hourly-indent-mail.yml`), because a Streamlit Cloud app sleeps when "
            "nobody has it open. One-time setup:\n"
            "1. GitHub → the repository → **Settings → Secrets and variables → Actions → New repository "
            "secret**.\n"
            "2. Name: `STREAMLIT_SECRETS`. Value: paste **exactly the same text** as in Streamlit Cloud → "
            "Manage app → Settings → Secrets (sheet, service-account key, smtp settings).\n"
            "3. **Actions** tab → *Hourly indent e-mail* → **Run workflow** once to test (tick *force*).\n"
            "After that it runs by itself every hour from 8 AM to 2 PM IST. GitHub sometimes starts a "
            "scheduled run a few minutes late.")

    st.divider()
    st.markdown("**E-mail log** (latest first)")
    try:
        log = recipients.read_log()
    except SheetError:
        log = pd.DataFrame()
    if log.empty:
        st.caption("Nothing sent yet.")
    else:
        show = log.drop(columns=["_row"], errors="ignore").iloc[::-1].head(50)
        st.dataframe(show, hide_index=True, width="stretch")
