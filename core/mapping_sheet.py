"""New Mapping sheet (22 Nov): the team's country / variety / spec / box-kg master.

Read only. Pre-production actual and Batching plan take the countries, grades, counts and box
kg of a SKU from its **Combination 1** tab (one row per customer SKU x country x variety/grade),
and from its **Parent** tab when the customer SKU is not there yet.

The sheet writes customers the warehouse way ("Zepto (KWPL)", "Swiggy - Moksh Enterprises (MOKS)",
"Hyperpure CC-PACK-HUSKUR1") and SKU names the customer's way ("Apple Queen Imported - 2 pcs");
the app has Zepto / Swiggy / Zomato and our names ("2PC - Apple Queen Imported"). A SKU is matched
only inside the same city + customer (never across customers): 1) same name in our style, case
and spaces ignored, 2) same pack and the same words (BH / Imported / Pcs ... ignored), one clear best.

Secret `mapping_sheet_id` (default: the New Mapping sheet). The app's service account needs Viewer.
"""
from __future__ import annotations

import re

import pandas as pd

from core import config

DEFAULT_ID = "1A2zerkNL46XIlJwaBH2kL5TcaT04b_nfk4TVKG54-nM"
COMBO_TAB, PARENT_TAB = "Combination 1", "Parent"

_UNIT = r"(pcs?|pieces?|piece|nos|kgs?|g|gm|gms|grams?|packs?|pkt|box|boxes|tray|trays|punnet)"
_STOP = {"bh", "imported", "import", "imp", "pcs", "pc", "piece", "pieces", "fk", "the", "of", "and", "a",
         "fresh", "premium", "ea"}
_CUSTOMERS = [(r"zepto", "Zepto"), (r"swiggy", "Swiggy"), (r"hyperpure|zomato", "Zomato"), (r"flipkart", "Flipkart"),
              (r"^more", "More"), (r"amazon", "Amazon"), (r"metro", "Metro"), (r"reliance", "Reliance"),
              (r"big ?basket", "Bigbasket"), (r"first ?club", "Firstclub"), (r"namdhari", "Namdhari"),
              (r"trent", "Trent")]


def _c(v) -> str:
    return " ".join(str(v or "").split())


def _k(v) -> str:
    return re.sub(r"[^a-z0-9]", "", _c(v).lower())


def sheet_id() -> str:
    return str(config.get("mapping_sheet_id", DEFAULT_ID) or DEFAULT_ID)


def app_customer(name: str) -> str:
    """'Zepto (KWPL)' -> 'Zepto', 'Hyperpure CPC-BLR9' -> 'Zomato', 'Metro (Reliance Cash & Carry)' -> 'Metro'."""
    low = _c(name).lower()
    for pat, cust in _CUSTOMERS:
        if re.search(pat, low):
            return cust
    return _c(name)


def ptp_city(city: str) -> str:
    c = _c(city)
    return c if not c or re.match(r"(?i)ptp\b", c) else f"PTP {c}"


def pack_prefix(text: str) -> str:
    """'2 pcs (280 - 330 g)' -> '2PC', '200g' -> '200GM', '1 kg' -> '1KG', 'EA' -> '1PC'."""
    p = _c(text).lower()
    m = re.search(rf"(\d+(?:\.\d+)?)\s*{_UNIT}\b", p)
    if m:
        q, u = f"{float(m.group(1)):g}", m.group(2)
        if re.fullmatch(r"pcs?|pieces?|piece|nos", u):
            return f"{q}PC"
        if u.startswith("kg"):
            return f"{q}KG"
        if re.fullmatch(r"g|gm|gms|grams?", u):
            return f"{q}GM"
        if re.fullmatch(r"packs?|pkt|punnet", u):
            return f"{q}Pack"
        if u.startswith("box"):
            return f"{q}Box"
        if u.startswith("tray"):
            return f"{q}Tray"
    if re.search(r"\bea\b", p):
        return "1PC"
    if re.fullmatch(r"kgs?", p):
        return "1KG"
    return ""


