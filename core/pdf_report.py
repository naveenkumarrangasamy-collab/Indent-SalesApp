"""PDF versions of the production reports (A4 landscape table)."""
from __future__ import annotations

import pandas as pd
from fpdf import FPDF
from fpdf.fonts import FontFace

GREEN = (28, 107, 73)

# Relative column widths; anything not listed gets 1.
_WEIGHTS = {"Store Names": 3.0, "Customer SKU Names": 4.2, "Customer SKU Name": 3.2, "Store": 2.2, "Parent SKU": 1.2,
            "Customer": 1.1, "City": 1.3, "Spec-Size": 1.3, "Lot Size": 1.1, "Variety": 1.1,
            "Origin": 1.1, "Total Qty": 0.9, "Qty": 0.8, "Lines": 0.6, "Indents": 0.7, "Stores": 0.6,
            "Lot": 0.7, "At spec": 2.4, "Spec Size": 2.4, "Make ready": 1.3, "Fruit needed": 1.2,
            "Repacking": 1.3}
_NUMERIC = {"Total Qty", "Qty", "Lines", "Indents", "Stores", "Price", "Amount"}


def _t(v) -> str:
    """Text safe for the built-in PDF fonts (Latin-1)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).replace("→", "->").replace("₹", "Rs ").replace("–", "-").replace("·", "-")
    return s.encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    footer_text = ""

    def footer(self):
        self.set_y(-10)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(120)
        self.cell(0, 5, f"{self.footer_text}   Page {self.page_no()}/{{nb}}", align="R")


def _new_pdf(title: str, subtitle: list[str], footer: str) -> FPDF:
    pdf = _PDF(orientation="L", unit="mm", format="A4")
    pdf.footer_text = _t(footer)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*GREEN)
    pdf.cell(0, 8, _t(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(40)
    for line in subtitle:
        pdf.cell(0, 5.5, _t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_text_color(0)
    return pdf


def _is_num(v) -> bool:
    s = _t(v).replace(",", "").strip()
    if s in ("", "-", "–"):
        return True
    try:
        float(s)
        return True
    except ValueError:
        return False


def _table(pdf: FPDF, df: pd.DataFrame, row_fill: dict | None = None) -> None:
    """Crisp, readable table: 10 pt text, bold green header, bold Total rows,
    numbers right-aligned (sized for reading on a phone as well as print).
    row_fill {Status value: hex}: rows with that Status get that background (24 Nov, batching)."""
    cols = list(df.columns)
    widths = [_WEIGHTS.get(c, 1.0) for c in cols]
    num = {c for c in cols if c in _NUMERIC or (len(df) and all(_is_num(v) for v in df[c]))}
    align = ["RIGHT" if c in num else "LEFT" for c in cols]
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0)
    pdf.set_draw_color(150, 160, 155)
    pdf.set_line_width(0.2)
    heading = FontFace(emphasis="BOLD", color=255, fill_color=GREEN, size_pt=10)
    bold = FontFace(emphasis="BOLD", fill_color=(214, 232, 222))
    with pdf.table(col_widths=widths, text_align=align, headings_style=heading, line_height=6,
                   cell_fill_color=(244, 248, 246), cell_fill_mode="ROWS", repeat_headings=1,
                   padding=(1.6, 2.0), borders_layout="ALL") as table:
        row = table.row()
        for c in cols:
            row.cell(_t(c))
        si = cols.index("Status") if row_fill and "Status" in cols else None
        fills = {k: FontFace(fill_color=tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)))
                 for k, h in (row_fill or {}).items()}
        for rec in df.itertuples(index=False):
            total = str(rec[0]).strip().casefold() == "total"
            st = bold if total else fills.get(rec[si]) if si is not None else None
            row = table.row()
            for v in rec:
                row.cell(_t(v), style=st)


def _lot_totals(pdf: FPDF, df: pd.DataFrame) -> None:
    for qc in ("Total Qty", "Qty"):
        if qc in df.columns:
            pdf.ln(1.5)
            pdf.set_font("Helvetica", "B", 9)
            if "Lot" in df.columns:
                by_lot = df.groupby("Lot")[qc].sum()
                pdf.cell(0, 5, _t("Total by lot: " + ", ".join(f"{_t(q)} {lot}" for lot, q in by_lot.items())),
                         new_x="LMARGIN", new_y="NEXT")
            break


def table_pdf(title: str, subtitle: list[str], df: pd.DataFrame, footer: str = "") -> bytes:
    pdf = _new_pdf(title, subtitle, footer)
    if df is None or df.empty:
        pdf.cell(0, 8, "No data for these filters.")
        return bytes(pdf.output())
    _table(pdf, df)
    _lot_totals(pdf, df)
    return bytes(pdf.output())


def sections_pdf(title: str, subtitle: list[str], sections: list[tuple[str, str, pd.DataFrame]],
                 footer: str = "", page_each: bool = False, row_fill: dict | None = None) -> bytes:
    """One PDF with a heading + table per section (e.g. one per customer / store).
    page_each: every section starts on a new page (one customer per page)."""
    pdf = _new_pdf(title, subtitle, footer)
    if not sections:
        pdf.cell(0, 8, "No indents.")
        return bytes(pdf.output())
    for i, (head, sub, df) in enumerate(sections):
        if i and (page_each or pdf.get_y() > 170):
            pdf.add_page()
        pdf.ln(2 if i else 0)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(*GREEN)
        pdf.cell(0, 7, _t(head), new_x="LMARGIN", new_y="NEXT")
        if sub:
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(40)
            pdf.multi_cell(0, 5.5, _t(sub), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
        if df is None:          # a heading only (e.g. the customer above its stores)
            continue
        if df.empty:
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 6, "No items.", new_x="LMARGIN", new_y="NEXT")
            continue
        _table(pdf, df, row_fill)
        _lot_totals(pdf, df)
    return bytes(pdf.output())


# ------------------------------------------------------------------ packed by-customer PDF (21 Nov)

_LEFT = {"Customer SKU Name", "Customer SKU Names", "Store Names", "Store"}
# 21 Nov: by-customer PDF palette (one place to change it)
PDFC = {"head": (228, 240, 251), "title": (0, 0, 0), "zebra": (255, 255, 255), "total": (255, 255, 255),
        "line": (205, 216, 226), "text": (0, 0, 0)}   # 21 Nov: one very light blue, black text


def _table2(pdf: FPDF, df: pd.DataFrame) -> None:
    """Sharp table: centred cells (names left), narrow #, thin lines, bold Total row."""
    cols = list(df.columns)
    known = {"#": 0.5, "Customer SKU Name": 4.0, "Parent SKU": 1.1, "Variety": 1.1, "Repacking": 1.25,
             "Spec-Size": 1.6, "Total": 0.8, "At spec": 2.3}
    widths = [known.get(c, 1.5) for c in cols]          # unknown = a store's qty column
    align = ["LEFT" if c in _LEFT else "CENTER" for c in cols]
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(0)
    pdf.set_draw_color(*PDFC["line"])
    pdf.set_line_width(0.15)
    heading = FontFace(emphasis="BOLD", color=PDFC["text"], fill_color=PDFC["head"], size_pt=8.8)
    bold = FontFace(emphasis="BOLD", fill_color=PDFC["total"])
    with pdf.table(col_widths=widths, text_align=align, headings_style=heading, line_height=5.0,
                   cell_fill_color=PDFC["zebra"], cell_fill_mode="ROWS", repeat_headings=1,
                   padding=(0.9, 1.6), borders_layout="HORIZONTAL_LINES", align="CENTER") as table:
        row = table.row()
        for c in cols:
            row.cell(_t(c))
        for rec in df.itertuples(index=False):
            total = any(str(v).strip().casefold() == "total" for v in list(rec)[:3])
            row = table.row()
            for v in rec:
                txt = _t(v)
                style = bold if total else None
                row.cell(txt, style=style)


