"""Hourly production e-mail to the ground team, 8:00 AM to 2:00 PM IST.

Each active ground-team address gets, for the delivery day(s), the
production report of the indents in its cities / customers (all customers
clubbed, with boxes) in the body, plus the same report as PDF and Excel.

Run every hour by the GitHub Actions workflow (.github/workflows/hourly-indent-mail.yml
-> scripts/hourly_mail.py), or from the Access page with "Send now".
Mail_Log keeps one line per e-mail, so a slot is never sent twice to a person.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core import boxes, config, indents, mailer, masters, recipients, reports


def hours() -> tuple[int, int]:
    try:
        a, b = config.get("hourly_mail_from", 8), config.get("hourly_mail_to", 14)
        return int(a), int(b)
    except (TypeError, ValueError):
        return 8, 14


def delivery_offsets() -> list[int]:
    """Which delivery days the hourly e-mail covers: 0 = today (default), 1 = tomorrow."""
    v = config.get("hourly_mail_days", [0])
    if isinstance(v, (int, float, str)):
        v = [v]
    try:
        return sorted({int(x) for x in v}) or [0]
    except (TypeError, ValueError):
        return [0]


def slot_for(now: datetime) -> datetime | None:
    """The hour this run belongs to, or None outside 8 AM-2 PM. A scheduled
    run that starts up to 40 minutes late still counts for the last hour."""
    first, last = hours()
    h = now.replace(minute=0, second=0, microsecond=0)
    if first <= now.hour <= last:
        return h
    if now.hour == last + 1 and now.minute < 40:
        return h - timedelta(hours=1)
    return None


def slot_label(slot: datetime) -> str:
    return f"{slot:%I:%M %p}, {slot:%a %d %b}".lstrip("0")


def run(now: datetime | None = None, force: bool = False, only: str | None = None) -> list[dict]:
    """Send this hour's e-mails. force: send even outside the window or if
    already sent (used by "Send now"). only: one recipient's e-mail."""
    now = now or config.now_ist()
    slot = slot_for(now)
    if slot is None:
        if not force:
            return [{"to": "-", "status": "skipped", "detail": "outside the 8 AM-2 PM window"}]
        slot = now.replace(minute=0, second=0, microsecond=0)
    key = f"{slot:%Y-%m-%d %H:%M}"
    label = slot_label(slot)
    people = [r for r in recipients.ground() if r.active]
    if only:
        people = [r for r in people if r.email.lower() == only.lower()]
    if not people:
        return [{"to": "-", "status": "skipped", "detail": "no active recipients with the hourly e-mail"}]
    lines = indents.read_lines(fresh=True)
    m = masters.load_masters()
    rules = boxes.read_rules()
    days = [(slot.date() + timedelta(days=k)).isoformat() for k in delivery_offsets()]
    results = []
    for r in people:
        if not force and recipients.already_sent("hourly", key, r.email):
            results.append({"to": r.email, "status": "skipped", "detail": f"already sent for {key}"})
            continue
        ok, why, n = _send_one([r.email], r, lines, m, rules, days, slot, label)
        recipients.log("hourly", key, r.email, ok, why)
        results.append({"to": r.email, "status": "sent" if ok else "failed", "detail": why, "indents": n})
    return results


def _send_one(to: list[str], scope: recipients.Recipient | None, lines, m, rules, days, slot, label,
              sample: bool = False) -> tuple[bool, str, int]:
    html_parts, files, n = [], [], 0
    scope_txt = scope.scope_text() if scope else "everything"
    for day in days:
        rows = reports.day_rows(lines, day)
        if scope is not None:
            rows = scope.filter(rows)
        n += 0 if rows is None or rows.empty else rows["indent_id"].nunique()
        html_parts.append(reports.production_mail_html(rows, m, rules, day, label,
                                                       scope.name if scope else "", scope_txt))
        files += reports.production_mail_files(rows, m, rules, day, label, scope_txt)
    day_txt = " + ".join(reports.fmt_day(d) for d in days)
    subject = (("[SAMPLE] " if sample else "") + f"Production {slot:%I:%M %p} - delivery {day_txt} - "
               f"{n} indent(s)").replace(" 0", " ", 1)
    text = (f"Production for delivery {day_txt} as of {label} ({scope_txt}). "
            "Open the HTML version or the attached PDF / Excel.")
    msg = mailer.build_message(to, subject, "<hr>".join(html_parts), text, files)
    ok, why = mailer.deliver(msg)
    return ok, why, n


def send_sample(to: str, scope: recipients.Recipient | None = None) -> tuple[bool, str]:
    """Send this hour's production e-mail now to one address (to check how it looks)."""
    now = config.now_ist()
    slot = now.replace(minute=0, second=0, microsecond=0)
    days = [(slot.date() + timedelta(days=k)).isoformat() for k in delivery_offsets()]
    ok, why, n = _send_one([to], scope, indents.read_lines(fresh=True), masters.load_masters(),
                           boxes.read_rules(), days, slot, slot_label(slot), sample=True)
    recipients.log("sample-hourly", f"{slot:%Y-%m-%d %H:%M}", to, ok, why)
    return ok, (f"Sample production e-mail sent to {to} ({n} indents)." if ok
                else f"Sample e-mail not sent: {why}")


def preview(day: str, scope: recipients.Recipient | None = None) -> list[tuple[str, bytes, str]]:
    """The 2 files as they would go out now (for downloading on the Access page)."""
    rows = reports.day_rows(indents.read_lines(), day)
    if scope is not None:
        rows = scope.filter(rows)
    return reports.production_mail_files(rows, masters.load_masters(), boxes.read_rules(), day,
                                         slot_label(config.now_ist()),
                                         scope.scope_text() if scope else "everything")
