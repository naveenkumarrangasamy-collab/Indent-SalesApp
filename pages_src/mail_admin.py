"""Access page (owner): the E-mails tab.

1. Mail server   - is sending set up, the last error in plain words, a test.
2. Production e-mails - the production report (every hour 8 AM-2 PM): address (+ name) -> cities.
3. PO e-mails     - every PO the moment it is uploaded: address (+ name), all cities / customers.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, hourly, indents, mailer, masters, recipients
from core.auth import User
from core.recipients import Recipient
from core.sheets import SheetError
from pages_src import common

TEAMS = {
    "Ground": ("Production e-mails",
               "Every hour from 8 AM to 2 PM: the production report (make-ready list + by spec size, all customers "
               "together) for today's deliveries, only for the cities chosen for each address, as PDF + Excel."),
    "Central": ("PO e-mails",
                "The moment any PO is uploaded (any time, all cities and customers): the customer's PO plus "
                "the SO details as PDF + Excel."),
}


def _hint(detail: str) -> str:
    d = detail.lower()
    if "not set up" in d:
        return "Add `smtp_user` and `smtp_password` to the Streamlit secrets."
    if "refused the login" in d or "535" in d or "534" in d or "username and password" in d:
        return ("The mailbox refused the password. For Gmail you need a 16-character **App password** "
                "(Google Account → Security → 2-Step Verification on → App passwords), not the normal "
                "password. A company @ninjacart.com (Google Workspace) mailbox may have App passwords "
                "switched off by the admin; then use a separate Gmail account as the sender, or ask IT.")
    if "could not reach" in d or "timed out" in d or "connection" in d:
        return "The mail server could not be reached / closed the connection. Check `smtp_host` / `smtp_port`."
    return ""


def _server(me: User) -> None:
    s = mailer.settings()
    pw = s["password"]
    checks = [
        ("Sender mailbox (smtp_user)", bool(s["user"]) and "@" in s["user"], s["user"] or "missing"),
        ("App password (smtp_password)", len(pw) == 16,
         "missing" if not pw else ("set (16 characters)" if len(pw) == 16
                                   else f"set, but {len(pw)} characters (a Gmail App password has 16)")),
        ("Mail server", True, f"{s['host']}:{s['port']}"),
    ]
    rows = "".join(f"<div>{'✅' if ok else '❌'} <b>{lbl}</b> · {v}</div>" for lbl, ok, v in checks)
    st.markdown(rows, unsafe_allow_html=True)
    try:
        log = recipients.read_log()
    except SheetError:
        log = pd.DataFrame()
    if not log.empty:
        last = log.iloc[-1]
        ok = last.get("status") == "sent"
        when = str(last.get("sent_at", ""))[:16].replace("T", " ")
        (st.success if ok else st.error)(
            f"Last e-mail ({last.get('kind')}, {when}) to {last.get('to')}: "
            + ("sent." if ok else f"**failed** — {last.get('detail')}"))
        if not ok and _hint(str(last.get("detail", ""))):
            st.info(_hint(str(last.get("detail", ""))))
    c = st.columns([2, 1])
    to = c[0].text_input("Send a test e-mail to", value=me.email, key="mail_test_to")
    if c[1].button("Send test", icon=":material/send:", width="stretch", key="mail_test_btn",
                   disabled=not mailer.configured()):
        with st.spinner("Sending…"):
            ok, msg = mailer.send_test_mail(me.email, to=to.strip())
        (st.success if ok else st.error)(msg)
        if not ok and _hint(msg):
            st.info(_hint(msg))


def _team(team: str, m: masters.Masters, me: User, people: list[Recipient]) -> None:
    title, what = TEAMS[team]
    st.markdown(f"#### {title}")
    st.caption(what)
    mine = [r for r in people if (r.hourly if team == "Ground" else r.so)]
    if mine:
        for r in mine:
            c = st.columns([2.2, 2.6, 0.6], vertical_alignment="center")
            c[0].markdown(f"**{r.email}**" + (f"<br><span class='mt-muted'>{r.name}</span>" if r.name else "")
                          + ("" if r.active else " <span class='mt-muted'>(paused)</span>"),
                          unsafe_allow_html=True)
            c[1].markdown(f"<span class='mt-muted'>Cities:</span> {', '.join(r.cities) or 'all cities'}"
                          if team == "Ground" else "<span class='mt-muted'>Every PO · all cities and customers</span>",
                          unsafe_allow_html=True)
            if c[2].button("", icon=":material/delete:", key=f"rm_{team}_{r.email}", help="Remove this address"):
                recipients.remove(r.email, team)
                common.flash("success", f"{r.email} removed from {TEAMS[team][0].lower()}.")
                st.rerun()
    else:
        st.info("Nobody yet. Add the first address below.")

    with st.form(f"add_{team}", clear_on_submit=True, border=True):
        st.markdown("**Add or change an address**")
        c = st.columns([1.4, 1])
        email = c[0].text_input("E-mail", placeholder="name@company.com")
        name = c[1].text_input("Name (optional)")
        cities = (st.multiselect("Cities whose indents go to this address (empty = all cities)", m.cities())
                  if team == "Ground" else [])
        if st.form_submit_button("Save", icon=":material/person_add:", type="primary"):
            e = email.strip().lower()
            if "@" not in e or "." not in e.split("@")[-1]:
                st.error("Enter a valid e-mail address.")
            else:
                try:
                    recipients.upsert(Recipient(e, name.strip(), team, hourly=team == "Ground",
                                                so=team == "Central", cities=cities), by=me.email)
                except SheetError as err:
                    st.error(f"Not saved. {err}")
                else:
                    common.flash("success", f"{e} saved for {TEAMS[team][0].lower()}"
                                            + (f" ({', '.join(cities) or 'all cities'})." if team == "Ground"
                                               else " (every PO)."))
                    st.rerun()

    # see exactly what this list receives
    c = st.columns([2, 1])
    who = c[0].selectbox("Send a sample of this e-mail to", [me.email] + [r.email for r in mine],
                         key=f"sample_to_{team}", accept_new_options=True,
                         help="Uses that address's cities when it is on the production e-mail list")
    if c[1].button("Send sample", icon=":material/forward_to_inbox:", width="stretch",
                   key=f"sample_btn_{team}", disabled=not mailer.configured()):
        scope = next((r for r in mine if r.email == who), None)
        with st.spinner("Building and sending…"):
            ok, msg = _sample(team, who, scope, me)
        (st.success if ok else st.error)(msg)
        if not ok and _hint(msg):
            st.info(_hint(msg))
    if team == "Ground":
        with st.expander("Download today's production e-mail files"):
            if st.button("Build PDF + Excel", key="hm_build"):
                st.session_state["hm_files"] = hourly.preview(config.now_ist().date().isoformat())
            for name, data, mime in st.session_state.get("hm_files", []):
                st.download_button(name, data, file_name=name, mime=mime, key=f"dl_{name}",
                                   icon=":material/download:")
        with st.expander("Automatic sending every hour"):
            st.markdown(
                "A Streamlit Cloud app sleeps when nobody has it open, so a schedule in the GitHub repository "
                "opens the app every hour from 8 AM to 2 PM (waking it if needed). The app sends the production "
                "e-mail **every hour, 8 AM to 2 PM**, on the hour (cron-job.org starts it a few minutes early; GitHub runs are a late backup; each goes out once). Nothing to set up. "
                "Test: GitHub → **Actions** → *Hourly indent e-mail* → **Run workflow**.")


def _sample(team: str, to: str, scope: Recipient | None, me: User) -> tuple[bool, str]:
    if team == "Ground":
        return hourly.send_sample(to, scope)
    # Central: the latest PO-frozen indent in scope (else the latest indent) as an example
    df = indents.read_lines()
    summ = indents.summary(df)
    if summ.empty:
        return False, "No indent to use as a sample yet."
    # PO e-mails cover every city / customer: any indent can be the sample
    pick = summ[summ["status"] == "Frozen"]
    pick = (pick if not pick.empty else summ).sort_values("last_edited_at").iloc[-1]
    cur = indents.snapshot(df, pick["indent_id"])
    return mailer.send_so_mail(cur, "", b"", me.email, po_number="SAMPLE", to_override=[to], sample=True)


def emails_tab(m: masters.Masters, me: User) -> None:
    st.markdown("#### Mail server")
    _server(me)
    try:
        people = recipients.read_all()
    except SheetError as e:
        common.sheet_error(e)
        return
    st.divider()
    t1, t2 = st.tabs(["Production e-mails (hourly)", "PO e-mails"])
    with t1:
        _team("Ground", m, me, people)
    with t2:
        _team("Central", m, me, people)
