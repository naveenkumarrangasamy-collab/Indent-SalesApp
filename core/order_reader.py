"""Read an order (indent) from a file for Create indent: Excel, PDF or a picture.

- Excel: the Zepto indent format (one qty column per warehouse; the column of
  the chosen store is used, else the total) or any sheet with an item column and
  a qty column.
- PDF: the item table of a text PDF (core.po_reader).
- Picture: free OCR (Tesseract). Each text line -> name + the last number on the
  line as qty; lines read with low confidence are marked `unsure` (yellow).
Matching to our SKU names happens in the page (core.po_reader.match).
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

import pandas as pd

from core import po_reader, zepto_import
from core.bulk_import import ImportFileError, _num, _s
from core.po_reader import POLine

PICTURE_TYPES = ("png", "jpg", "jpeg", "webp")
UNIT_WORDS = {"piece", "pieces", "pc", "pcs", "gram", "grams", "gm", "g", "kg", "pack", "packs", "box", "tray"}
_NAME_HEADS = ("productname", "itemname", "item", "product", "description", "itemdescription", "sku",
               "skuname", "customerskuname", "name", "particulars")
_QTY_HEADS = ("qty", "quantity", "orderqty", "po", "poqty", "indentqty", "total", "summation", "units",
              "noofunits")


@dataclass
class OrderRead:
    lines: list[POLine] = field(default_factory=list)
    total: float | None = None     # the total written in the file, when found
    kind: str = ""                 # excel / pdf / picture
    note: str = ""

    @property
    def read_total(self) -> float:
        return sum(x.qty for x in self.lines)


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").casefold())


def _excel(data: bytes, store: str) -> OrderRead:
    try:
        zf = zepto_import.read(data)
    except ImportFileError:
        zf = None
    if zf is not None:
        cols = [c for c, q in zf.qty.items() if sum(q) > 0]
        pick = next((c for c in cols if store and zepto_import.guess_store(c, [store]) == store), None)
        out = OrderRead(kind="excel", note=f"Zepto file · column {pick}" if pick else "Zepto file · all columns")
        for i, p in enumerate(zf.products):
            q = zf.qty[pick][i] if pick else p.qty
            if q > 0:
                out.lines.append(POLine(name=p.name, qty=q, code=p.code))
        return out
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    except Exception as e:  # noqa: BLE001 - any unreadable file
        raise ImportFileError(f"Could not read the Excel file ({e}).") from e
    for raw in sheets.values():
        values = raw.values.tolist()
        for h in range(min(15, len(values))):
            head = [_norm(x) for x in values[h]]
            ni = next((head.index(n) for n in _NAME_HEADS if n in head), None)
            qi = next((head.index(n) for n in _QTY_HEADS if n in head), None)
            if ni is None or qi is None:
                continue
            ui = next((head.index(n) for n in ("uom", "unit") if n in head), None)
            pi = next((head.index(n) for n in ("packsize", "pack", "packqty") if n in head), None)
            out = OrderRead(kind="excel")
            for row in values[h + 1:]:
                get = lambda i: row[i] if i is not None and i < len(row) else None  # noqa: E731
                name, q = _s(get(ni)), _num(get(qi))
                if not name and q is not None and q > 0:
                    out.total = q                      # an unlabelled total row under the qty column
                    continue
                if not name or q is None or q <= 0:
                    continue
                if name.casefold().startswith("total"):
                    out.total = q
                    continue
                uom, size = _s(get(ui)), _num(get(pi))
                if size and uom and not re.match(r"\d", uom):
                    uom = f"{size:g} {uom}"           # packsize 2 + PIECE -> '2 PIECE', 250 + GRAM -> '250 GRAM'
                out.lines.append(POLine(name=f"{name} - {uom}" if uom else name, qty=q))
            return out
    raise ImportFileError("No sheet has an item column and a qty column.")


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _ocr_lines(data: bytes) -> list[tuple[str, float]]:
    """(text, confidence 0-100) per line of the picture."""
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(data)).convert("L")
    if im.width < 2000:
        im = im.resize((im.width * 2, im.height * 2))
    im = ImageOps.autocontrast(im)
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        im.save(f.name)
        out = subprocess.run(["tesseract", f.name, "stdout", "--psm", "6", "tsv"],
                             capture_output=True, text=True, timeout=120).stdout
    lines: dict[tuple, list[tuple[str, float]]] = {}
    for row in out.splitlines()[1:]:
        p = row.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            conf = float(p[10])
        except ValueError:
            continue
        lines.setdefault((p[2], p[3], p[4]), []).append((p[11], conf))
    res = []
    for words in lines.values():
        confs = [c for _, c in words if c >= 0]
        res.append((" ".join(w for w, _ in words), sum(confs) / len(confs) if confs else 0.0))
    return res


def _picture(data: bytes) -> OrderRead:
    if not ocr_available():
        raise ImportFileError("Reading pictures is not set up on this server (Tesseract missing).")
    out = OrderRead(kind="picture")
    for text, conf in _ocr_lines(data):
        text = text.replace("|", " ").strip()
        toks = text.split()
        nums = [i for i, t in enumerate(toks) if re.fullmatch(r"\d+(\.\d+)?", t)]
        if not nums:
            continue
        name_toks = [t for t in toks[:nums[0]] if re.search(r"[A-Za-z]", t)]
        qty = float(toks[nums[-1]])
        if not name_toks:
            continue
        name = " ".join(name_toks).strip(" -_.,:;")
        if re.search(r"\b(total|grand|summation)\b", name, re.I):
            out.total = qty
            continue
        if len(re.sub(r"[^A-Za-z]", "", name)) < 4:
            continue
        unit = ""
        if len(toks) > nums[0] + 1 and toks[nums[0] + 1].casefold() in UNIT_WORDS:
            unit = f"{toks[nums[0]]} {toks[nums[0] + 1]}"
        out.lines.append(POLine(name=f"{name} - {unit}" if unit else name, qty=qty, unsure=conf < 75))
    return out


def read(file_name: str, data: bytes, store: str = "") -> OrderRead:
    ext = file_name.rsplit(".", 1)[-1].casefold() if "." in file_name else ""
    if ext in ("xlsx", "xls"):
        return _excel(data, store)
    if ext == "pdf":
        r = po_reader.read_pdf(data)
        return OrderRead(lines=r.lines, total=None, kind="pdf", note=" ".join(r.checks))
    if ext in PICTURE_TYPES:
        return _picture(data)
    raise ImportFileError("Attach a picture (PNG/JPG), an Excel or a PDF file.")
