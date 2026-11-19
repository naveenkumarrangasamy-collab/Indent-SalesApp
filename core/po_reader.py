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
         "piec": "pc", "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "kg": "kg"}
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
    unsure: bool = False   # read from a picture with low confidence: check it


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


def _norm(s: str) -> str:
    return " ".join(str(s or "").split()).casefold()


def _keys(names: list[str]) -> list[tuple]:
    seen, out = set(), []
    for c in names:
        if _norm(c) and _norm(c) not in seen:       # the master can list a name twice
            seen.add(_norm(c))
            out.append((c, *our_key(c)))
    return out


# Words that make a different product: a name with 'Bloom' never matches one without it
# (Bloom Grapes Red Globe vs Grapes Red Globe), same for Snacky, Mini, Jumbo, ...
MARKERS = frozenset({"bloom", "snacky", "mini", "large", "jumbo", "bulk", "baby", "semiripe", "organic"})


def _order(a: str, b: str) -> float:
    """How alike two names read, word order included (tie-break only)."""
    from difflib import SequenceMatcher
    core = lambda n: " ".join(re.findall(r"[a-z]+", re.sub(r"\([^)]*\d[^)]*\)", " ", n.casefold())))  # noqa: E731
    return SequenceMatcher(None, core(a), core(b)).ratio()


def _compact(s: str) -> str:
    s = re.sub(r"\([^)]*\d[^)]*\)", " ", s.casefold())
    s = re.sub(r"^\s*[0-9.]+\s*[a-z]+\s*-\s*", "", s)                 # our pack prefix
    s = re.split(r"\s+-\s+(?=\d)", s, maxsplit=1)[0]                    # their pack suffix
    return re.sub(r"[^a-z]", "", s)


def _fuzzy(name: str, keys: list[tuple]) -> tuple[str, str]:
    """Last try for badly read text (OCR glued words, typos): letters only,
    'AvocadoHassimpored' ~ 'avocadohassimported', 'Avocada Jumbo (PCS) - FK - Grade A'
    ~ '1Pc - Avocado Jumbo - FK'. Bloom / Snacky / Jumbo ... must agree."""
    from difflib import SequenceMatcher
    a = _compact(name)
    if len(a) < 5:
        return "", ""
    marks = set(re.findall(r"[a-z]+", name.casefold())) & MARKERS
    best, score = "", 0.0
    for c, w, _ in keys:
        if marks != (set(w) & MARKERS):
            continue
        r = SequenceMatcher(None, a, _compact(c)).ratio()
        if r > score:
            best, score = c, r
    return (best, "guess") if score >= 0.72 else ("", "")


def _sane(name: str, sku: str) -> bool:
    """A saved match must still share a word with the name (guards against a wrong pick)."""
    w1, _ = po_key(name)
    w2, _ = our_key(sku)
    return bool(w1 & w2) or not w1


def _find(name: str, keys: list[tuple], close_at: float, loose: bool = False,
          auto: bool = True) -> tuple[str, str]:
    """Best SKU for one name.
    1. the same words (and the same pack, when both say one) -> 'name';
       loose (the indent's own items): the same words are enough;
    2. most words in common, preferring the same pack -> 'close' (>= close_at);
    3. auto: otherwise the SKU sharing the most words -> 'guess' (never left
       blank while any SKU shares a word)."""
    words, pack = po_key(name)
    if not words:
        return "", ""
    same = [c for c, w, p in keys if w == words and (not pack or not p or p == pack)]
    if not same and loose:
        same = [c for c, w, p in keys if w == words]
    if len(same) > 1 and pack:
        same = [c for c, w, p in keys if w == words and p == pack] or same
    if same:
        return max(same, key=lambda c: _order(name, c)), "name"   # same words: same word order first
    best, rank, jac_b, pack_b = "", None, 0.0, 0
    for c, w, p in keys:
        shared = len(w & words)
        if not shared or (w ^ words) & MARKERS:     # Bloom / Snacky / Mini ... must agree
            continue
        jac = shared / len(w | words)
        pack_ok = 2 if pack and p == pack else (1 if not pack or not p else 0)
        r = (jac + 0.1 * pack_ok, shared, _order(name, c))
        if rank is None or r > rank:
            best, rank, jac_b, pack_b = c, r, jac, pack_ok
    if rank is None:
        return _fuzzy(name, keys) if auto else ("", "")
    if jac_b >= close_at and (pack_b or loose):
        return best, "close"
    return (best, "guess") if auto else ("", "")


