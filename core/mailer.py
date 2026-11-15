"""E-mails sent by the app.

* SO / PO e-mail: at once when a PO is uploaded, to the central team
  (Mail_Recipients with SO_PO = Y whose scope covers the store) plus
  po_mail_to. Subject starts with the customer name.
* Hourly indent e-mail: see core/hourly.py.

Settings (Streamlit secrets):
    smtp_user      = "sender@gmail.com"          # the mailbox that sends
    smtp_password  = "16-character app password" # Gmail: Google Account > Security > App passwords
    smtp_host      = "smtp.gmail.com"            # optional (default)
    smtp_port      = 587                         # optional (587 STARTTLS, or 465 SSL)
    po_mail_to     = ["rakeshdhasa@gmail.com"]   # optional, default as shown
    po_mail_cc     = []                          # optional
"""
from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage

from core import config

DEFAULT_TO = ["rakeshdhasa@gmail.com"]


def _list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = v.replace(";", ",").split(",")
    return [str(x).strip() for x in v if str(x).strip()]


def settings() -> dict:
    return {
        "host": str(config.get("smtp_host", "smtp.gmail.com") or "smtp.gmail.com"),
        "port": int(config.get("smtp_port", 587) or 587),
        "user": str(config.get("smtp_user", "") or "").strip(),
        "password": str(config.get("smtp_password", "") or "").replace(" ", ""),
        "sender": str(config.get("mail_from", "") or config.get("smtp_user", "") or "").strip(),
        "to": _list(config.get("po_mail_to")) or list(DEFAULT_TO),
        "cc": _list(config.get("po_mail_cc")),
    }


def configured() -> bool:
    s = settings()
    return bool(s["user"] and s["password"] and s["to"])


def build_po_message(cur, file_name: str, pdf: bytes, uploaded_by: str, sender: str,
                     to: list[str], cc: list[str] | None = None) -> EmailMessage:
    h = cur.header
    msg = EmailMessage()
    msg["Subject"] = h.customer or "PO"
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    total = sum(x.amount for x in cur.lines)
    lines_txt = "\n".join(f"  - {x.customer_sku_name}{' (' + x.variety + ')' if x.variety else ''}: "
                          f"{x.qty:g} {x.lot} @ {x.price:,.2f} = {x.amount:,.2f}" for x in cur.lines)
    text = (f"PO received for {h.customer}.\n\n"
            f"Indent: {cur.indent_id}\nCustomer: {h.customer}\nStore: {h.store}\nCity: {h.city}\n"
            f"Delivery: {h.delivery_date} at {h.expected_time}\nPO file: {file_name}\n"
            f"Uploaded by: {uploaded_by}\n\nItems:\n{lines_txt}\n\nTotal amount: {total:,.2f}\n")
    msg.set_content(text)
    rows = "".join(f"<tr><td>{html.escape(x.customer_sku_name)}</td><td>{html.escape(x.variety)}</td>"
                   f"<td>{html.escape(x.lot)}</td><td align='right'>{x.qty:g}</td>"
                   f"<td align='right'>{x.price:,.2f}</td><td align='right'>{x.amount:,.2f}</td></tr>"
                   for x in cur.lines)
    msg.add_alternative(
        f"<p>PO received for <b>{html.escape(h.customer)}</b>.</p>"
        f"<table cellpadding='3'><tr><td>Indent</td><td><b>{cur.indent_id}</b></td></tr>"
        f"<tr><td>Store</td><td>{html.escape(h.store)}</td></tr>"
        f"<tr><td>City</td><td>{html.escape(h.city)}</td></tr>"
        f"<tr><td>Delivery</td><td>{h.delivery_date} at {h.expected_time}</td></tr>"
        f"<tr><td>PO file</td><td>{html.escape(file_name)}</td></tr>"
        f"<tr><td>Uploaded by</td><td>{html.escape(uploaded_by)}</td></tr></table><br>"
        f"<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse'>"
        f"<tr style='background:#1c6b49;color:#fff'><th>Customer SKU Name</th><th>Variety</th><th>Lot</th>"
        f"<th>Qty</th><th>Price</th><th>Amount</th></tr>{rows}"
        f"<tr><td colspan='5' align='right'><b>Total</b></td><td align='right'><b>{total:,.2f}</b></td></tr>"
        f"</table>", subtype="html")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=file_name or "PO.pdf")
    return msg


_STAGE_HELP = {
    "connect": "could not reach the mail server (check smtp_host / smtp_port)",
    "starttls": "the server closed the connection while starting encryption",
    "login": "the server closed the connection at login (wrong password type or SMTP blocked for "
             "this account)",
    "send": "the server closed the connection while receiving the e-mail",
}


def _attempts(host: str, port: int) -> list[tuple[str, int, str]]:
    """Try the configured way first, then the other standard Gmail way."""
    first = (host, port, "ssl" if port == 465 else "starttls")
    other = (host, 587, "starttls") if first[2] == "ssl" else (host, 465, "ssl")
    return [first] if first[:2] == other[:2] else [first, other]


