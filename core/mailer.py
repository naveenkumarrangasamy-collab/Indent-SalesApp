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


def file_mime(name: str) -> str:
    """The PO file's type: a PDF, or a screenshot for customers without a PO (19 Nov)."""
    ext = str(name or "").rsplit(".", 1)[-1].casefold()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel", "csv": "text/csv"}.get(
        ext, "application/pdf")


def send_so_mail(cur, file_name: str, pdf: bytes, uploaded_by: str,
                 po_number: str = "", to_override: list[str] | None = None,
                 sample: bool = False, po_qty: dict | None = None) -> tuple[bool, str]:
    """SO placement e-mail with the customer's PO + SO as PDF and Excel.
    po_qty: this PO's qty per SKU, to show the PO qty and differences."""
    from core import recipients, reports
    s = settings()
    to = to_override or po_recipients(cur.header)
    h = cur.header
    subject = (("[SAMPLE] " if sample else "") + f"{h.customer} - SO placed - {h.store} - {cur.indent_id}"
               + (f" - PO {po_number}" if po_number else ""))
    # Attachments: the PO as PDF (the customer's own file) + the PO as Excel (17 Nov: user wants just these two).
    so = reports.so_files(cur, po_number, file_name, uploaded_by, po_qty)
    xlsx = [(f"PO_{cur.indent_id}{('_' + po_number) if po_number else ''}.xlsx", f[1], f[2])
            for f in so if f[0].endswith(".xlsx")]
    files = ([(file_name or "PO.pdf", pdf, file_mime(file_name))] if pdf
             else [f for f in so if f[0].endswith(".pdf")]) + xlsx
    text = (f"SO placed for {h.customer} / {h.store} ({h.city}), delivery {h.delivery_date}. "
            f"Indent {cur.indent_id}, PO {po_number or file_name}. The PO is attached as PDF and Excel.")
    msg = build_message(to, subject, reports.so_html(cur, po_number, file_name, uploaded_by, po_qty), text,
                        files, s["cc"])
    if sample:
        msg.replace_header("To", ", ".join(to))
        del msg["Cc"]
    ok, why = deliver(msg)
    recipients.log("sample-so" if sample else "so", cur.indent_id, to + ([] if sample else s["cc"]), ok, why)
    if ok:
        return True, f"SO / PO e-mail sent to {', '.join(to + s['cc'])}."
    return False, f"SO / PO e-mail not sent: {why}"


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


