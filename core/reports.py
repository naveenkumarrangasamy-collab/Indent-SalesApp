"""Report data and files for the e-mails.

Hourly indent e-mail (ground team), per recipient scope:
  * overall indent  - the production view: total per city, parent SKU, variety,
                      lot, lot size and spec, across all customers
  * customer level  - customer > store > items
  as HTML in the body plus 4 attachments: 2 PDF + 2 Excel.

SO / PO e-mail (central team): the frozen indent with its PO, as PDF + Excel.
"""
from __future__ import annotations

import html
import io
from datetime import date, datetime

import pandas as pd

from core import config, indents, production_calc
from core.lots import lot_size
from core.masters import Masters
from core.models import fmt_num
from core.pdf_report import customers_pdf, table_pdf
from core.schema import STATUS_CANCELLED, STATUS_FROZEN

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STATUS_WORDS = {"Submitted": "Waiting for PO", "Locked": "Locked, waiting for PO", "Frozen": "PO received"}

OVERALL_COLS = production_calc.PRODUCTION_COLUMNS
CUSTOMER_COLS = ["Customer", "Store", "City", "Indent", "Status", "Parent SKU", "Customer SKU Name",
                 "Variety", "Lot", "Lot Size", "Qty", "Price", "Amount"]


def fmt_day(iso: str) -> str:
    try:
        return f"{date.fromisoformat(str(iso)[:10]):%a %d %b %Y}"
    except ValueError:
        return str(iso)


# ------------------------------------------------------------------ data

def day_rows(lines: pd.DataFrame, day: str) -> pd.DataFrame:
    """Current version of every live indent for this delivery date."""
    cur = indents.current_rows(lines) if lines is not None and not lines.empty else lines
    if cur is None or cur.empty:
        return pd.DataFrame(columns=list(lines.columns) if lines is not None else [])
    return cur[cur["delivery_date"].astype(str) == str(day)]


def state_at(lines: pd.DataFrame, when: datetime) -> pd.DataFrame:
    """Every indent as it stood at `when`: its latest version saved by then
    (indents created later are absent; deleted ones are dropped)."""
    if lines is None or lines.empty:
        return lines
    ts = pd.to_datetime(lines["submitted_at"], errors="coerce", utc=True)
    upto = lines[ts <= pd.Timestamp(when).tz_convert("UTC")]
    if upto.empty:
        return upto
    top = upto.groupby("indent_id")["version"].transform("max")
    cur = upto[upto["version"] == top]
    return cur[cur["status"] != STATUS_CANCELLED]


def customer_df(rows: pd.DataFrame) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame(columns=CUSTOMER_COLS)
    out = pd.DataFrame({
        "Customer": rows["customer"], "Store": rows["store"], "City": rows["city"],
        "Indent": rows["indent_id"], "Status": rows["status"].map(lambda s: STATUS_WORDS.get(s, s)),
        "Parent SKU": rows["parent_sku"], "Customer SKU Name": rows["customer_sku_name"],
        "Variety": rows["variety"].fillna(""), "Lot": rows["lot"],
        "Lot Size": rows["customer_sku_name"].map(lot_size),
        "Qty": rows["qty"].map(lambda q: int(q) if float(q).is_integer() else q),
        "Price": rows["price"].round(2), "Amount": rows["amount"].round(2)})
    return out.sort_values(["Customer", "Store", "Parent SKU", "Customer SKU Name"],
                           key=lambda s: s.astype(str).str.casefold()).reset_index(drop=True)


# ------------------------------------------------------------------ files

def xlsx(sheets: dict[str, pd.DataFrame], row_fill: dict | None = None) -> bytes:
    """`row_fill` {Status value: hex colour}: rows of a sheet with a 'Status' column get that fill."""
    from openpyxl.styles import Font, PatternFill
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            safe = "".join(ch for ch in name if ch not in "[]:*?/\\")[:31] or "Sheet"
            df.to_excel(xw, sheet_name=safe, index=False)
            ws = xw.sheets[safe]
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="FF1C6B49")
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)]) + 2
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(48, width)
            ws.freeze_panes = "A2"
            if row_fill and "Status" in df.columns:
                for i, stv in enumerate(df["Status"], start=2):
                    if stv in row_fill:
                        for cell in ws[i]:
                            cell.fill = PatternFill("solid", fgColor="FF" + row_fill[stv])   # FF = solid in every viewer
    return buf.getvalue()


