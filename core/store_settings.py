"""Per-store settings kept in the Google Sheet (20 Nov):

- Delivery_Times: the usual expected delivery time of each store (City, Customer,
  Store, Time 'HH:MM'). Create indent and Bulk indents start from it; a store
  without one must get a time typed once (then it is saved here).
- Store_Aliases: an Excel tab name used in Bulk indents -> City + Customer + Store,
  remembered after it is matched once (tab names are limited to 31 characters)."""
from __future__ import annotations

import pandas as pd

from core import config
from core.schema import DELIVERY_TIMES, STORE_ALIASES


def _k(*parts) -> tuple:
    return tuple(" ".join(str(p or "").split()).casefold() for p in parts)


def _read(backend, tab: str) -> pd.DataFrame:
    """backend None = the app's cached read (cleared on every save)."""
    from core import indents
    try:
        b = backend or indents.get_backend()
        if tab not in b.list_tabs():
            return pd.DataFrame()
        return indents._cached_tab(tab) if backend is None else b.read(tab)
    except Exception:  # noqa: BLE001 - missing tab = nothing saved yet
        return pd.DataFrame()


def times(backend=None) -> dict[tuple, str]:
    """{(city, customer, store): 'HH:MM'}; the last row for a store wins."""
    df = _read(backend, DELIVERY_TIMES)
    out = {}
    for r in df.to_dict("records") if not df.empty else []:
        t = str(r.get("Time") or "").strip()
        if t:
            out[_k(r.get("City"), r.get("Customer"), r.get("Store"))] = t[:5]
    return out


def time_for(backend, city: str, customer: str, store: str) -> str:
    return times(backend).get(_k(city, customer, store), "")


def save_times(backend, rows: list[dict], user: str) -> int:
    """rows: [{City, Customer, Store, Time}]. Rewrites the tab with every store's
    latest time (one row per store). Returns how many stores have a time."""
    cur = {k: {"City": "", "Customer": "", "Store": "", "Time": v} for k, v in times(backend).items()}
    df = _read(backend, DELIVERY_TIMES)
    for r in df.to_dict("records") if not df.empty else []:
        k = _k(r.get("City"), r.get("Customer"), r.get("Store"))
        if k in cur:
            cur[k].update({"City": r.get("City"), "Customer": r.get("Customer"), "Store": r.get("Store"),
                           "Updated_At": r.get("Updated_At", ""), "Updated_By": r.get("Updated_By", "")})
    stamp = config.now_iso()
    for r in rows:
        k = _k(r["City"], r["Customer"], r["Store"])
        t = str(r.get("Time") or "").strip()
        if not t:
            cur.pop(k, None)
            continue
        old = cur.get(k, {})
        if old.get("Time") != t:
            cur[k] = {"City": r["City"], "Customer": r["Customer"], "Store": r["Store"], "Time": t,
                      "Updated_At": stamp, "Updated_By": user}
    head = ["City", "Customer", "Store", "Time", "Updated_At", "Updated_By"]
    values = [head] + [[v.get(h, "") for h in head] for v in sorted(cur.values(), key=lambda x: (
        str(x["City"]), str(x["Customer"]), str(x["Store"])))]
    backend.replace_tab(DELIVERY_TIMES, values)
    _clear()
    return len(cur)


def aliases(backend, city: str) -> dict[str, tuple[str, str]]:
    """{tab name (normalised): (customer, store)} for one city."""
    df = _read(backend, STORE_ALIASES)
    out = {}
    for r in df.to_dict("records") if not df.empty else []:
        if _k(r.get("City")) == _k(city) and str(r.get("Tab Name") or "").strip():
            out[_k(r["Tab Name"])[0]] = (str(r.get("Customer") or "").strip(), str(r.get("Store") or "").strip())
    return out


def save_aliases(backend, city: str, pairs: list[tuple[str, str, str]], user: str) -> None:
    """pairs: [(tab name, customer, store)] -> appended (the last one wins when read)."""
    stamp = config.now_iso()
    rows = [{"City": city, "Tab Name": t, "Customer": c, "Store": s, "Updated_At": stamp, "Updated_By": user}
            for t, c, s in pairs if t and c and s]
    if rows:
        backend.append_dicts(STORE_ALIASES, rows)
        _clear()


def _clear() -> None:
    from core import indents
    try:
        indents.clear_cache()
    except Exception:  # noqa: BLE001
        pass
