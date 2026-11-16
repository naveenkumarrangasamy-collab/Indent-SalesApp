"""Zepto indent Excel (Bangalore): one row per product, one qty column per
Zepto warehouse ("HSK old Final", "NLM Final", ...), plus "Summation".

  Product Name | UOM | EAN | Pack Date | ... | HSK New Final | HSK old Final | NLM Final | Summation

Each warehouse column with qty becomes one indent (store chosen by the user,
with a guess from the column name). Products are matched to our Zepto SKU
names like PO lines (core.po_reader): saved match (PO_Item_Map, by EAN or
name), same words + pack ("2 PIECE" = "2PC - ..."), close name."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from core import po_reader
from core.bulk_import import ImportFileError, _date, _num, _s

STORE_HINTS = {"hsk": "yalachanayakanapura", "nlm": "nelam"}   # column word -> store name word


@dataclass
class ZeptoFile:
    products: list[po_reader.POLine] = field(default_factory=list)   # .code = EAN, .qty = total
    qty: dict[str, list[float]] = field(default_factory=dict)        # column -> qty per product
    pack_date: str = ""


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").casefold())


def read(data: bytes) -> ZeptoFile:
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    except Exception as e:  # noqa: BLE001 - any unreadable file
        raise ImportFileError(f"Could not read the Excel file ({e}).") from e
    for raw in sheets.values():
        values = raw.values.tolist()
        for h in range(min(10, len(values))):
            head = [_norm(x) for x in values[h]]
            if "productname" not in head:
                continue
            ci = head.index("productname")
            uom = head.index("uom") if "uom" in head else None
            ean = head.index("ean") if "ean" in head else None
            pdate = head.index("packdate") if "packdate" in head else None
            qty_cols = [(i, _s(values[h][i])) for i, x in enumerate(head)
                        if x.endswith("final") and x != "summation"]
            if not qty_cols and "summation" in head:
                qty_cols = [(head.index("summation"), "Summation")]
            if not qty_cols:
                raise ImportFileError("No warehouse qty columns (… Final) in the Zepto file.")
            out = ZeptoFile(qty={name: [] for _, name in qty_cols})
            for row in values[h + 1:]:
                get = lambda i: row[i] if i is not None and i < len(row) else None  # noqa: E731
                name = _s(get(ci))
                if not name:
                    continue
                q = [(_num(get(i)) or 0.0) for i, _ in qty_cols]
                code = get(ean)
                code = str(int(code)) if isinstance(code, float) and code == code else _s(code)
                full = f"{name} - {_s(get(uom))}" if uom is not None and _s(get(uom)) else name
                out.products.append(po_reader.POLine(name=full, qty=sum(q), code=code))
                for (_, col), v in zip(qty_cols, q):
                    out.qty[col].append(v)
                if not out.pack_date and pdate is not None:
                    out.pack_date = _date(get(pdate))
            return out
    raise ImportFileError("This is not a Zepto indent file: no 'Product Name' column.")


def guess_store(column: str, stores: list[str]) -> str:
    """'HSK old Final' -> the Zepto store with Yalachanayakanapura (Hoskote) in its name."""
    col = column.casefold()
    for word, store_word in STORE_HINTS.items():
        if word in col:
            hits = [s for s in stores if store_word in s.casefold()]
            if len(hits) > 1:      # 'Nelamangala' vs 'Nelamgala (New)'
                want_new = "new" in col
                hits = [s for s in hits if ("new" in s.casefold()) == want_new] or hits
            if hits:
                return hits[0]
    return ""