def _html_table(df: pd.DataFrame, num: set[str]) -> str:
    if df is None or df.empty:
        return "<p style='color:#666'>No indents.</p>"
    head = "".join(f"<th style='padding:4px 6px;text-align:left'>{html.escape(str(c))}</th>"
                   for c in df.columns)
    body = []
    for i, rec in enumerate(df.itertuples(index=False)):
        bg = "#f3f7f5" if i % 2 else "#ffffff"
        cells = "".join(
            f"<td style='padding:3px 6px;{'text-align:right;' if c in num else ''}'>"
            f"{html.escape(fmt_num(v) if c in num and isinstance(v, (int, float)) else str(v))}</td>"
            for c, v in zip(df.columns, rec))
        body.append(f"<tr style='background:{bg}'>{cells}</tr>")
    return ("<table cellspacing='0' style='border-collapse:collapse;font-size:13px;border:1px solid #d0d7de'>"
            f"<tr style='background:#1c6b49;color:#fff'>{head}</tr>{''.join(body)}</table>")


# ------------------------------------------------------------------ hourly production e-mail

def production_view(rows: pd.DataFrame, m: Masters | None) -> pd.DataFrame:
    """Production sheet 'by spec size' (Variety dropped when empty)."""
    p = production_calc.production(rows, m)
    if not p.empty and not p["Variety"].astype(bool).any():
        p = p.drop(columns=["Variety"])
    return p


def make_ready_view(rows: pd.DataFrame, m: Masters | None) -> pd.DataFrame:
    """Make-ready list (City dropped when only one city)."""
    mr = production_calc.make_ready(rows, m)
    if len(mr["City"].unique()) <= 1:
        mr = mr.drop(columns=["City"])
    return mr


def by_customer_view(rows: pd.DataFrame, m: Masters | None) -> list[tuple[str, str, pd.DataFrame]]:
    """Production by customer, every block with item numbers (21 Nov)."""
    from core.production_calc import make_ready_by_customer, numbered
    return [(h, sub, numbered(df)) for h, sub, df in make_ready_by_customer(rows, m)]


def production_mail_files(rows: pd.DataFrame, m: Masters | None, day: str,
                          slot_label: str, scope: str = "everything", changes: pd.DataFrame | None = None,
                          po_diff: pd.DataFrame | None = None) -> list[tuple[str, bytes, str]]:
    """21 Nov (user): the hourly e-mail carries only Production by customer (one PDF,
    one customer per page, item numbers). No make-ready / spec-size tables, no Excel."""
    stamp = str(day).replace("-", "")
    hh = slot_label.split(",")[0].replace(":", "").replace(" ", "")
    blocks = by_customer_view(rows, m)
    if not blocks:
        return []
    pdf = customers_pdf("Production by customer", [f"Delivery {fmt_day(day)} - as of {slot_label} - {scope}"],
                        blocks, footer=f"MT Indent - by customer - {slot_label}")
    return [(f"Production_by_customer_{stamp}_{hh}.pdf", pdf, "application/pdf")]


# 21 Nov: hourly mail palette (one place to change it)
MAIL = {"head": "#e4f0fb", "band": "#e4f0fb", "title": "#000000", "bg": "#ffffff", "zebra": "#ffffff",
        "total": "#ffffff", "line": "#d9e2ea", "text": "#000000"}   # 21 Nov: one very light blue, black text