def find_in_indent(name: str, indent_names: list[str]) -> tuple[str, str]:
    """Match one PO name (customer's style or ours) to the indent's items."""
    words, pack = our_key(name)
    if not pack:
        words, pack = po_key(name)
    keys = _keys(indent_names)
    same = [c for c, w, p in keys if w == words]
    if len(same) == 1:
        return same[0], "name"
    best, score = "", 0.0
    for c, w, p in keys:
        if w and words:
            sc = len(w & words) / len(w | words)
            if sc > score:
                best, score = c, sc
    return (best, "close") if score >= 0.5 else ("", "")


def match(lines: list[POLine], candidates: list[str], item_map: dict[str, str] | None = None,
          prefer: list[str] | None = None) -> list[POLine]:
    """Fill .sku/.how on every line. prefer: the indent's own SKU names; a PO line
    is matched to them first (only the indent's items matter for the check),
    then to the rest of the master."""
    item_map = {k.strip().casefold(): v for k, v in (item_map or {}).items() if k and v}
    own = _keys(prefer or [])
    own_names = {_norm(c) for c, _, _ in own}
    rest = _keys([c for c in candidates if _norm(c) not in own_names])
    for x in lines:
        hit = item_map.get(x.code.strip().casefold()) or item_map.get(x.name.strip().casefold())
        if hit and not _sane(x.name, hit):
            hit = None
        if hit and (not own or _norm(hit) in own_names):
            x.sku, x.how = next((c for c, _, _ in own if _norm(c) == _norm(hit)), hit), "map"
            continue
        sku, how = _find(x.name, own, 0.5, loose=True, auto=False) if own else ("", "")
        if not sku and not hit and own:
            sku, how = _soft(x.name, own)          # a spelling of one of the indent's items
            if not sku:
                sku, how = _fuzzy(x.name, own)
        if not sku and hit:
            sku, how = hit, "map"
        if not sku:
            sku, how = _find(x.name, rest, 0.6)
        x.sku, x.how = sku, how
    return lines


FILLER = frozenset({"a", "grade", "pcs", "pc", "imported", "import", "fresh", "loose", "the"})


def _soft(name: str, keys: list[tuple]) -> tuple[str, str]:
    """Every word of our SKU is in the name, allowing a small spelling slip
    ('Avocada Jumbo (PCS) - FK - Grade A' has avocado~avocada, jumbo, fk of
    '1Pc - Avocado Jumbo - FK'); at most one other real word; markers agree."""
    from difflib import SequenceMatcher
    words = set(po_key(name)[0]) | set(our_key(name)[0])
    if not words:
        return "", ""
    marks = words & MARKERS
    best, rank = "", None
    for c, w, _ in keys:
        if len(w) < 2 or (set(w) & MARKERS) != marks:
            continue
        used, score = set(), 0.0
        for ow in w:
            r, hit = max(((1.0 if ow == nw else SequenceMatcher(None, ow, nw).ratio(), nw) for nw in words),
                         default=(0.0, ""))
            if r < 0.8:
                break
            used.add(hit)
            score += r
        else:
            if len(words - used - FILLER) <= 1:
                rk = (len(w), score)
                if rank is None or rk > rank:
                    best, rank = c, rk
    return (best, "guess") if best else ("", "")


def suggest(name: str, names: list[str]) -> str:
    """The existing SKU that a new name most likely means (same words, close name,
    or a spelling of it), for an owner to approve; '' when none is close."""
    keys = _keys(names)
    sku, _ = _find(name, keys, 0.5, auto=False)
    if not sku:
        sku, _ = _soft(name, keys)
    if not sku:
        sku, _ = _fuzzy(name, keys)
    return sku


def store_hint(po_number: str, prefixes: dict[str, str]) -> str:
    """Store the PO belongs to by its number's first letter (Swiggy: M = WH1, B = WH2)."""
    p = str(po_number or "").strip().upper()
    for store, pre in prefixes.items():
        if pre and p.startswith(pre.upper()):
            return store
    return ""
