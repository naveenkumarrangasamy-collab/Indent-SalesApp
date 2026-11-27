"""24 Nov (user-approved): the ops team's "BLR FF Ops - Tracker" sheet gets columns A-M filled
by the app, so nobody copy-pastes the Batching sheet any more.

Columns A-M of the tab (secret `dispatch_sheet_tab`, default "Copy of 03 - BLR_MTDispatch"):
Date, City, Customer, Delivery point, Parent SKU, Customer SKU Name, Variety, Lot, Lot Size, Spec,
Indent Qty, Cux PO Qty, Diff in Indent and PO (PO - indent).

Rules (user 24 Nov 4:41 PM):
- The app writes ONLY columns A-M. Columns N onwards are typed by people and never touched.
- A row is found again by Date + Customer + Delivery point + Customer SKU Name + Variety; it only
  gets its A-M values / colour updated. Rows are never moved, sorted or deleted.
- A new indent line becomes a NEW row under the last row that has anything in A-M.
- An item that left the indent (qty 0 / indent cancelled) keeps its row with Indent Qty 0.
- Colours like the Batching sheet: red = PO lower / not on PO, yellow = PO higher,
  orange = on the PO but not on the indent, white = match / no PO yet.
- Runs on the app's server after every indent save / PO upload / freeze (background, with the
  Indent_vs_PO tab), once after a redeploy and on every hourly trigger, so it never depends on
  anyone's own computer being online. Only cities in `dispatch_sheet_cities` (PTP Bangalore).
The sheet must be shared with the app's service account as Editor."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from core import config

WIDTH = 14          # A..N once the tab has its Facility column (27 Nov); A..M before that
FAC = 2             # Facility sits after City (column C)
EPOCH = dt.date(1899, 12, 30)
WHITE = (1.0, 1.0, 1.0)
COLOURS = {"PO lower": (0.973, 0.788, 0.788), "Not on PO": (0.973, 0.788, 0.788),
           "PO higher": (1.0, 0.910, 0.604), "Not on indent": (1.0, 0.827, 0.631)}


def sheet_id() -> str:
    return str(config.get("dispatch_sheet_id", "12Zc6-C19dHKxrrdI1XsHn0Hl8zt-mbhxyssb9m5eVTk")).strip()


def tab_name() -> str:
    return str(config.get("dispatch_sheet_tab", "Auto 03 - BLR_MTDispatch")).strip()


def tab_gid() -> int:
    """The tab's fixed id (survives renames; was 'Copy of 03 …', renamed 'Auto 03 …' on 24 Nov)."""
    try:
        return int(config.get("dispatch_sheet_gid", 339596934))
    except (TypeError, ValueError):
        return 0


def _worksheet(client):
    ss = client.open_by_key(sheet_id())
    if tab_gid():
        try:
            return ss.get_worksheet_by_id(tab_gid())
        except Exception:  # noqa: BLE001 - fall back to the name
            pass
    return ss.worksheet(tab_name())


def cities() -> set[str]:
    v = config.get("dispatch_sheet_cities", ["PTP Bangalore"])
    v = [v] if isinstance(v, str) else list(v or [])
    return {str(x).strip().casefold() for x in v if str(x).strip()}


def start_date() -> str:
    """First delivery date written to the tab (user 24 Nov 4:50 PM: start from 24 Nov)."""
    return str(config.get("dispatch_sync_from", "2026-11-24")).strip()[:10]


def days_back() -> int:
    try:
        return int(config.get("dispatch_sync_days_back", 2))
    except (TypeError, ValueError):
        return 2


# ------------------------------------------------------------------ pure helpers (tested)

def _cf(v) -> str:
    return " ".join(str(v or "").split()).casefold()


def serial(day) -> int | None:
    """A date as the Google Sheets day number (what UNFORMATTED_VALUE returns for a date cell)."""
    if isinstance(day, (int, float)) and not isinstance(day, bool):
        return int(day)
    s = str(day or "").strip()
    if not s:
        return None
    for dayfirst in (False, True):
        try:
            d = pd.to_datetime(s, dayfirst=dayfirst, errors="raise").date()
            return (d - EPOCH).days
        except (ValueError, TypeError):
            continue
    return None