def _mail_table(df: pd.DataFrame) -> str:
    """Centred, roomy table for the hourly mail: names left, everything else centred,
    a bold Total row, 'to fill' / 'not in New tab' in amber."""
    left = {"Customer SKU Name"}
    th = "".join(
        f"<th style='padding:9px 10px;font-size:13px;font-weight:600;color:{MAIL['text']};background:{MAIL['head']};"
        f"text-align:{'left' if c in left else 'center'};white-space:nowrap'>{html.escape(str(c))}</th>"
        for c in df.columns)
    body = []
    for i, rec in enumerate(df.itertuples(index=False)):
        vals = list(rec)
        total = any(str(v).strip().casefold() == "total" for v in vals[:3])
        bg = MAIL["total"] if total else (MAIL["zebra"] if i % 2 else "#ffffff")
        tds = []
        for c, v in zip(df.columns, vals):
            txt = fmt_num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
            color = MAIL["text"]
            tds.append(f"<td style='padding:8px 10px;font-size:14px;border-bottom:1px solid #e3e8e5;"
                       f"text-align:{'left' if c in left else 'center'};color:{color};"
                       f"{'font-weight:700;border-top:1px solid #b8c7d6;' if total else ''}'>{html.escape(txt)}</td>")
        body.append(f"<tr style='background:{bg}'>{''.join(tds)}</tr>")
    return ("<table role='presentation' cellspacing='0' cellpadding='0' align='center' "
            f"width='100%' style='border-collapse:collapse;width:100%;margin:0 auto;border:1px solid {MAIL['line']};border-radius:6px;"
            f"font-family:Arial,Helvetica,sans-serif'><tr>{th}</tr>{''.join(body)}</table>")


def production_mail_html(rows: pd.DataFrame, m: Masters | None, day: str,
                         slot_label: str, name: str = "", scope: str = "everything",
                         changes: pd.DataFrame | None = None, po_diff: pd.DataFrame | None = None,
                         since: str = "") -> str:
    """21 Nov: Production by customer only, centred and easy to read on phone and laptop."""
    n = rows["indent_id"].nunique() if rows is not None and not rows.empty else 0
    waiting = rows[rows["status"] != STATUS_FROZEN]["indent_id"].nunique() if n else 0
    blocks = by_customer_view(rows, m) if n else []
    items = sum(int((df["#"] != "").sum()) for _, _, df in blocks)
    font = "font-family:Arial,Helvetica,sans-serif"
    tiles = "".join(
        f"<td align='center' style='padding:10px 18px'><div style='font-size:24px;font-weight:700;color:{MAIL['title']}'>"
        f"{v}</div><div style='font-size:12px;color:#000;text-transform:uppercase;letter-spacing:.04em'>{k}</div></td>"
        for k, v in (("Indents", n), ("Customers", len(blocks)), ("Items", items), ("Waiting for PO", waiting)))
    out = [f"<div style='background:{MAIL['bg']};padding:24px 8px;{font}'>",
           "<table role='presentation' align='center' cellspacing='0' cellpadding='0' "
           "style='max-width:1000px;width:100%;margin:0 auto;background:#ffffff;border-radius:10px;"
           f"border:1px solid {MAIL['line']}'>",
           f"<tr><td align='center' style='background:{MAIL['band']};color:{MAIL['text']};padding:18px 16px;border-radius:10px 10px 0 0'>"
           "<div style='font-size:22px;font-weight:700'>Production by customer</div>"
           f"<div style='font-size:15px;margin-top:4px'>Delivery {fmt_day(day)} &nbsp;·&nbsp; as of {slot_label}</div>"
           "</td></tr>",
           f"<tr><td align='center' style='padding:14px 16px 4px;font-size:14px;color:#000'>"
           f"Hello{(' ' + html.escape(name)) if name else ''}, here is the production by customer "
           f"({html.escape(scope)}). The same is attached as PDF.</td></tr>",
           f"<tr><td align='center'><table role='presentation' align='center'><tr>{tiles}</tr></table></td></tr>"]
    if not blocks:
        out.append("<tr><td align='center' style='padding:20px;color:#000'>No indents.</td></tr>")
    for head, sub, df in blocks:
        out.append(f"<tr><td align='center' style='padding:22px 12px 6px'>"
                   f"<div style='font-size:19px;font-weight:700;color:{MAIL['title']}'>{html.escape(head)}</div>"
                   f"<div style='font-size:13px;color:#000;margin:3px 0 10px'>{html.escape(sub)}</div>"
                   f"{_mail_table(df)}</td></tr>")
    out.append("<tr><td align='center' style='padding:22px 12px;font-size:12px;color:#000'>"
               "Sent by the MT Indent app.</td></tr></table></div>")
    return "".join(out)


# ------------------------------------------------------------------ hourly batching mail (26 Nov)

