"""Hourly tracker (19 Nov, v3, approved by the user): one view, customer by customer.
Every indent of the delivery day with every item; columns every 30 minutes from 8 AM
(+ Now) and a last "PO vs indent" column. Built from the saved versions in Indent_Lines
(core.tracking.grid), so nothing extra is recorded.

Cells: qty, and only in the half hour it changed the change in brackets — green (+46)
up, red (−50) down, yellow (±) changed and back. After that the qty stays yellow (it
went up) or red (it went down) until the PO is uploaded; from the PO on it is plain."""
from __future__ import annotations

from datetime import date, timedelta
from html import escape

import pandas as pd
import streamlit as st

from core import config, indents, reports, tracking
from core.auth import User
from core.sheets import SheetError
from pages_src import common

ALL_C = "All cities"

CSS = """<style>
.tk{width:100%;border-collapse:collapse;font-size:13px;table-layout:auto}
.tk th{font-weight:600;color:#555;padding:6px 6px;border-bottom:1px solid #bbb;text-align:center;white-space:nowrap;
 position:sticky;top:0;background:#fff}
.tk th.l,.tk td.l{text-align:left}
.tk td{padding:5px 6px;border-bottom:1px solid #eee;text-align:center;white-space:nowrap}
.tk td.l{white-space:normal;min-width:220px}
.tk .up{color:#1a7f37;font-weight:700}.tk .down{color:#cf222e;font-weight:700}.tk .swing{color:#b8860b;font-weight:700}
.tk .yellow{color:#b8860b;font-weight:700}.tk .red{color:#cf222e;font-weight:700}
.tk .m{color:#aaa}
.tk tr.c0 td{background:#e7f0fb;color:#0b4f9c;font-weight:700;text-align:left;font-size:14px}
.tk tr.c1 td{background:#f3f4f6;font-weight:600;text-align:left;white-space:normal}
.tk td.po{border-left:1px solid #ccc}
.tk .ok{background:#e6f4ea;color:#1a7f37;border-radius:6px;padding:1px 6px}
.tk .bad{background:#fde8e8;color:#cf222e;border-radius:6px;padding:1px 6px}
.tk-legend{font-size:12px;color:#666;margin:4px 0 8px}
</style>"""


