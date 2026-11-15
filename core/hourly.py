"""Hourly indent e-mail to the ground team, 8:00 AM to 2:00 PM IST.

Each active recipient with Hourly_Indent = Y gets, for the delivery day(s),
the indents inside their scope: an overall SKU section and a customer-level
section in the body, plus 2 PDF + 2 Excel attachments.

Run every hour by the GitHub Actions workflow (.github/workflows/hourly-indent-mail.yml
-> scripts/hourly_mail.py), or from the Access page with "Send now".
Mail_Log keeps one line per e-mail, so a slot is never sent twice to a person.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core import config, indents, mailer, masters, recipients, reports


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
    people = recipients.hourly_list()
    if only:
        people = [r for r in people if r.email.lower() == only.lower()]
    if not people:
        return [{"to": "-", "status": "skipped", "detail": "no active recipients with the hourly e-mail"}]
    lines = indents.read_lines(fresh=True)
    m = masters.load_masters()
    days = [(slot.date() + timedelta(days=k)).isoformat() for k in delivery_offsets()]
    results = []
    for r in people:
        if not force and recipients.already_sent("hourly", key, r.email):
            results.append({"to": r.email, "status": "skipped", "detail": f"already sent for {key}"})
            continue
        html_parts, files, n = [], [], 0
        for day in days:
            rows = r.filter(reports.day_rows(lines, day))
            n += 0 if rows is None or rows.empty else rows["indent_id"].nunique()
            html_parts.append(reports.indent_mail_html(rows, m, day, label, r.name, r.scope_text()))
            files += reports.indent_mail_files(rows, m, day, label, r.scope_text())
        day_txt = " + ".join(reports.fmt_day(d) for d in days)
        subject = f"Indent update {slot:%I:%M %p} - delivery {day_txt} - {n} indent(s)".replace(" 0", " ", 1)
        text = (f"Indents for delivery {day_txt} as of {label} (scope: {r.scope_text()}). "
                "Open the HTML version or the attached PDF / Excel files.")
        msg = mailer.build_message([r.email], subject, "<hr>".join(html_parts), text, files)
        ok, why = mailer.deliver(msg)
        recipients.log("hourly", key, r.email, ok, why)
        results.append({"to": r.email, "status": "sent" if ok else "failed", "detail": why,
                        "indents": n})
    return results


def preview(day: str, scope: recipients.Recipient | None = None) -> list[tuple[str, bytes, str]]:
    """The 4 files as they would go out now (for downloading on the Access page)."""
    lines = indents.read_lines()
    rows = reports.day_rows(lines, day)
    if scope is not None:
        rows = scope.filter(rows)
    now = config.now_ist()
    return reports.indent_mail_files(rows, masters.load_masters(), day, slot_label(now),
                                     scope.scope_text() if scope else "everything")
