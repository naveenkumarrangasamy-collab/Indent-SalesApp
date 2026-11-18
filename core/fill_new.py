"""Fill the empty spec of New-tab rows from the 'Mapping Whole' tab (19 Nov).

For every New-tab row with no Spec-Size and no Spec-Origin, the closest SKU in
Mapping Whole is found: the same Customer SKU Name first, else the same Parent
SKU with the most alike name (pack written the same way counts most). Its rows
give the origin(s) and size; the active origin (Active = Y, else the first)
fills the row itself and every other origin is proposed as an extra New-tab row.
Repacking comes from the New tab's own rows of that reference SKU, if any."""
from __future__ import annotations

import difflib
import re

from core import importer
from core.po_reader import our_key
from core.schema import norm_header


def _s(v) -> str:
    return " ".join(str(v or "").split())


def _words(name: str) -> str:
    w, _ = our_key(name)
    return " ".join(sorted(w))


def _recs(values: list[list]) -> tuple[list[str], list[dict]]:
    if not values:
        return [], []
    head = [norm_header(h) for h in values[0]]
    out = []
    for i, row in enumerate(values[1:], start=2):            # sheet row number
        r = {h: _s(row[j]) if j < len(row) else "" for j, h in enumerate(head) if h}
        r["_row"] = i
        out.append(r)
    return head, out


def _best(name: str, parent: str, cands: dict[str, list[dict]]) -> str:
    """Name of the closest Mapping Whole SKU (same parent), '' when none."""
    if name.casefold() in cands:
        return name.casefold()
    _, pack = our_key(name)
    want = _words(name)
    best, score = "", 0.0
    for key, rows in cands.items():
        if rows[0].get("parentsku", "").casefold() != parent.casefold():
            continue
        s = difflib.SequenceMatcher(None, want, _words(rows[0]["customerskuname"])).ratio()
        if pack and our_key(rows[0]["customerskuname"])[1] == pack:
            s += 0.25
        if s > score:
            best, score = key, s
    return best


def plan(new_values: list[list], mw_values: list[list]) -> list[dict]:
    """One proposal per empty New-tab row."""
    head, new_rows = _recs(new_values)
    _, mw = _recs(mw_values)
    cands: dict[str, list[dict]] = {}
    for r in mw:
        if r.get("customerskuname") and (r.get("specsize") or r.get("specorigin")):
            cands.setdefault(r["customerskuname"].casefold(), []).append(r)
    repack = {}
    for r in new_rows:
        rp = r.get("specrepacking") or r.get("repacking", "")
        if rp and r.get("customerskuname"):
            repack.setdefault(r["customerskuname"].casefold(), rp)
    out = []
    for r in new_rows:
        if not r.get("customerskuname") or r.get("specsize") or r.get("specorigin"):
            continue
        ref = _best(r["customerskuname"], r.get("parentsku", ""), cands)
        rows = cands.get(ref, [])
        active = [x for x in rows if x.get("active", "").casefold() in {"y", "yes", "true", "1"}]
        order = active + [x for x in rows if x not in active]
        seen, origins = set(), []
        for x in order:
            k = (x.get("specorigin", "").casefold(), x.get("specsize", "").casefold())
            if k not in seen:
                seen.add(k)
                origins.append((x.get("specorigin", ""), x.get("specsize", "")))
        first = origins[0] if origins else ("", "")
        out.append({"Row": r["_row"], "City": r.get("city", ""), "Customer": r.get("customer", ""),
                    "Parent SKU": r.get("parentsku", ""), "Customer SKU Name": r["customerskuname"],
                    "Reference (Mapping Whole)": rows[0]["customerskuname"] if rows else "",
                    "Spec-Origin": first[0], "Spec-Size": first[1],
                    "Spec-Repacking": repack.get(ref, "") or r.get("specrepacking", ""),
                    "Other origins": "; ".join(f"{o} {s}".strip() for o, s in origins[1:])})
    return out


def apply(backend, rows: list[dict]) -> list[str]:
    """Write the chosen origin/size/repacking into the New-tab rows and append one
    extra row per other origin ('Peru 16mm; Chile 18mm')."""
    tab = importer.PROD_BASE
    values = backend.read_values(tab) or []
    if not values:
        return []
    head = [norm_header(h) for h in values[0]]
    col = {k: head.index(k) for k in ("specorigin", "specsize", "specrepacking") if k in head}
    n_upd, extra = 0, []
    for r in rows:
        cells = {}
        for key, field in (("specorigin", "Spec-Origin"), ("specsize", "Spec-Size"),
                           ("specrepacking", "Spec-Repacking")):
            if key in col and _s(r.get(field)):
                cells[col[key]] = _s(r[field])
        if cells:
            backend._update_raw(tab, int(r["Row"]), cells)
            n_upd += 1
        for part in [p.strip() for p in str(r.get("Other origins") or "").split(";") if p.strip()]:
            m = re.match(r"(.+?)\s+(\S*\d\S*.*)$", part)
            origin, size = (m.group(1), m.group(2)) if m else (part, "")
            src = values[int(r["Row"]) - 1]
            row = list(src) + [""] * (len(head) - len(src))
            if "specorigin" in col:
                row[col["specorigin"]] = origin
            if "specsize" in col:
                row[col["specsize"]] = size
            if "specrepacking" in col and _s(r.get("Spec-Repacking")):
                row[col["specrepacking"]] = _s(r["Spec-Repacking"])
            extra.append(row)
    if extra:
        backend._append_raw(tab, extra)
    return [f"{n_upd} New-tab rows filled"] + ([f"{len(extra)} extra origin rows added"] if extra else [])