def _fmt_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    diff = (d - config.now_ist().date()).days
    word = {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(diff, "")
    return f"{word} · {d:%a %d %b}" if word else f"{d:%a %d %b}"


def _hm(ts) -> str:
    if ts is None or pd.isna(ts):
        return ""
    t = pd.Timestamp(ts).tz_convert(config.IST)
    day = t.date() != config.now_ist().date()
    return t.strftime("%d %b %I:%M %p" if day else "%I:%M %p").replace(" 0", " ").lstrip("0")


def _head(b: dict) -> str:
    bits = [b["store"], b["indent"], f"entered {_hm(b['entered'])}"]
    if b["edited"]:
        bits.append("edited " + ", ".join(_hm(t) for t in b["edited"]))
    if b["frozen_at"] is not None:
        bits.append(f"PO {_hm(b['frozen_at'])} · tracking stopped")
    bits.append(f"{b['items']} item(s) · {fmt(b['qty'])} qty")
    bits.append(f"{b['changes']} change(s)" if b["changes"] else "no change")
    return " · ".join(bits)


def fmt(q) -> str:
    return f"{q:,.0f}" if float(q).is_integer() else f"{q:,.2f}"


def _table(blocks: list[dict], labels: list[str], only_changed: bool) -> str:
    n = len(labels) + 2
    out = [CSS, "<div style='overflow-x:auto'><table class='tk'><tr><th class='l'>Customer · store · item</th>"]
    out += [f"<th>{escape(lbl)}</th>" for lbl in labels]
    out.append("<th class='po'>PO vs indent</th></tr>")
    last = None
    for b in blocks:
        rows = [r for r in b["rows"] if r["changed"]] if only_changed else b["rows"]
        if only_changed and not rows:
            continue
        if b["customer"] != last:
            out.append(f"<tr class='c0'><td colspan='{n}'>{escape(b['customer'])}</td></tr>")
            last = b["customer"]
        out.append(f"<tr class='c1'><td colspan='{n}'>{escape(_head(b))}</td></tr>")
        for no, r in enumerate(rows, start=1):
            tds = []
            for q, ch, kind in r["cells"]:
                if q == "·":
                    tds.append("<td class='m'>·</td>")
                elif kind in ("up", "down", "swing"):
                    tds.append(f"<td>{q} <span class='{kind}'>{escape(ch)}</span></td>")
                else:
                    tds.append(f"<td class='{kind}'>{q}</td>")
            po = (f"<span class='{r['po_kind']}'>{escape(r['po'])}</span>" if r["po_kind"]
                  else f"<span class='m'>{escape(r['po'])}</span>")
            nm = (f"<span class='bad'>{escape(r['name'])}</span>" if r.get("po_only") else escape(r["name"]))
            out.append(f"<tr><td class='l'><span style='color:#8a8f98;font-size:11px;margin-right:6px'>{no}</span>{nm}</td>{''.join(tds)}<td class='po'>{po}</td></tr>")
    out.append("</table></div>")
    return "".join(out)


def _frame(blocks: list[dict], labels: list[str]) -> pd.DataFrame:
    """Flat table for Excel / PDF: the cell text with its change, e.g. '459 (+46)'."""
    recs = []
    for b in blocks:
        for no, r in enumerate(b["rows"], start=1):
            d = {"#": no, "Customer": b["customer"], "Store": b["store"], "Indent": b["indent"],
                 "Customer SKU Name": r["name"]}
            for lbl, (q, ch, _) in zip(labels, r["cells"]):
                d[lbl] = f"{q} {ch}".strip()
            d["PO vs indent"] = r["po"]
            recs.append(d)
    return pd.DataFrame(recs, columns=["#", "Customer", "Store", "Indent", "Customer SKU Name"] + labels + ["PO vs indent"])


def _pdf(blocks: list[dict], labels: list[str], day: str) -> bytes:
    from core.pdf_report import sections_pdf
    secs = []
    for cust in dict.fromkeys(b["customer"] for b in blocks):
        part = [b for b in blocks if b["customer"] == cust]
        df = _frame(part, labels).drop(columns=["Customer"])
        secs.append((cust, " | ".join(_head(b) for b in part), df))
    return sections_pdf("Hourly tracker", [f"Delivery {_fmt_day(day)} - as of {_hm(config.now_ist())}",
                                           "(+n) / (-n) = changed in that half hour; (±) = changed and back"],
                        secs, footer="MT Indent - hourly tracker", page_each=True)


def render(user: User) -> None:
    common.show_flash()
    if not (user.is_owner or getattr(user, "is_warehouse", False)):
        st.error("The hourly tracker is for the owner and the warehouse team.")
        return
    try:
        lines = indents.read_lines()
        po = indents.read_po_freeze()
    except SheetError as e:
        common.sheet_error(e, "Indents could not be loaded.")
        return
    allowed = set(indents.visible_to(indents.summary(lines), user)["indent_id"]) if not lines.empty else set()
    lines = lines[lines["indent_id"].isin(allowed)] if not lines.empty else lines

    head = st.columns([3, 1, 1], vertical_alignment="bottom")
    head[0].markdown("### Hourly tracker")
    head[0].caption("Every half hour from 8 AM · tracking stops for an indent once its PO is uploaded")

    today = config.now_ist().date()
    days = [(today + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    if st.session_state.get("tk_day") not in days:
        st.session_state["tk_day"] = today.isoformat()
    day = st.pills("Delivery date", days, key="tk_day", format_func=_fmt_day) or today.isoformat()
    on_day = lines[lines["delivery_date"].astype(str) == day] if not lines.empty else lines
    if not on_day.empty:
        on_day = on_day[on_day["indent_id"].isin(set(indents.summary(on_day).query("status != 'Cancelled'")["indent_id"]))]
    cities = sorted(set(on_day["city"].astype(str))) if not on_day.empty else []
    if len(cities) > 1:
        c = st.pills("City", [ALL_C] + cities, default=ALL_C, key="tk_city")
        if c and c != ALL_C:
            on_day = on_day[on_day["city"] == c]
    if on_day.empty:
        st.info("No indents for this delivery date.")
        return
    counts = on_day.drop_duplicates("indent_id")["customer"].value_counts()
    opts = [f"All · {int(counts.sum())}"] + [f"{k} · {n}" for k, n in sorted(counts.items())]
    cu = st.pills("Customer", opts, default=opts[0], key=f"tk_cust_{day}")
    if cu and not cu.startswith("All · "):
        on_day = on_day[on_day["customer"] == cu.rsplit(" · ", 1)[0]]
    only = st.toggle("Only changed items", key="tk_only")

    pts = [(lbl, t) for lbl, t in tracking.points(day) if t is not None]
    if not pts:
        st.info("Tracking starts at 8 AM on the delivery day.")
        return
    labels = [lbl.replace(" AM", "").replace(" PM", "") if lbl != "Now" else "Now" for lbl, _ in pts]
    scoped = lines[lines["indent_id"].isin(set(on_day["indent_id"]))]
    blocks = tracking.grid(scoped, po, day, pts)
    if not blocks:
        st.info("No indents for these filters.")
        return
    stamp = day.replace("-", "")
    head[1].download_button("PDF", lambda: _pdf(blocks, labels, day), file_name=f"Hourly_tracker_{stamp}.pdf",
                            mime="application/pdf", icon=":material/picture_as_pdf:", width="stretch",
                            on_click="ignore", key="tk_pdf")
    head[2].download_button("Excel", lambda: reports.xlsx({"Hourly tracker": _frame(blocks, labels)}),
                            file_name=f"Hourly_tracker_{stamp}.xlsx", mime=reports.XLSX,
                            icon=":material/download:", width="stretch", on_click="ignore", key="tk_xlsx")
    st.markdown("<div class='tk-legend'><b style='color:#1a7f37'>(+ green)</b> / <b style='color:#cf222e'>(− red)</b>"
                " only in the half hour it changed · then <b style='color:#b8860b'>yellow</b> = went up, "
                "<b style='color:#cf222e'>red</b> = went down, until the PO · <b style='color:#b8860b'>(±)</b> "
                "changed and back · · = not entered yet</div>", unsafe_allow_html=True)
    html = _table(blocks, labels, only)
    if only and "class='c1'" not in html:
        st.success("No item changed for these filters.")
    else:
        st.markdown(html, unsafe_allow_html=True)