def _block(pdf: FPDF, head: str, sub: str, df: pd.DataFrame, cont: bool = False) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*PDFC["title"])
    pdf.cell(0, 7, _t(head + ("  (continued)" if cont else "")), align="C", new_x="LMARGIN", new_y="NEXT")
    if sub:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(0)
        pdf.cell(0, 5, _t(sub), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    _table2(pdf, df)


def _fits(pdf: FPDF, head: str, sub: str, df: pd.DataFrame, cont: bool) -> bool:
    with pdf.offset_rendering() as dummy:
        _block(dummy, head, sub, df, cont)
    return not dummy.page_break_triggered


def customers_pdf(title: str, subtitle: list[str], sections: list[tuple[str, str, pd.DataFrame]],
                  footer: str = "") -> bytes:
    """Customers one after another, as many per page as fit. A customer that does not
    fit in the space left starts on a fresh page; one longer than a page goes on over the
    next page(s) with its heading and column header again, numbers carrying on."""
    pdf = _PDF(orientation="L", unit="mm", format="A4")
    pdf.footer_text = _t(footer)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*PDFC["title"])
    pdf.cell(0, 9, _t(title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0)
    for line in subtitle:
        pdf.cell(0, 5.5, _t(line), align="C", new_x="LMARGIN", new_y="NEXT")
    top = 12
    if not sections:
        pdf.cell(0, 8, "No indents.", align="C")
        return bytes(pdf.output())
    for head, sub, df in sections:
        if df is None or df.empty:
            continue
        rest, cont = df.reset_index(drop=True), False
        while len(rest):
            if _fits(pdf, head, sub, rest, cont):
                _block(pdf, head, sub, rest, cont)
                break
            if pdf.get_y() > top + 25:          # not at the top: start this customer on a fresh page
                pdf.add_page()
                continue
            lo, hi = 1, len(rest) - 1             # longer than a page: as many rows as fit
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if _fits(pdf, head, sub, rest.iloc[:mid], cont):
                    lo = mid
                else:
                    hi = mid - 1
            left = rest.iloc[lo:]
            only_total = left.iloc[:, : min(3, left.shape[1])].astype(str).apply(
                lambda r: r.str.strip().str.casefold()).eq("total").any(axis=1).all()
            if only_total and lo > 1:            # never a page with just the Total row
                lo -= 1
            _block(pdf, head, sub, rest.iloc[:lo], cont)
            rest, cont = rest.iloc[lo:].reset_index(drop=True), True
            pdf.add_page()
    return bytes(pdf.output())