def po_quantities(lines: pd.DataFrame) -> tuple[dict, set, list[dict]]:
    """{(indent_id, sku key): PO qty or None = not on the PO}, the indents whose PO has qty per item
    (PO_Item_Map links used), and the PO-only items (on a PO, not on the indent)."""
    from core.models import IndentLine
    from core.sheets import SheetError
    try:
        po = indents.read_po_freeze()
    except SheetError:
        return {}, set(), []
    out, ids, extras = {}, set(), []
    if lines is None or lines.empty:
        return out, ids, extras
    for iid, g in lines.groupby("indent_id"):
        info = indents.po_info(po, iid)
        if info["qty"] is None:
            continue
        ids.add(iid)
        first = g.iloc[0]
        items = [IndentLine(parent_sku=r["parent_sku"], customer_sku_name=r["customer_sku_name"],
                            variety=r.get("variety", ""), lot=r.get("lot", ""), qty=r["qty"])
                 for r in g.to_dict("records")]
        for r in indents.po_vs_indent(items, info, customer=str(first["customer"])):
            if r["indent_qty"] is not None:
                out[(iid, " ".join(str(r["customer_sku_name"]).split()).casefold())] = r["po_qty"]
            elif r["po_qty"]:
                extras.append({"day": first["delivery_date"], "City": first["city"], "Customer": first["customer"],
                               "Delivery point": first["store"], "Customer SKU Name": r["customer_sku_name"],
                               "PO qty": r["po_qty"]})
    return out, ids, extras


def batching_view(rows: pd.DataFrame, m: Masters | None, day: str) -> pd.DataFrame:
    """The Batching sheet of one delivery day (as on the page): indent qty, PO qty, difference, status."""
    pc = production_calc
    if rows is None or rows.empty:
        return pd.DataFrame()
    po_qty, po_ids, extras = po_quantities(rows)
    return pc.with_po(pc.batching(rows, m), po_qty, po_ids, [e for e in extras if e["day"] == day])


_ORDER = {"PO lower": 0, "Not on PO": 1, "Not on indent": 2, "PO higher": 3, "No PO yet": 4, "Match": 5}


def _spec_missing(v) -> bool:
    t = str(v or "").strip().casefold()
    return not t or t == "-" or t.startswith(production_calc.NOT_IN_BASE.casefold()) \
        or t.startswith(production_calc.PENDING.casefold())


def _q(v, sign: bool = False) -> str:
    if v is None or v == "" or (not isinstance(v, str) and pd.isna(v)):
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return ("+" if sign and f > 0 else "") + fmt_num(f)


def _batch_table(df: pd.DataFrame) -> str:
    left = {"Customer SKU Name", "Spec"}
    th = "".join(
        f"<th style='padding:8px 9px;font-size:13px;font-weight:600;color:#000;background:{MAIL['head']};"
        f"text-align:{'left' if c in left else 'center'};white-space:nowrap'>{html.escape(str(c))}</th>"
        for c in df.columns)
    body = []
    for rec in df.to_dict("records"):
        tds = []
        for c in df.columns:
            v = rec[c]
            fill = ""
            if c == "Status" and v in production_calc.STATUS_COLOURS:
                fill = f"background:#{production_calc.STATUS_COLOURS[v]};"
            tds.append(f"<td style='padding:7px 9px;font-size:13px;border-bottom:1px solid #e3e8e5;color:#000;"
                       f"text-align:{'left' if c in left else 'center'};{fill}'>{html.escape(str(v))}</td>")
        body.append(f"<tr>{''.join(tds)}</tr>")
    return ("<table role='presentation' cellspacing='0' cellpadding='0' align='center' width='100%' "
            f"style='border-collapse:collapse;width:100%;border:1px solid {MAIL['line']};"
            f"font-family:Arial,Helvetica,sans-serif'><tr>{th}</tr>{''.join(body)}</table>")


