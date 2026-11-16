"""Read a customer's PO (text PDF) and match its lines to our SKU names.

Reading: pdfplumber finds the item table on every page (header row with an
item/description column and a qty column), so numbers are copied exactly,
never guessed. Scanned/photo POs have no text and give no lines.

Matching, in order:
  1. PO_Item_Map tab (Customer + PO item code or name -> Customer SKU Name),
  2. same name: the words of the item name without pack/size, plus the same
     pack ("2PC - Bloom Kiwi" = "Bloom Kiwi - 2 pc (200 - 250 g)"),
  3. close name (most words the same) -> marked for checking.
Checks: qty x unit cost = line value, and the line values add up to the PO total.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

UNITS = {"pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc", "pack": "pc",
         "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "kg": "kg"}
NUM = re.compile(r"-?\d[\d,]*\.?\d*")


@dataclass
class POLine:
    name: str
    qty: float
    code: str = ""
    unit_cost: float | None = None
    value: float | None = None
    sku: str = ""          # our Customer SKU Name ("" = not matched)
    how: str = ""          # map / name / close / ""


@dataclass
class POReadResult:
    lines: list[POLine] = field(default_factory=list)
    po_number: str = ""
    total: float | None = None       # PO total printed on the PDF
    has_text: bool = True
    checks: list[str] = field(default_factory=list)   # problems found

    @property
    def total_qty(self) -> float:
        return sum(x.qty for x in self.lines)


def _num(s) -> float | None:
    m = NUM.search(str(s or "").replace("Rs.", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _clean(s) -> str:
    return " ".join(str(s or "").split())


def _col(header: list[str], *words: str, avoid: tuple = ()) -> int | None:
    for w in words:
        for i, h in enumerate(header):
            h2 = _clean(h).casefold()
            if h2 and re.search(w, h2) and not any(a in h2 for a in avoid):
                return i
    return None


def _table_lines(table: list[list]) -> list[POLine]:
    out, cols = [], None
    for row in table:
        cells = [_clean(c) for c in row]
        if cols is None:
            desc = _col(cells, r"item desc", r"description", r"^item$")
            qty = _col(cells, r"^qty", r"quantity")
            if desc is not None and qty is not None:
                cols = {"desc": desc, "qty": qty,
                        "code": _col(cells, r"material code", r"item code", r"sku code"),
                        "cost": _col(cells, r"unit (base )?cost", r"unit price"),
                        "value": _col(cells, r"taxable value", r"sub-total")}
            continue
        if any("total" in c.casefold() for c in cells[:2]):
            continue
        name = cells[cols["desc"]] if cols["desc"] < len(cells) else ""
        qty = _num(cells[cols["qty"]]) if cols["qty"] < len(cells) else None
        if not name or qty is None or name.casefold() in ("rate", "amt"):
            continue
        get = lambda k: cells[cols[k]] if cols[k] is not None and cols[k] < len(cells) else ""  # noqa: E731
        out.append(POLine(name=name, qty=qty, code=get("code"), unit_cost=_num(get("cost")),
                          value=_num(get("value"))))
    return out


def _po_number(text: str) -> str:
    for pat in (r"PO\s*No\.?\s*:?\s*([A-Z0-9][A-Z0-9\-/]{3,})", r"Order\s*#.*?\n\s*(PO-\d+)",
                r"\b(PO-\d{4,}(?:-[A-Z0-9]+)?)", r"\b([MB]BFPO\d+|P\d{6,})\b"):
        m = re.search(pat, text, re.S)
        if m:
            return m.group(1).strip("-")
    return ""


def _po_total(text: str) -> float | None:
    vals = [_num(m.group(1)) for m in re.finditer(
        r"(?:Grand Total(?: Amount)?|Total Amount|Total Taxable Amount|Sub-Total)\s*(?:\(INR\))?\s*:?\s*"
        r"(?:Rs\.?\s*)?([\d,]+\.\d{2})", text)]
    vals = [v for v in vals if v]
    return max(vals) if vals else None


def read_pdf(data: bytes) -> POReadResult:
    import pdfplumber
    res = POReadResult()
    text = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                text.append(page.extract_text() or "")
                for t in page.extract_tables():
                    res.lines += _table_lines(t)
    except Exception as e:  # noqa: BLE001 - a broken PDF just gives no lines
        res.checks.append(f"The PDF could not be read ({type(e).__name__}).")
        return res
    full = "\n".join(text)
    res.has_text = bool(full.strip())
    res.po_number = _po_number(full)
    res.total = _po_total(full)
    if not res.has_text:
        res.checks.append("This PDF is a scan/photo (no text): type the quantities by hand.")
    for x in res.lines:
        if x.unit_cost and x.value and abs(x.unit_cost * x.qty - x.value) > max(1.0, x.value * 0.005):
            res.checks.append(f"{x.name}: qty {x.qty:g} × {x.unit_cost:g} ≠ {x.value:g}")
    vals = [x.value for x in res.lines if x.value is not None]
    if res.total and vals and len(vals) == len(res.lines) and abs(sum(vals) - res.total) > 1:
        res.checks.append(f"Lines add up to {sum(vals):,.2f} but the PO total is {res.total:,.2f}: "
                          "a line may be missing.")
    return res


# ------------------------------------------------------------------ matching

def _pack(text: str) -> str:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-z]+)\s*$", text.casefold())
    if m and m.group(2) in UNITS:
        return f"{float(m.group(1)):g}{UNITS[m.group(2)]}"
    return ""


def _words(core: str) -> frozenset:
    core = re.sub(r"\([^)]*\d[^)]*\)", " ", core.casefold())       # sizes like (250-300 g)
    return frozenset(w for w in re.findall(r"[a-z]+", core) if w not in {"pc", "pcs", "g", "gm", "kg"})


def our_key(sku: str) -> tuple[frozenset, str]:
    """'2PC - Bloom Kiwi Sungold Imported (New Zealand)' -> (words, '2pc')."""
    m = re.match(r"^\s*([0-9.]+\s*[A-Za-z]+)\s*-\s*(.+)$", sku)
    if m and _pack(m.group(1)):
        return _words(m.group(2)), _pack(m.group(1))
    return _words(sku), ""


def po_key(name: str) -> tuple[frozenset, str]:
    """'Bloom Kiwi Sungold Imported (New Zealand) - 2 pc (200 - 250 g)' -> (words, '2pc').
    'Blueberry Imported - 120 - 130 g' -> (words, '') (a weight range is not a pack)."""
    parts = re.split(r"\s+-\s+(?=\d)", name, maxsplit=1)
    pack = ""
    if len(parts) == 2:
        tail = re.sub(r"\([^)]*\)", "", parts[1]).strip()
        pack = _pack(tail)
    return _words(parts[0]), pack


def match(lines: list[POLine], candidates: list[str], item_map: dict[str, str] | None = None) -> list[POLine]:
    """Fill .sku/.how on every line. candidates: our SKU names (the indent's first)."""
    item_map = {k.strip().casefold(): v for k, v in (item_map or {}).items() if k and v}
    keys = [(c, *our_key(c)) for c in dict.fromkeys(candidates)]
    for x in lines:
        hit = item_map.get(x.code.strip().casefold()) or item_map.get(x.name.strip().casefold())
        if hit:
            x.sku, x.how = hit, "map"
            continue
        words, pack = po_key(x.name)
        same = [c for c, w, p in keys if w == words and (not pack or not p or p == pack)]
        if len(same) > 1 and pack:
            same = [c for c, w, p in keys if w == words and p == pack] or same
        if len(same) == 1 or (same and len(set(same)) == 1):
            x.sku, x.how = same[0], "name"
            continue
        if same:
            continue                              # ambiguous: let the user choose
        best, score = "", 0.0
        for c, w, p in keys:
            if pack and p and p != pack or not w or not words:
                continue
            s = len(w & words) / len(w | words)
            if s > score:
                best, score = c, s
        if score >= 0.6:
            x.sku, x.how = best, "close"
    return lines


def store_hint(po_number: str, prefixes: dict[str, str]) -> str:
    """Store the PO belongs to by its number's first letter (Swiggy: M = WH1, B = WH2)."""
    p = str(po_number or "").strip().upper()
    for store, pre in prefixes.items():
        if pre and p.startswith(pre.upper()):
            return store
    return ""
