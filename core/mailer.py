"""E-mail the customer's PO when it is uploaded (subject = customer name).

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


def send_po_mail(cur, file_name: str, pdf: bytes, uploaded_by: str) -> tuple[bool, str]:
    """Returns (sent, message for the user)."""
    s = settings()
    if not configured():
        return False, ("PO e-mail not sent: add smtp_user and smtp_password (a Gmail app password) "
                       "to the app secrets.")
    msg = build_po_message(cur, file_name, pdf, uploaded_by, s["sender"], s["to"], s["cc"])
    try:
        if s["port"] == 465:
            with smtplib.SMTP_SSL(s["host"], s["port"], timeout=30,
                                  context=ssl.create_default_context()) as smtp:
                smtp.login(s["user"], s["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s["host"], s["port"], timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(s["user"], s["password"])
                smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return False, ("PO e-mail not sent: the mail server refused the login. For Gmail use an "
                       "App password (not the normal password) in smtp_password.")
    except (smtplib.SMTPException, OSError) as e:
        return False, f"PO e-mail not sent: {e}"
    return True, f"PO e-mailed to {', '.join(s['to'] + s['cc'])}."
