"""Turn an order picture / screenshot into a table: item rows x one qty column per
store (19 Nov night, "Read order picture" page). Free readers, in order:

1. Gemini (free key, `gemini_api_key`): asked for the table as JSON;
2. OCR.space (free key, `ocrspace_api_key`; 25,000 a month, 1 MB a picture): table
   mode text, split into rows here;
3. Tesseract (built in): the same text parsing (weak on tilted phone photos).

The first reader that gives rows wins; the page shows which one read it. Nothing is
guessed: every cell is shown for checking and can be corrected before saving."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from core import config

NUM = re.compile(r"^-?\d[\d,]*(\.\d+)?$")


@dataclass
class TRow:
    name: str
    qtys: list[float]
    code: str = ""
    unsure: bool = False


@dataclass
class TableRead:
    stores: list[str] = field(default_factory=list)     # one header per qty column ("" = not written)
    rows: list[TRow] = field(default_factory=list)
    totals: list[float | None] = field(default_factory=list)
    customer: str = ""
    source: str = ""
    notes: str = ""

    @property
    def text(self) -> str:
        return " ".join([self.customer] + self.stores + [r.name for r in self.rows])

    def column_total(self, i: int) -> float:
        return sum(r.qtys[i] for r in self.rows if i < len(r.qtys))


class TableReadError(Exception):
    pass


# ------------------------------------------------------------------ text -> table

def _num(s: str) -> float | None:
    s = s.strip().replace(",", "")
    return float(s) if NUM.match(s) else None


def _cells(line: str) -> list[str]:
    parts = re.split(r"\t+|\s{2,}|\s*\|\s*", line.strip())
    return [p.strip() for p in parts if p.strip()]


def parse_lines(lines: list[str]) -> TableRead:
    """Rows = a name (with letters) followed by numbers; the last numbers are the qty
    columns. A long leading number (6+ digits) is the item code. A row without a
    name is the total row. The header line above the rows names the qty columns."""
    out = TableRead()
    rows, header = [], None
    for raw in lines:
        cells = _cells(raw)
        if not cells:
            continue
        code = ""
        if re.fullmatch(r"\d{6,}", cells[0].replace(" ", "")):
            code, cells = cells[0], cells[1:]
        nums: list[float] = []
        while cells and _num(cells[-1]) is not None:
            nums.insert(0, _num(cells.pop()))
        name = " ".join(cells).strip(" -:")
        if re.search(r"^(date|po date|order date|delivery|po no|po number)\b", name, re.I) or \
                re.search(r"\b\d{1,2}[-/][A-Za-z0-9]{2,3}[-/]\d{2,4}\b", name):
            continue                                # a date / PO line above the table
        if not nums:
            if name and not rows:
                header = cells                      # the last text-only line before the rows
            continue
        if not re.search(r"[A-Za-z]{2}", name):
            out.totals = nums                       # '-  -  1,050' / 'Total'
            continue
        if re.search(r"\b(total|grand total|summation)\b", name, re.I):
            out.totals = nums
            continue
        rows.append(TRow(name=name, qtys=nums, code=code))
    if not rows:
        return out
    width = max(len(r.qtys) for r in rows)
    for r in rows:                                  # short rows: numbers belong to the last columns
        r.qtys = [0.0] * (width - len(r.qtys)) + r.qtys
    out.rows = rows
    heads = [h for h in (header or []) if not re.search(r"(item|sku|desc|product|name|code|s\.?\s*no|uom)",
                                                        h, re.I)]
    out.stores = (heads[-width:] if len(heads) >= width else [""] * (width - len(heads)) + heads)
    if out.totals and len(out.totals) != width:
        out.totals = (out.totals + [None] * width)[-width:] if len(out.totals) > width else \
            [None] * (width - len(out.totals)) + out.totals
    return out


# ------------------------------------------------------------------ readers

def _small_jpeg(data: bytes, limit: int = 950_000) -> bytes:
    """OCR.space free: 1 MB a picture. Shrink and re-encode until it fits."""
    if len(data) <= limit:
        return data
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    side, q = 2000, 85
    while True:
        im2 = im.copy()
        im2.thumbnail((side, side))
        buf = io.BytesIO()
        im2.save(buf, "JPEG", quality=q)
        if buf.tell() <= limit or side < 900:
            return buf.getvalue()
        side, q = int(side * 0.8), max(60, q - 5)


def ocrspace_key() -> str:
    return str(config.get("ocrspace_api_key", "") or "").strip()


def read_ocrspace(data: bytes) -> TableRead:
    import requests
    img = _small_jpeg(data)
    try:
        r = requests.post("https://api.ocr.space/parse/image", timeout=90,
                          files={"file": ("order.jpg", img, "image/jpeg")},
                          data={"apikey": ocrspace_key(), "language": "eng", "OCREngine": "2",
                                "isTable": "true", "scale": "true", "detectOrientation": "true"})
    except requests.RequestException as e:
        raise TableReadError(f"OCR.space could not be reached ({type(e).__name__}).") from e
    try:
        j = r.json()
    except ValueError as e:
        raise TableReadError(f"OCR.space gave no answer ({r.status_code}).") from e
    if j.get("IsErroredOnProcessing") or not j.get("ParsedResults"):
        msg = j.get("ErrorMessage") or j.get("ErrorDetails") or "no text found"
        raise TableReadError(f"OCR.space: {msg if isinstance(msg, str) else '; '.join(map(str, msg))}")
    text = "\n".join(p.get("ParsedText", "") for p in j["ParsedResults"])
    out = parse_lines(text.splitlines())
    out.source = "OCR.space"
    return out


def read_tesseract(data: bytes) -> TableRead:
    from core import order_reader
    if not order_reader.ocr_available():
        raise TableReadError("The built-in reader (Tesseract) is not installed here.")
    got = order_reader._ocr_lines(data)
    out = parse_lines([t for t, _ in got])
    low = {t for t, c in got if c < 75}
    for r in out.rows:
        r.unsure = any(r.name in t for t in low)
    out.source = "Tesseract"
    return out


GEMINI_PROMPT = """You read purchase orders / indents for a fruit supplier (Ninjacart) from a photo or a
screenshot (a WhatsApp message, an Excel screenshot or a phone photo; it may be tilted or a bit blurred).
The order may list quantities for SEVERAL stores / warehouses side by side (e.g. "WH1" and "WH2",
"FNV1"/"FNV2", or store names as column headers). Return:
- customer: the customer / company written on it ("" if none);
- stores: the header of each quantity column, left to right, exactly as written ("" when a column has
  no header). One entry per quantity column; just [""] when there is one unnamed qty column;