def key(day, customer, point, sku, variety) -> tuple:
    return (serial(day), _cf(customer), _cf(point), _cf(sku), _cf(variety))


def _num(v):
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return ""
    f = float(v)
    return int(f) if f.is_integer() else round(f, 3)


def to_rows(view: pd.DataFrame) -> list[dict]:
    """Batching view (with 'Delivery date', with_po columns) -> [{key, values (13), status}]."""
    out = []
    for r in view.to_dict("records"):
        vals = [str(r["Delivery date"])[:10], r["City"], r.get("Facility", ""), r["Customer"], r["Delivery point"],
                r.get("Parent SKU", ""),
                r["Customer SKU Name"], r.get("Variety", ""), r.get("Lot", ""), r.get("Lot Size", ""),
                r.get("Spec", ""), _num(r.get("Indent qty")), _num(r.get("PO qty")), _num(r.get("Difference"))]
        vals = ["" if v is None or (isinstance(v, float) and pd.isna(v)) else v for v in vals]
        out.append({"key": key(vals[0], vals[3], vals[4], vals[6], vals[7]), "values": vals,
                    "status": r.get("Status", "")})
    return out


def _same(a, b) -> bool:
    if a in ("", None) and b in ("", None):
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return _cf(a) == _cf(b)


def plan(existing: list[list], new: list[dict], day_serials: set[int], city_set: set[str],
         first_data_row: int = 2) -> dict:
    """What to write. existing = A-M values of the tab from `first_data_row` on (unformatted: dates
    as day numbers). Returns {"update": [(row, values, status)], "append_at": row,
    "append": [(values, status)]}. Changed rows only; nothing is ever deleted or moved."""
    by_key: dict[tuple, int] = {}
    last_used = first_data_row - 1
    for i, r in enumerate(existing):
        row = first_data_row + i
        r = list(r) + [""] * (WIDTH - len(r))
        if any(str(x).strip() for x in r[:WIDTH]):
            last_used = row
            k = key(r[0], r[3], r[4], r[6], r[7])
            if k[0] is not None and k not in by_key:
                by_key[k] = row
    update, append, seen = [], [], set()
    for n in new:
        row = by_key.get(n["key"])
        seen.add(n["key"])
        if row is None:
            append.append((n["values"], n["status"]))
            continue
        old = list(existing[row - first_data_row]) + [""] * WIDTH
        vals = n["values"]
        if not all(_same(o, v) for o, v in zip(old[1:WIDTH], vals[1:WIDTH])):
            update.append((row, vals, n["status"]))
    for k, row in by_key.items():               # left the indent: keep the row, Indent Qty 0
        if k in seen or k[0] not in day_serials:
            continue
        old = list(existing[row - first_data_row]) + [""] * WIDTH
        if _cf(old[1]) not in city_set or _same(old[11], 0):
            continue
        po = old[12]
        has_po = str(po).strip() != ""
        vals = [_date_text(k[0])] + list(old[1:11]) + [0, po, _num(po) if has_po else ""]
        update.append((row, vals, "Not on indent" if has_po and not _same(po, 0) else ""))
    append.sort(key=lambda a: (str(a[0][0]), _cf(a[0][2]), _cf(a[0][3]), _cf(a[0][4]), _cf(a[0][5])))
    return {"update": update, "append_at": last_used + 1, "append": append}


def _date_text(s: int) -> str:
    return (EPOCH + dt.timedelta(days=int(s))).isoformat()


# ------------------------------------------------------------------ building + writing