def batching_blocks(view: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """One block per city · customer · delivery point; rows needing attention first, numbered."""
    if view is None or view.empty:
        return []
    many = view["City"].nunique() > 1
    has_var = "Variety" in view.columns and view["Variety"].astype(str).str.strip().astype(bool).any()
    out = []
    for (city, cust, point), part in view.groupby(["City", "Customer", "Delivery point"], sort=False):
        part = part.assign(_o=part["Status"].map(lambda x: _ORDER.get(x, 9))).sort_values("_o", kind="stable")
        df = pd.DataFrame({"Customer SKU Name": part["Customer SKU Name"]})
        if has_var:
            df["Variety"] = part["Variety"].values
        df["Spec"] = [("spec missing" if _spec_missing(x) else x) for x in part["Spec"]]
        df["Indent"] = [_q(x) for x in part["Indent qty"]]
        df["PO"] = [_q(x) for x in part["PO qty"]]
        df["Diff"] = [_q(x, sign=True) for x in part["Difference"]]
        df["Status"] = part["Status"].values
        head = " · ".join(([city] if many else []) + [cust] + ([point] if str(point) != str(cust) else []))
        out.append((head, production_calc.numbered(df.reset_index(drop=True))))
    return out


def batching_counts(view: pd.DataFrame) -> list[tuple[str, int]]:
    if view is None or view.empty:
        return [("Lines", 0)]
    st_ = view["Status"].value_counts()
    return [("Lines", len(view)), ("PO matched", int(st_.get("Match", 0))),
            ("Short / not on PO", int(st_.get("PO lower", 0) + st_.get("Not on PO", 0))),
            ("No PO yet", int(st_.get("No PO yet", 0))),
            ("Spec missing", int(sum(_spec_missing(x) for x in view["Spec"])))]


def batching_mail_html(view: pd.DataFrame, day: str, slot_label: str, name: str = "",
                       scope: str = "everything") -> str:
    """26 Nov (user): the hourly e-mail carries only the Batching sheet."""
    font = "font-family:Arial,Helvetica,sans-serif"
    tiles = "".join(
        f"<td align='center' style='padding:10px 16px'><div style='font-size:22px;font-weight:700;color:#000'>"
        f"{v}</div><div style='font-size:11px;color:#000;text-transform:uppercase;letter-spacing:.04em'>{k}</div></td>"
        for k, v in batching_counts(view))
    out = [f"<div style='background:#ffffff;padding:24px 8px;{font}'>",
           "<table role='presentation' align='center' cellspacing='0' cellpadding='0' "
           f"style='max-width:1000px;width:100%;margin:0 auto;background:#ffffff;border-radius:10px;border:1px solid {MAIL['line']}'>",
           f"<tr><td align='center' style='background:{MAIL['band']};color:#000;padding:18px 16px;border-radius:10px 10px 0 0'>"
           "<div style='font-size:22px;font-weight:700'>Batching sheet</div>"
           f"<div style='font-size:15px;margin-top:4px'>Delivery {fmt_day(day)} &nbsp;·&nbsp; as of {slot_label}</div></td></tr>",
           f"<tr><td align='center' style='padding:14px 16px 4px;font-size:14px;color:#000'>"
           f"Hello{(' ' + html.escape(name)) if name else ''}, here is the batching sheet ({html.escape(scope)}). "
           "The full sheet is attached as Excel.</td></tr>",
           f"<tr><td align='center'><table role='presentation' align='center'><tr>{tiles}</tr></table></td></tr>"]
    blocks = batching_blocks(view)
    if not blocks:
        out.append("<tr><td align='center' style='padding:20px;color:#000'>No indents.</td></tr>")
    for head, df in blocks:
        out.append(f"<tr><td align='center' style='padding:20px 12px 4px'>"
                   f"<div style='font-size:17px;font-weight:700;color:#000;margin-bottom:8px'>{html.escape(head)}</div>"
                   f"{_batch_table(df)}</td></tr>")
    out.append("<tr><td align='center' style='padding:22px 12px;font-size:12px;color:#000'>"
               "Red = PO lower or not on the PO · yellow = PO higher · orange = not on the indent. "
               "Sent by the MT Indent app.</td></tr></table></div>")
    return "".join(out)


def batching_mail_files(view: pd.DataFrame, day: str, slot_label: str) -> list[tuple[str, bytes, str]]:
    if view is None or view.empty:
        return []
    stamp = str(day).replace("-", "")
    hh = slot_label.split(",")[0].replace(":", "").replace(" ", "")
    df = production_calc.numbered(view.reset_index(drop=True))
    for c in ("Indent qty", "PO qty", "Difference"):
        df[c] = [_q(x, sign=c == "Difference") for x in df[c]]
    data = xlsx({"Batching": df}, row_fill=production_calc.STATUS_COLOURS)
    return [(f"Batching_{stamp}_{hh}.xlsx", data,
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]


# ------------------------------------------------------------------ SO / PO

def _num(df: pd.DataFrame) -> pd.DataFrame:
    from core.production_calc import numbered
    return numbered(df)


def so_df(cur, po_qty: dict | None = None) -> pd.DataFrame:
    """The SO items. With po_qty (this PO's qty per SKU), adds PO qty and the
    difference (PO - indent) per item, and items that are only on the PO."""
    df = pd.DataFrame([{"Parent SKU": x.parent_sku, "Customer SKU Name": x.customer_sku_name,
                        "Variety": x.variety, "Lot": x.lot, "Lot Size": lot_size(x.customer_sku_name),
                        "Qty": int(x.qty) if float(x.qty).is_integer() else x.qty,
                        "Price": round(x.price, 2), "Amount": round(x.amount, 2)} for x in cur.lines])
    if po_qty is None:
        return _num(df)
    by = {str(k).strip().casefold(): (k, float(v)) for k, v in po_qty.items() if v is not None}
    po, diff = [], []
    for x in cur.lines:
        hit = by.pop(x.customer_sku_name.strip().casefold(), None)
        po.append("" if hit is None else fmt_num(hit[1]))
        d = (hit[1] if hit else 0.0) - float(x.qty)
        diff.append("" if abs(d) < 1e-9 else ("+" if d > 0 else "") + fmt_num(d)
                    + (" (not on PO)" if hit is None else ""))
    df["PO qty"], df["Diff"] = po, diff
    extra = [{"Parent SKU": "", "Customer SKU Name": k, "Variety": "", "Lot": "", "Lot Size": "", "Qty": 0,
              "Price": 0.0, "Amount": 0.0, "PO qty": fmt_num(v), "Diff": "+" + fmt_num(v) + " (not on indent)"}
             for k, v in by.values()]
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True) if extra else df
    return _num(df)


def so_info(cur, po_number: str, po_file: str, uploaded_by: str) -> list[tuple[str, str]]:
    h = cur.header
    return [("Indent", cur.indent_id), ("PO number", po_number or "-"), ("PO file", po_file or "-"),
            ("Customer", h.customer), ("Store", h.store), ("City", h.city),
            ("Delivery", f"{fmt_day(h.delivery_date)} at {h.expected_time}"),
            ("Total qty", fmt_num(sum(x.qty for x in cur.lines))),
            ("Total amount", f"Rs {sum(x.amount for x in cur.lines):,.2f}"),
            ("PO uploaded by", uploaded_by),
            ("PO uploaded at", config.now_ist().strftime("%d %b %Y %I:%M %p"))]


def so_files(cur, po_number: str, po_file: str, uploaded_by: str,
             po_qty: dict | None = None) -> list[tuple[str, bytes, str]]:
    info = so_info(cur, po_number, po_file, uploaded_by)
    df = so_df(cur, po_qty)
    pdf = table_pdf(f"SO placed - {cur.header.customer} - {cur.header.store}",
                    [f"{k}: {v}" for k, v in info], df, footer=f"MT Indent - {cur.indent_id}")
    x = xlsx({"SO": pd.DataFrame(info, columns=["Field", "Value"]), "Items": df})
    return [(f"SO_{cur.indent_id}.pdf", pdf, "application/pdf"), (f"SO_{cur.indent_id}.xlsx", x, XLSX)]


def so_html(cur, po_number: str, po_file: str, uploaded_by: str, po_qty: dict | None = None) -> str:
    info = so_info(cur, po_number, po_file, uploaded_by)
    df = so_df(cur, po_qty)
    n_diff = int((df["Diff"].astype(str) != "").sum()) if "Diff" in df.columns else 0
    rows = "".join(f"<tr><td style='padding:2px 10px 2px 0;color:#555'>{html.escape(k)}</td>"
                   f"<td><b>{html.escape(str(v))}</b></td></tr>" for k, v in info)
    return (f"<p>SO placed for <b>{html.escape(cur.header.customer)}</b> · "
            f"{html.escape(cur.header.store)}. "
            + (f"<b style='color:#b45309'>{n_diff} item(s) on this PO differ from the indent</b> "
               "(see Diff).</p>" if n_diff else "The customer's PO matches the indent.</p>")
            + f"<table>{rows}</table><br>"
            + _html_table(df, {"Qty", "Price", "Amount", "PO qty"})
            + "<p style='color:#888;font-size:12px'>Attached: the customer's PO, and the SO as PDF and "
              "Excel. Sent by the MT Indent app.</p>")