- lines: every order line top to bottom: name = the item exactly as written including pack/size words
  (e.g. "Fresho Kiwi - Green 3 pcs (240 Gms)"), code = the item / SKU code if written (else ""),
  qtys = the quantity in each quantity column in the same order as stores (0 when empty),
  sure = false when any part is hard to read;
- totals: the total row per column if written (else []).
Skip prices, amounts, dates and phone numbers. Never invent lines or numbers."""

GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "customer": {"type": "STRING"},
        "stores": {"type": "ARRAY", "items": {"type": "STRING"}},
        "totals": {"type": "ARRAY", "items": {"type": "NUMBER"}},
        "lines": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}, "code": {"type": "STRING"},
                           "qtys": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                           "sure": {"type": "BOOLEAN"}},
            "required": ["name", "qtys", "sure"]}},
    },
    "required": ["stores", "lines"],
}


def parse_gemini(p: dict) -> TableRead:
    stores = [str(s or "").strip() for s in (p.get("stores") or [])] or [""]
    out = TableRead(stores=stores, customer=str(p.get("customer") or "").strip())
    for ln in p.get("lines") or []:
        name = " ".join(str(ln.get("name") or "").split())
        qtys = []
        for q in (ln.get("qtys") or []):
            try:
                qtys.append(float(q or 0))
            except (TypeError, ValueError):
                qtys.append(0.0)
        qtys = (qtys + [0.0] * len(stores))[:len(stores)]
        if name and any(qtys):
            out.rows.append(TRow(name=name, qtys=qtys, code=str(ln.get("code") or "").strip(),
                                 unsure=not bool(ln.get("sure", True))))
    t = [float(x) for x in (p.get("totals") or []) if isinstance(x, (int, float))]
    out.totals = t if len(t) == len(stores) else []
    return out


def read_gemini(data: bytes, mime: str) -> TableRead:
    from core import ai_reader
    key = ai_reader.api_key()
    img, mime = ai_reader._shrink(data, mime)
    first = str(config.get("gemini_model", ai_reader.DEFAULT_MODEL) or ai_reader.DEFAULT_MODEL)
    tried = []
    for model in dict.fromkeys((first,) + ai_reader.FALLBACK_MODELS):
        try:
            p = _gemini_call(model, img, mime, key)
        except (LookupError, ai_reader.Busy) as e:
            tried.append(f"{model}: {'not available' if isinstance(e, LookupError) else e}")
            continue
        out = parse_gemini(p)
        out.source = f"Gemini ({model})"
        return out
    raise TableReadError("Gemini is busy (" + "; ".join(tried) + ").")


def _gemini_call(model: str, img: bytes, mime: str, key: str) -> dict:
    """Same call as core.ai_reader, with the table prompt."""
    from core import ai_reader
    return ai_reader._call(model, img, mime, key, GEMINI_PROMPT, GEMINI_SCHEMA)


def readers() -> list[str]:
    from core import ai_reader, order_reader
    out = []
    if ai_reader.available():
        out.append("gemini")
    if ocrspace_key():
        out.append("ocrspace")
    if order_reader.ocr_available():
        out.append("tesseract")
    return out


def read(data: bytes, name: str = "order.jpg") -> TableRead:
    """The first free reader that finds rows. Raises TableReadError when none can."""
    from core import ai_reader
    problems = []
    for who in readers():
        try:
            if who == "gemini":
                got = read_gemini(data, ai_reader.mime_of(name))
            elif who == "ocrspace":
                got = read_ocrspace(data)
            else:
                got = read_tesseract(data)
        except (TableReadError, ai_reader.AIReadError) as e:
            problems.append(str(e))
            continue
        except Exception as e:  # noqa: BLE001 - one reader failing never stops the next
            problems.append(f"{who}: {type(e).__name__}")
            continue
        if got.rows:
            if problems:
                got.notes = "Earlier readers: " + " | ".join(problems)
            return got
        problems.append(f"{who}: no rows found")
    if not problems:
        raise TableReadError("No picture reader is set up (add gemini_api_key or ocrspace_api_key in Secrets).")
    raise TableReadError("The picture could not be read. " + " | ".join(problems))


def pick_column(t: TableRead, store: str) -> int | None:
    """The qty column for one store (header words or WH1/WH2 numbers), else None."""
    from core.order_reader import _norm
    s = _norm(store)
    best, score = None, 0
    for i, h in enumerate(t.stores):
        h2 = _norm(h)
        if not h2:
            continue
        sc = 3 if h2 == s else 2 if (h2 in s or s in h2) else 0
        dh, ds = re.findall(r"\d+", h2), re.findall(r"\d+", s)
        if not sc and dh and ds and dh[-1] == ds[-1]:
            sc = 1
        if sc > score:
            best, score = i, sc
    return best


STORE_WORDS = {"wh1": ("wh1", "fnv1", "mbf", "mbfpo"), "wh2": ("wh2", "fnv2", "blr", "blrpo")}


def guess_store(header: str, stores: list[str]) -> str:
    """Which of our stores a qty column header means: 'FNV1' / 'MBF' / 'WH 1' -> the store
    with WH1 in its name; else the store sharing most words; '' when unsure."""
    from core.order_reader import _norm
    h = _norm(header)
    if not h or not stores:
        return stores[0] if len(stores) == 1 and not h else ""
    for tag, words in STORE_WORDS.items():
        if any(w in h for w in words):
            hit = [s for s in stores if tag in _norm(s)]
            if len(hit) == 1:
                return hit[0]
    exact = [s for s in stores if _norm(s) == h or h in _norm(s) or _norm(s) in h]
    if len(exact) == 1:
        return exact[0]
    hw = set(re.findall(r"[a-z]+|\d+", header.casefold()))
    scored = sorted(((len(hw & set(re.findall(r"[a-z]+|\d+", s.casefold()))), s) for s in stores), reverse=True)
    if scored and scored[0][0] and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return ""


__all__ = ["TableRead", "TRow", "TableReadError", "read", "parse_lines", "parse_gemini", "pick_column",
           "readers", "ocrspace_key", "guess_store"]