def our_name(name: str, packaging: str = "") -> str:
    """Customer name -> our style: 'Apple Queen Imported - 2 pcs (250 - 300 g)' -> '2PC - Apple Queen Imported'."""
    s = _c(name)
    tail = re.compile(rf"\s*[-–,]?\s*\(?\s*\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?\s*{_UNIT}\b.*$", re.I)
    for _ in range(2):
        s = tail.sub("", s).strip()
    s = re.sub(r"\s+EA\b", "", s, flags=re.I)
    s = re.sub(r"\s+pack\.?$", "", s, flags=re.I).rstrip(" -–,") or _c(name)
    p = pack_prefix(packaging) or pack_prefix(name)
    return f"{p} - {s}" if p else s


def _pfx(name: str) -> str:
    m = re.match(r"\s*(\S+)\s-\s", _c(name))
    return m.group(1).lower() if m else ""


def _words(name: str) -> set[str]:
    body = re.sub(r"^\S+\s-\s", "", _c(name)).lower()
    return {w for w in re.split(r"[^a-z0-9]+", body) if w and w not in _STOP}


def _jaccard(a: str, b: str) -> float:
    A, B = _words(a), _words(b)
    u = A | B
    return len(A & B) / len(u) if u else 0.0


def _app_pfx(name: str) -> str:
    """Our pack prefix of an app SKU name, unit case ignored ('1Pc' = '1PC', '200gm' = '200GM')."""
    p = _pfx(name)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(pcs?|gms?|g|kgs?|pack|box|tray)", p)
    if not m:
        return p
    u = m.group(2)
    u = "pc" if u.startswith("pc") else "kg" if u.startswith("kg") else "gm" if u.startswith("g") else u
    return f"{float(m.group(1)):g}{u}"


# ------------------------------------------------------------------ reading

def _read(tab: str) -> pd.DataFrame:
    """A tab of the New Mapping sheet as text (header = first row); empty when not reachable."""
    from core.sheets import get_backend
    b = get_backend()
    client = getattr(b, "client", None)
    try:
        if client is None:      # local mode / tests: data/mapping/<tab>.csv when present
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "data" / "mapping" / f"{tab}.csv"
            return pd.read_csv(p, dtype=str, keep_default_na=False) if p.exists() else pd.DataFrame()
        ws = client.open_by_key(sheet_id()).worksheet(tab)
        vals = ws.get_all_values()
    except Exception:  # noqa: BLE001  (not shared / renamed / quota): pages fall back to the old masters
        return pd.DataFrame()
    if not vals:
        return pd.DataFrame()
    head = [_c(h) or f"col{i}" for i, h in enumerate(vals[0])]
    return pd.DataFrame([r + [""] * (len(head) - len(r)) for r in vals[1:]], columns=head)


def _col(df: pd.DataFrame, *names) -> pd.Series:
    want = {_k(n) for n in names}
    for c in df.columns:
        if _k(c) in want:
            return df[c].map(_c)
    return pd.Series([""] * len(df), index=df.index)


def _box_kg(lot: str) -> float | None:
    s = _c(lot).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", s)
    return float(m.group(1)) if m else None


