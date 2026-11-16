"""Plain data objects for an indent."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field


def to_number(v, default: float = 0.0) -> float:
    if v is None:
        return default
    if isinstance(v, (int, float)):
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    s = str(v).replace(",", "").strip()
    if not s:
        return default
    try:
        f = float(s)
    except ValueError:
        return default
    return default if math.isnan(f) or math.isinf(f) else f


def fmt_q(v) -> str:
    """Like fmt_num, but None (not on the PO / not on the indent) stays blank, never 0."""
    return "" if v is None else fmt_num(v)


def fmt_num(v) -> str:
    """40.0 -> '40', 12.5 -> '12.5', 1/3 -> '0.333' (for sheet text and diffs)."""
    n = to_number(v)
    if n.is_integer():
        return str(int(n))
    return f"{n:.3f}".rstrip("0").rstrip(".")


def _lot(v) -> str:
    from core.lots import normalize_lot
    return normalize_lot(v)


@dataclass
class IndentHeader:
    delivery_date: str = ""   # YYYY-MM-DD
    city: str = ""
    customer: str = ""
    store: str = ""
    expected_time: str = ""   # HH:MM

    FIELDS = ("delivery_date", "city", "customer", "store", "expected_time")


    def missing(self) -> list[str]:
        labels = {"delivery_date": "Delivery date", "city": "City", "customer": "Customer",
                  "store": "Store", "expected_time": "Expected delivery time"}
        return [labels[f] for f in self.FIELDS if not str(getattr(self, f) or "").strip()]

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.FIELDS}

    @classmethod
    def from_dict(cls, d: dict | None) -> "IndentHeader":
        d = d or {}
        return cls(**{f: str(d.get(f, "") or "") for f in cls.FIELDS})


@dataclass
class IndentLine:
    parent_sku: str = ""
    customer_sku_name: str = ""
    variety: str = ""
    lot: str = ""
    qty: float = 0.0
    price: float = 0.0

    @property
    def amount(self) -> float:
        return round(to_number(self.qty) * to_number(self.price), 2)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["qty"] = to_number(self.qty)
        d["price"] = to_number(self.price)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IndentLine":
        return cls(
            parent_sku=str(d.get("parent_sku", "") or ""),
            customer_sku_name=str(d.get("customer_sku_name", "") or ""),
            variety=str(d.get("variety", "") or ""),
            lot=_lot(d.get("lot", "")),
            qty=to_number(d.get("qty")),
            price=to_number(d.get("price")),
        )


@dataclass
class IndentSnapshot:
    """One version of an indent as stored in Indent_Lines."""
    indent_id: str
    version: int
    status: str
    submitted_at: str
    submitted_by: str
    header: IndentHeader
    lines: list[IndentLine] = field(default_factory=list)

    @property
    def total_amount(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)