def deliver(msg: EmailMessage) -> tuple[bool, str]:
    """Send with automatic fallback between 587/STARTTLS and 465/SSL.
    Returns (sent, explanation)."""
    s = settings()
    if not configured():
        return False, ("e-mail is not set up: add smtp_user and smtp_password (a Gmail App password) "
                       "to the app secrets.")
    tried = []
    for host, port, mode in _attempts(s["host"], s["port"]):
        stage = "connect"
        try:
            ctx = ssl.create_default_context()
            smtp = (smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) if mode == "ssl"
                    else smtplib.SMTP(host, port, timeout=30))
            with smtp:
                smtp.ehlo()
                if mode == "starttls":
                    stage = "starttls"
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                stage = "login"
                smtp.login(s["user"], s["password"])
                stage = "send"
                refused = smtp.send_message(msg)
            if refused:
                return False, f"the server refused these recipients: {', '.join(refused)}"
            return True, f"sent via {host}:{port} ({mode.upper()})"
        except smtplib.SMTPAuthenticationError as e:
            detail = (e.smtp_error or b"").decode(errors="replace")[:200]
            return False, ("the mail server refused the login for " + s["user"] + ". For Gmail use a "
                           "16-character App password (Google Account > Security > App passwords), not "
                           "the normal password. Company (Workspace) accounts may need the admin to "
                           f"allow it. Server said: {e.smtp_code} {detail}")
        except (smtplib.SMTPException, OSError) as e:
            tried.append(f"{host}:{port} {mode.upper()} - {_STAGE_HELP[stage]} ({type(e).__name__}: {e})")
    return False, "could not send. Tried " + " | ".join(tried)


def build_message(to: list[str], subject: str, html_body: str, text: str,
                  attachments: list[tuple[str, bytes, str]] | None = None,
                  cc: list[str] | None = None) -> EmailMessage:
    s = settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = s["sender"] or s["user"]
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    for name, data, mime in attachments or []:
        main, sub = mime.split("/", 1)
        msg.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return msg


def po_recipients(header) -> list[str]:
    """Central team for this city / customer / store, plus po_mail_to.
    Falls back to the default address when nobody is set up yet."""
    from core import recipients
    try:
        team = [r.email for r in recipients.so_list(header.city, header.customer, header.store)]
    except Exception:
        team = []
    extra = _list(config.get("po_mail_to"))
    out = []
    for e in team + extra:
        if e.lower() not in {x.lower() for x in out}:
            out.append(e)
    return out or list(DEFAULT_TO)


def send_so_mail(cur, file_name: str, pdf: bytes, uploaded_by: str,
                 po_number: str = "", to_override: list[str] | None = None,
                 sample: bool = False) -> tuple[bool, str]:
    """SO placement e-mail with the customer's PO + SO as PDF and Excel."""
    from core import recipients, reports
    s = settings()
    to = to_override or po_recipients(cur.header)
    h = cur.header
    subject = (("[SAMPLE] " if sample else "") + f"{h.customer} - SO placed - {h.store} - {cur.indent_id}"
               + (f" - PO {po_number}" if po_number else ""))
    files = [(file_name or "PO.pdf", pdf, "application/pdf")] if pdf else []
    files += reports.so_files(cur, po_number, file_name, uploaded_by)
    text = (f"SO placed for {h.customer} / {h.store} ({h.city}), delivery {h.delivery_date}. "
            f"Indent {cur.indent_id}, PO {po_number or file_name}. Details attached (PDF and Excel).")
    msg = build_message(to, subject, reports.so_html(cur, po_number, file_name, uploaded_by), text,
                        files, s["cc"])
    if sample:
        msg.replace_header("To", ", ".join(to))
        del msg["Cc"]
    ok, why = deliver(msg)
    recipients.log("sample-so" if sample else "so", cur.indent_id, to + ([] if sample else s["cc"]), ok, why)
    if ok:
        return True, f"SO / PO e-mail sent to {', '.join(to + s['cc'])}."
    return False, f"SO / PO e-mail not sent: {why}"


def send_po_mail(cur, file_name: str, pdf: bytes, uploaded_by: str) -> tuple[bool, str]:
    """Returns (sent, message for the user)."""
    s = settings()
    msg = build_po_message(cur, file_name, pdf, uploaded_by, s["sender"] or s["user"], s["to"], s["cc"])
    ok, why = deliver(msg)
    if ok:
        return True, f"PO e-mailed to {', '.join(s['to'] + s['cc'])} (subject '{msg['Subject']}')."
    return False, f"PO e-mail not sent: {why}"


def send_test_mail(sent_by: str, to: str | None = None) -> tuple[bool, str]:
    s = settings()
    msg = EmailMessage()
    msg["Subject"] = "MT Indent - test e-mail"
    msg["From"] = s["sender"] or s["user"]
    msg["To"] = to or ", ".join(s["to"])
    if s["cc"] and not to:
        msg["Cc"] = ", ".join(s["cc"])
    msg.set_content(f"This is a test from the MT Indent app, sent by {sent_by}. "
                    "PO e-mails will arrive like this, with the PO PDF attached.")
    ok, why = deliver(msg)
    dest = to or ", ".join(s["to"] + s["cc"])
    try:
        from core import recipients
        recipients.log("test", "", dest, ok, why)
    except Exception:
        pass
    return ok, (f"Test e-mail sent to {dest}: {why}." if ok else f"Test e-mail failed: {why}")


def status_text() -> str:
    s = settings()
    pw = "set" if s["password"] else "missing"
    pw_len = len(s["password"])
    hint = "" if not s["password"] or pw_len == 16 else \
        f" (it is {pw_len} characters; a Gmail App password has 16)"
    return (f"Sender: {s['user'] or 'missing'} · password: {pw}{hint} · server: {s['host']}:{s['port']} · "
            f"to: {', '.join(s['to'])}" + (f" · cc: {', '.join(s['cc'])}" if s["cc"] else ""))