def combos_from(df: pd.DataFrame) -> pd.DataFrame:
    """Combination 1 rows -> city, customer (app), sku, our, parent, cust_variety, country, grade, spec, box_kg, lot."""
    cols = ["city", "customer", "sku", "our", "parent", "cust_variety", "country", "grade", "spec", "box_kg", "lot"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({
        "city": _col(df, "City").map(ptp_city), "customer": _col(df, "Customer").map(app_customer),
        "sku": _col(df, "SKU Name"), "packaging": _col(df, "Packaging"), "parent": _col(df, "Parent SKU"),
        "cust_variety": _col(df, "Customer Variety"), "country": _col(df, "Country"),
        "grade": _col(df, "Variety (Parent tab)"), "spec": _col(df, "Country Spec"), "lot": _col(df, "Origin Lot"),
    })
    out = out[(out["sku"] != "") & (out["country"] != "")]
    out["our"] = [our_name(s, p) for s, p in zip(out["sku"], out["packaging"])]
    out["box_kg"] = out["lot"].map(_box_kg)
    return out[cols].reset_index(drop=True)


def parent_from(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["parent", "grade", "country", "spec", "lot", "box_kg"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame({"parent": _col(df, "Parent SKU", "Parent Category"), "grade": _col(df, "Variety"),
                        "country": _col(df, "Origin"), "spec": _col(df, "Spec"), "lot": _col(df, "Origin Lot")})
    out = out[out["parent"] != ""]
    out["box_kg"] = out["lot"].map(_box_kg)
    return out[cols].reset_index(drop=True)


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(combos, parent), cached like the other masters."""
    import streamlit as st

    @st.cache_data(ttl=int(config.get("master_refresh_minutes", 5) or 5) * 60, show_spinner=False)
    def _load(sid: str):
        return combos_from(_read(COMBO_TAB)), parent_from(_read(PARENT_TAB))
    return _load(sheet_id())


# ------------------------------------------------------------------ matching

def match_rows(combos: pd.DataFrame, city: str, customer: str, sku_name: str) -> tuple[pd.DataFrame, str]:
    """Combination rows of this app SKU (same city + customer only) and how it was matched."""
    if combos is None or combos.empty:
        return pd.DataFrame(), ""
    same = combos[(combos["city"].map(_k) == _k(city)) & (combos["customer"].map(_k) == _k(customer))]
    if same.empty:
        return same, ""
    hit = same[same["our"].map(_k) == _k(sku_name)]
    if not hit.empty:
        return hit, "same name"
    pf = _app_pfx(sku_name)
    names = {o for o in same["our"].unique() if _app_pfx(o) == pf}
    scored = sorted(((_jaccard(sku_name, o), o) for o in names), reverse=True)
    if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.15):
        return same[same["our"] == scored[0][1]], f"close name: {scored[0][1]}"
    return pd.DataFrame(), ""


def _variety_ok(grade: str, variety: str, parent: str) -> bool:
    v = _k(variety)
    if not v or v == _k(parent):
        return True
    v = {"braeburn": "breaburn", "pinklady": "crippspink"}.get(v, v)
    return _k(grade).startswith(v)


def options(combos: pd.DataFrame, parent_df: pd.DataFrame, city: str, customer: str, sku_name: str,
            parent: str, variety: str = "", unit_default: str = "Box") -> dict[str, dict]:
    """{label: {'spec': [...], 'unit', 'box_kg', 'source', 'country', 'grade', 'lot'}} for one app SKU.
    Label = 'Country · Grade' (grade left out when it is just the fruit), '· <lot>' added when the same
    country + grade comes in boxes of different weights."""
    from core.preprod import parse_spec
    rows, how = match_rows(combos, city, customer, sku_name)
    source = f"Combination 1 ({how})" if how else ""
    if rows.empty and parent_df is not None and not parent_df.empty:
        p = parent_df[parent_df["parent"].map(_k) == _k(parent)]
        p = p[[_variety_ok(g, variety, parent) for g in p["grade"]]]
        rows, source = p, "Parent tab (SKU not in Combination 1 yet)"
    out: dict[str, dict] = {}
    if rows is None or rows.empty:
        return out
    seen = rows.drop_duplicates(subset=["country", "grade", "spec", "lot"])
    multi = seen.groupby([seen["country"].map(_k), seen["grade"].map(_k)]).size()
    for r in seen.to_dict("records"):
        grade = _c(r["grade"])
        show_grade = grade and _k(grade) != _k(r.get("parent") or parent)
        label = _c(r["country"]) + (f" · {grade}" if show_grade else "")
        if multi.get((_k(r["country"]), _k(grade)), 1) > 1 and _c(r["lot"]):
            label += f" · {_c(r['lot'])}"
        if label in out:
            continue
        out[label] = {"spec": parse_spec(r["spec"]), "unit": unit_default, "box_kg": r["box_kg"],
                      "source": source, "country": _c(r["country"]), "grade": grade, "lot": _c(r["lot"])}
    return out
