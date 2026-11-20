"""Bulk indents (20 Nov, user-approved): one Excel per city, one sheet tab per store
(tab name = the store, e.g. 'Swiggy WH1', 'Zepto - Yalachanayakanapura'), columns
Customer SKU name | UOM | Qty. Every tab becomes a new indent, or updates that store's
indent for the day (only when a qty changed); new customers, stores and SKUs are
created. The page is pages_src/bulk_indents.py; the logic here is plain and tested."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core import master_add


def key(s) -> str:
    return " ".join(str(s or "").split()).casefold()


def _squash(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").casefold())


def all_parents(m) -> list[str]:
    out = []
    for cty in m.cities():
        for c in m.customers(cty):
            out += m.parents(cty, c)
    return list(dict.fromkeys(p for p in out if p))


def names_for(m, city: str, customer: str) -> dict[str, str]:
    out = {}
    for p in m.parents(city, customer):
        for n in m.sku_names(city, customer, p):
            out[key(n)] = n
    return out


def match_name(name: str, names: dict[str, str], links: dict[str, str], parents: list[str]) -> tuple[str, str]:
    """(our SKU name, status) for one file line: 'ok' (a SKU we have: saved link, or the
    exact name in our style), 'new' (its fruit exists: added on save), 'red' (new fruit)."""
    linked = links.get(key(name))
    ours = master_add.new_sku_name(name)
    hit = (names.get(key(linked)) if linked else None) or names.get(key(ours)) or names.get(key(name))
    if hit:
        return hit, "ok"
    if master_add.guess_parent(ours, parents) or master_add.guess_parent(name, parents):
        return ours, "new"
    return ours, "red"


@dataclass
class Line:
    sku: str
    qty: float
    status: str                       # ok / new / red
    texts: list[str] = field(default_factory=list)
    qtys: list[float] = field(default_factory=list)
    code: str = ""

    @property
    def combined(self) -> bool:
        return len(self.qtys) > 1


def lines_for(read, names: dict[str, str], links: dict[str, str], parents: list[str]) -> list[Line]:
    """The file lines of one tab, matched; the same SKU twice is added up (370 + 49)."""
    out: dict[str, Line] = {}
    for x in read.lines:
        sku, status = match_name(x.name, names, links, parents)
        k = key(sku)
        if k in out:
            ln = out[k]
            ln.qty += float(x.qty)
            ln.texts.append(x.name)
            ln.qtys.append(float(x.qty))
        else:
            out[k] = Line(sku=sku, qty=float(x.qty), status=status, texts=[x.name], qtys=[float(x.qty)],
                          code=x.code)
    return list(out.values())


def resolve_tab(tab: str, city_stores: list[tuple[str, str]], aliases: dict[str, tuple[str, str]],
                customers: list[str]) -> tuple[str, str, str]:
    """(customer, store, how) for a tab name. city_stores: [(customer, store)] of the city.
    how: 'saved' (remembered tab name), 'store' (the exact store name), 'customer' (a customer
    with one store), 'close' (one store whose name contains the tab name or the other way
    round), '' (pick it)."""
    t = key(tab)
    if t in aliases and aliases[t][1]:
        return aliases[t][0], aliases[t][1], "saved"
    for c, s in city_stores:
        if key(s) == t or _squash(s) == _squash(tab):
            return c, s, "store"
    by_cust = {}
    for c, s in city_stores:
        by_cust.setdefault(key(c), []).append((c, s))
    if t in by_cust and len(by_cust[t]) == 1:
        return by_cust[t][0][0], by_cust[t][0][1], "customer"
    close = [(c, s) for c, s in city_stores if _squash(tab) and
             (_squash(tab) in _squash(s) or _squash(s) in _squash(tab))]
    if len(close) == 1:
        return close[0][0], close[0][1], "close"
    cust = next((c for c in customers if _squash(c) and _squash(tab).startswith(_squash(c))), "")
    return cust, "", ""


def compare(saved: dict[str, float], lines: list[Line]) -> tuple[list[str], list[str]]:
    """Against the store's saved indent: (changed 'name a→b', added names). Saved items
    that are not in the file are left as they are."""
    changed, added = [], []
    for ln in lines:
        k = key(ln.sku)
        if k not in saved:
            added.append(ln.sku)
        elif abs(saved[k] - ln.qty) > 1e-9:
            changed.append(f"{ln.sku} {saved[k]:g}→{ln.qty:g}")
    return changed, added


def duplicate_names(sku_df) -> list[dict]:
    """Access → Duplicate names (20 Nov): per city + customer, SKU names that are the same
    fruit written more than once: the exact same name on several rows, or the same words
    with a different pack / order ('1Pack - Kiwi Sungold', '2PC - Kiwi Sungold',
    '2PC - Sungold Kiwi'). Words like Bloom / Snacky make a different product."""
    from core.po_reader import our_key
    groups: dict[tuple, list[str]] = {}
    for r in sku_df.to_dict("records"):
        name = str(r.get("Customer SKU Name") or "").strip()
        if not name:
            continue
        words, _ = our_key(name)
        if not words:
            continue
        g = (key(r.get("City")), key(r.get("Customer")), frozenset(words))
        groups.setdefault(g, []).append(name)
    out = []
    for (city, cust, _), names in groups.items():
        distinct = list(dict.fromkeys(names))
        if len(names) > 1:
            first = next(r for r in sku_df.to_dict("records") if key(r.get("City")) == city
                         and key(r.get("Customer")) == cust)
            out.append({"City": first.get("City"), "Customer": first.get("Customer"),
                        "Names": " | ".join(f"{n} ×{names.count(n)}" if names.count(n) > 1 else n
                                            for n in distinct),
                        "Kind": "same name on several rows" if len(distinct) == 1 else
                        f"{len(distinct)} names, same words (check the packs)"})
    return sorted(out, key=lambda r: (str(r["City"]), str(r["Customer"]), r["Names"]))