def build(lines: pd.DataFrame, m, days: list[str]) -> list[dict]:
    """Current indent lines (all cities) -> rows for the tab (only `cities()`, only `days`)."""
    from core import indents
    from core.production_calc import batching, with_po
    from pages_src.production import _po_quantities

    cur = indents.current_rows(lines)
    if cur.empty:
        return []
    cur = cur[cur["city"].map(_cf).isin(cities()) & cur["delivery_date"].astype(str).str[:10].isin(days)]
    if cur.empty:
        return []
    po_qty, po_ids, extras = _po_quantities(cur)
    out = []
    for day, part in cur.groupby("delivery_date", sort=True):
        v = with_po(batching(part, m), po_qty, po_ids, [e for e in extras if e["day"] == day])
        v.insert(0, "Delivery date", str(day)[:10])
        fac = {(_cf(c), _cf(s)): config.facility_of(ci, f) for ci, c, s, f in
               zip(part["city"], part["customer"], part["store"], part.get("facility", [""] * len(part)))}
        v["Facility"] = [fac.get((_cf(c), _cf(s))) or config.facility_of(ci)
                         for ci, c, s in zip(v["City"], v["Customer"], v["Delivery point"])]
        out += to_rows(v)
    return out


def _a1(row: int, col: int) -> str:
    from gspread.utils import rowcol_to_a1
    return rowcol_to_a1(row, col)


def has_facility(head: list) -> bool:
    """True when the tab's header row has the Facility column after City (column C)."""
    return len(head) > FAC and _cf(head[FAC]) == "facility"


def widen(rows: list[list]) -> list[list]:
    """Old layout (A-M, no Facility) -> the 14 values used here (blank facility)."""
    out = []
    for r in rows:
        r = list(r)
        out.append(r[:FAC] + [""] + r[FAC:] if len(r) > FAC else r)
    return out


def write(ws, p: dict, fac: bool = True) -> int:
    """Apply a plan to the worksheet: values with USER_ENTERED (dates become dates), only the app's
    columns (A-N with the Facility column, A-M on a tab that has none yet)."""
    last = "N" if fac else "M"
    cut = (lambda v: v) if fac else (lambda v: v[:FAC] + v[FAC + 1:])
    data, fmts = [], []
    for row, vals, status in p["update"]:
        data.append({"range": f"A{row}:{last}{row}", "values": [cut(vals)]})
        fmts.append((row, row, status))
    if p["append"]:
        start = p["append_at"]
        end = start + len(p["append"]) - 1
        if ws.row_count < end:
            ws.add_rows(end - ws.row_count + 50)
        data.append({"range": f"A{start}:{last}{end}", "values": [cut(v) for v, _ in p["append"]]})
        fmts += [(start + i, start + i, s) for i, (_, s) in enumerate(p["append"])]
    if not data:
        return 0
    ws.batch_update(data, value_input_option="USER_ENTERED")
    ws.batch_format([{"range": f"A{a}:{last}{b}",
                      "format": {"backgroundColor": dict(zip(("red", "green", "blue"), COLOURS.get(s, WHITE)))}}
                     for a, b, s in fmts])
    return len(data)


def sync(backend=None, lines: pd.DataFrame | None = None, m=None, today: dt.date | None = None) -> str:
    """Bring the tab up to date for the last `days_back()` days, today and tomorrow. Never raises."""
    try:
        from core import indents, masters
        b = backend or indents.get_backend()
        client = getattr(b, "client", None)
        if client is None or not sheet_id():
            return "skipped: no Google connection"
        today = today or config.now_ist().date()
        days = [(today + dt.timedelta(days=k)).isoformat() for k in range(-days_back(), 2)]
        days = [d for d in days if d >= start_date()]
        if not days:
            return "skipped: before the start date"
        lines = lines if lines is not None else indents.prepare(b.read(indents.INDENT_LINES))
        m = m if m is not None else masters.load_masters()
        new = build(lines, m, days)
        ws = _worksheet(client)
        head = ws.get("A1:N1")
        fac = has_facility(head[0] if head else [])
        existing = ws.get("A2:N" if fac else "A2:M", value_render_option="UNFORMATTED_VALUE",
                          date_time_render_option="SERIAL_NUMBER")
        if not fac:
            existing = widen(existing)
            for x in new:                     # no Facility column yet: nothing to compare or write there
                x["values"][FAC] = ""
        p = plan(existing, new, {serial(d) for d in days}, cities())
        n = write(ws, p, fac)
        return f"ok: {len(p['update'])} updated, {len(p['append'])} added" if n else "ok: up to date"
    except Exception as e:  # noqa: BLE001 - only a copy for the ops team; the next save tries again
        return f"error {type(e).__name__}: {e}"
