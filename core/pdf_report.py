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
            "Lot": 0.7}
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
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*GREEN)
    pdf.cell(0, 8, _t(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(60)
    for line in subtitle:
        pdf.cell(0, 5, _t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_text_color(0)
    return pdf


def _table(pdf: FPDF, df: pd.DataFrame) -> None:
    cols = list(df.columns)
    widths = [_WEIGHTS.get(c, 1.0) for c in cols]
    align = ["RIGHT" if c in _NUMERIC else "LEFT" for c in cols]
    pdf.set_font("Helvetica", "", 8)
    heading = FontFace(emphasis="BOLD", color=255, fill_color=GREEN)
    with pdf.table(col_widths=widths, text_align=align, headings_style=heading, line_height=4.6,
                   cell_fill_color=(243, 247, 245), cell_fill_mode="ROWS", repeat_headings=1,
                   padding=1.2) as table:
        row = table.row()
        for c in cols:
            row.cell(_t(c))
        for rec in df.itertuples(index=False):
            row = table.row()
            for v in rec:
                row.cell(_t(v))


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
                 footer: str = "") -> bytes:
    """One PDF with a heading + table per section (e.g. one per customer / store)."""
    pdf = _new_pdf(title, subtitle, footer)
    if not sections:
        pdf.cell(0, 8, "No indents.")
        return bytes(pdf.output())
    for i, (head, sub, df) in enumerate(sections):
        if pdf.get_y() > 170 and i:
            pdf.add_page()
        pdf.ln(2 if i else 0)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*GREEN)
        pdf.cell(0, 7, _t(head), new_x="LMARGIN", new_y="NEXT")
        if sub:
            pdf.set_font("Helvetica", "", 8.5)
            pdf.set_text_color(60)
            pdf.multi_cell(0, 4.5, _t(sub), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
        if df is None:          # a heading only (e.g. the customer above its stores)
            continue
        if df.empty:
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 6, "No items.", new_x="LMARGIN", new_y="NEXT")
            continue
        _table(pdf, df)
        _lot_totals(pdf, df)
    return bytes(pdf.output())
