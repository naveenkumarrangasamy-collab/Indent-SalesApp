"""Compare two versions of an indent into Change_Log rows (spec 4.2 / 5.6)."""
from __future__ import annotations

from core.models import IndentHeader, IndentLine, fmt_num

HEADER_FIELDS = ["delivery_date", "city", "customer", "store", "expected_time"]
LINE_FIELDS = ["parent_sku", "variety", "lot", "qty", "price"]
_NUMERIC = {"qty", "price"}


def _val(field: str, v) -> str:
    if field in _NUMERIC:
        return fmt_num(v)
    return str(v or "").strip()


def _line_summary(line: IndentLine) -> str:
    parts = [f"parent={line.parent_sku}"]
    if line.variety:
        parts.append(f"variety={line.variety}")
    parts += [f"lot={line.lot}", f"qty={fmt_num(line.qty)}", f"price={fmt_num(line.price)}"]
    return "; ".join(parts)


def _key(name: str) -> str:
    return str(name or "").strip().casefold()


def diff(old_header: IndentHeader, old_lines: list[IndentLine],
         new_header: IndentHeader, new_lines: list[IndentLine]) -> list[dict]:
    """Return a list of changes, each a dict with change_type,
    customer_sku_name, field, old_value, new_value."""
    changes: list[dict] = []

    for f in HEADER_FIELDS:
        a, b = _val(f, getattr(old_header, f)), _val(f, getattr(new_header, f))
        if a != b:
            changes.append({"change_type": "header_changed", "customer_sku_name": "",
                            "field": f, "old_value": a, "new_value": b})

    old_map = {_key(line.customer_sku_name): line for line in old_lines}
    new_map = {_key(line.customer_sku_name): line for line in new_lines}

    for k, line in old_map.items():
        if k not in new_map:
            changes.append({"change_type": "line_removed", "customer_sku_name": line.customer_sku_name,
                            "field": "", "old_value": _line_summary(line), "new_value": ""})

    for k, line in new_map.items():
        if k not in old_map:
            changes.append({"change_type": "line_added", "customer_sku_name": line.customer_sku_name,
                            "field": "", "old_value": "", "new_value": _line_summary(line)})

    for k, new in new_map.items():
        old = old_map.get(k)
        if old is None:
            continue
        for f in LINE_FIELDS:
            a, b = _val(f, getattr(old, f)), _val(f, getattr(new, f))
            if a != b:
                changes.append({"change_type": "line_changed", "customer_sku_name": new.customer_sku_name,
                                "field": f, "old_value": a, "new_value": b})
    return changes


def has_changes(old_header, old_lines, new_header, new_lines) -> bool:
    return bool(diff(old_header, old_lines, new_header, new_lines))


def to_rows(changes: list[dict], *, indent_id: str, from_version: int, to_version: int,
            changed_by: str, changed_at: str) -> list[dict]:
    return [{"changed_at": changed_at, "indent_id": indent_id, "from_version": from_version,
             "to_version": to_version, "changed_by": changed_by, **c} for c in changes]
