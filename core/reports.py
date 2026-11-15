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
from core.pdf_report import sections_pdf, table_pdf
from core.schema import STATUS_CANCELLED, STATUS_FROZEN

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STATUS_WORDS = {"Submitted": "Waiting for PO", "Frozen": "PO received"}

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


def overall_df(rows: pd.DataFrame, m: Masters | None) -> pd.DataFrame:
    if rows is None or rows.empty:
        return pd.DataFrame(columns=OVERALL_COLS)
    return production_calc.production(rows, m)


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

def xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    from openpyxl.styles import Font, PatternFill
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            safe = "".join(ch for ch in name if ch not in "[]:*?/\\")[:31] or "Sheet"
            df.to_excel(xw, sheet_name=safe, index=False)
            ws = xw.sheets[safe]
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="1C6B49")
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(300)]) + 2
                ws.column_dimensions[ws.cell(1, i).column_letter].width = min(48, width)
            ws.freeze_panes = "A2"
    return buf.getvalue()


def _customer_sections(cdf: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    sections = []
    for cust, part in cdf.groupby("Customer", sort=True):
        stores = part["Store"].nunique()
        sections.append((f"{cust}", f"{stores} store(s) - total qty {fmt_num(part['Qty'].sum())} - "
                                    f"Rs {part['Amount'].sum():,.0f}", None))
        for (store, iid, status), sp in part.groupby(["Store", "Indent", "Status"], sort=True):
            sections.append((f"   {store}", f"{iid} - {status} - {sp['City'].iloc[0]}",
                             sp[["Parent SKU", "Customer SKU Name", "Variety", "Lot", "Lot Size",
                                 "Qty", "Price", "Amount"]].reset_index(drop=True)))
    return sections   # customer headings carry no table (None)


def indent_mail_files(rows: pd.DataFrame, m: Masters | None, day: str, slot_label: str,
                      scope: str = "everything") -> list[tuple[str, bytes, str]]:
    """The 4 attachments of the hourly indent e-mail."""
    odf, cdf = overall_df(rows, m), customer_df(rows)
    sub = [f"Delivery {fmt_day(day)} - as of {slot_label} - scope: {scope}",
           f"{rows['indent_id'].nunique() if rows is not None and not rows.empty else 0} indents"]
    stamp = str(day).replace("-", "")
    hh = slot_label.split(",")[0].replace(":", "").replace(" ", "")   # "11:00 AM, Sun 15 Nov" -> 1100AM
    overall_pdf = table_pdf("Overall indent - all SKUs", sub, odf, footer=f"MT Indent - {slot_label}")
    cust_pdf = sections_pdf("Customer-level indent", sub, _customer_sections(cdf),
                            footer=f"MT Indent - {slot_label}")
    per_customer = {"All customers": cdf}
    for cust, part in cdf.groupby("Customer", sort=True):
        per_customer[str(cust)] = part.reset_index(drop=True)
    return [
        (f"Overall_indent_{stamp}_{hh}.pdf", overall_pdf, "application/pdf"),
        (f"Customer_indent_{stamp}_{hh}.pdf", cust_pdf, "application/pdf"),
        (f"Overall_indent_{stamp}_{hh}.xlsx", xlsx({"Overall indent": odf}), XLSX),
        (f"Customer_indent_{stamp}_{hh}.xlsx", xlsx(per_customer), XLSX),
    ]


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


def indent_mail_html(rows: pd.DataFrame, m: Masters | None, day: str, slot_label: str,
                     name: str = "", scope: str = "everything") -> str:
    odf, cdf = overall_df(rows, m), customer_df(rows)
    n_ind = rows["indent_id"].nunique() if rows is not None and not rows.empty else 0
    waiting = rows[rows["status"] != STATUS_FROZEN]["indent_id"].nunique() if n_ind else 0
    parts = [f"<p>Hello{(' ' + html.escape(name)) if name else ''},</p>",
             f"<p>Indents for delivery on <b>{fmt_day(day)}</b>, as of <b>{slot_label}</b> "
             f"(scope: {html.escape(scope)}). {n_ind} indent(s), {waiting} still waiting for a PO. "
             "PDF and Excel copies are attached.</p>",
             "<h3 style='color:#1c6b49'>1. Overall indent (all SKUs)</h3>",
             _html_table(odf, {"Total"}),
             "<h3 style='color:#1c6b49'>2. Customer-level indent</h3>"]
    if cdf.empty:
        parts.append("<p style='color:#666'>No indents.</p>")
    for cust, part in cdf.groupby("Customer", sort=True):
        parts.append(f"<h4 style='margin:14px 0 4px'>{html.escape(str(cust))}</h4>")
        for (store, iid, status), sp in part.groupby(["Store", "Indent", "Status"], sort=True):
            parts.append(f"<div style='margin:6px 0 2px'><b>{html.escape(str(store))}</b> "
                         f"<span style='color:#666'>· {html.escape(str(iid))} · {html.escape(str(status))}"
                         "</span></div>")
            parts.append(_html_table(sp[["Customer SKU Name", "Variety", "Lot", "Lot Size", "Qty"]],
                                     {"Qty"}))
    parts.append("<p style='color:#888;font-size:12px'>Sent by the MT Indent app.</p>")
    return "".join(parts)


# ------------------------------------------------------------------ hourly production e-mail

def production_view(rows: pd.DataFrame, m: Masters | None, rules: list | None) -> pd.DataFrame:
    p = production_calc.production(rows, m)
    if not p.empty and not p["Variety"].astype(bool).any():
        p = p.drop(columns=["Variety"])
    if not p.empty and len(p["City"].unique()) == 1:
        p = p.drop(columns=["City"])
    return p


def production_mail_files(rows: pd.DataFrame, m: Masters | None, rules: list | None, day: str,
                          slot_label: str, scope: str = "everything") -> list[tuple[str, bytes, str]]:
    """The hourly e-mail attachments: the production report as PDF and Excel."""
    p = production_view(rows, m, rules)
    n = rows["indent_id"].nunique() if rows is not None and not rows.empty else 0
    sub = [f"Delivery {fmt_day(day)} - as of {slot_label} - {scope}",
           f"{n} indents - all customers together"]
    stamp = str(day).replace("-", "")
    hh = slot_label.split(",")[0].replace(":", "").replace(" ", "")
    return [(f"Production_{stamp}_{hh}.pdf",
             table_pdf("Production sheet", sub, p, footer=f"MT Indent - {slot_label}"), "application/pdf"),
            (f"Production_{stamp}_{hh}.xlsx", xlsx({"Production": p}), XLSX)]


def production_mail_html(rows: pd.DataFrame, m: Masters | None, rules: list | None, day: str,
                         slot_label: str, name: str = "", scope: str = "everything") -> str:
    p = production_view(rows, m, rules)
    n = rows["indent_id"].nunique() if rows is not None and not rows.empty else 0
    waiting = rows[rows["status"] != STATUS_FROZEN]["indent_id"].nunique() if n else 0
    return "".join([
        f"<p>Hello{(' ' + html.escape(name)) if name else ''},</p>",
        f"<p>Production for delivery on <b>{fmt_day(day)}</b>, as of <b>{slot_label}</b> "
        f"({html.escape(scope)}). {n} indent(s), {waiting} still waiting for a PO. "
        "The same report is attached as PDF and Excel.</p>",
        "<h3 style='color:#1c6b49'>Production sheet</h3>",
        _html_table(p, {"Total"}),
        "<p style='color:#888;font-size:12px'>Sent by the MT Indent app.</p>"])


# ------------------------------------------------------------------ SO / PO

def so_df(cur) -> pd.DataFrame:
    return pd.DataFrame([{"Parent SKU": x.parent_sku, "Customer SKU Name": x.customer_sku_name,
                          "Variety": x.variety, "Lot": x.lot, "Lot Size": lot_size(x.customer_sku_name),
                          "Qty": int(x.qty) if float(x.qty).is_integer() else x.qty,
                          "Price": round(x.price, 2), "Amount": round(x.amount, 2)} for x in cur.lines])


def so_info(cur, po_number: str, po_file: str, uploaded_by: str) -> list[tuple[str, str]]:
    h = cur.header
    return [("Indent", cur.indent_id), ("PO number", po_number or "-"), ("PO file", po_file or "-"),
            ("Customer", h.customer), ("Store", h.store), ("City", h.city),
            ("Delivery", f"{fmt_day(h.delivery_date)} at {h.expected_time}"),
            ("Total qty", fmt_num(sum(x.qty for x in cur.lines))),
            ("Total amount", f"Rs {sum(x.amount for x in cur.lines):,.2f}"),
            ("PO uploaded by", uploaded_by),
            ("PO uploaded at", config.now_ist().strftime("%d %b %Y %I:%M %p"))]


def so_files(cur, po_number: str, po_file: str, uploaded_by: str) -> list[tuple[str, bytes, str]]:
    info = so_info(cur, po_number, po_file, uploaded_by)
    df = so_df(cur)
    pdf = table_pdf(f"SO placed - {cur.header.customer} - {cur.header.store}",
                    [f"{k}: {v}" for k, v in info], df, footer=f"MT Indent - {cur.indent_id}")
    x = xlsx({"SO": pd.DataFrame(info, columns=["Field", "Value"]), "Items": df})
    return [(f"SO_{cur.indent_id}.pdf", pdf, "application/pdf"), (f"SO_{cur.indent_id}.xlsx", x, XLSX)]


def so_html(cur, po_number: str, po_file: str, uploaded_by: str) -> str:
    info = so_info(cur, po_number, po_file, uploaded_by)
    rows = "".join(f"<tr><td style='padding:2px 10px 2px 0;color:#555'>{html.escape(k)}</td>"
                   f"<td><b>{html.escape(str(v))}</b></td></tr>" for k, v in info)
    return (f"<p>SO placed for <b>{html.escape(cur.header.customer)}</b> · "
            f"{html.escape(cur.header.store)}. The customer's PO matched the indent and the indent "
            "is now frozen.</p>"
            f"<table>{rows}</table><br>"
            + _html_table(so_df(cur), {"Qty", "Price", "Amount"})
            + "<p style='color:#888;font-size:12px'>Attached: the customer's PO, and the SO as PDF and "
              "Excel. Sent by the MT Indent app.</p>")
