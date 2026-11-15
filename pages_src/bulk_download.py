"""Owner only: pick indents (or Select all) and download them as one Excel."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import config, indents, reports
from core.auth import User


def build_xlsx(lines: pd.DataFrame, ids: list[str], po: dict | None = None) -> bytes:
    """One workbook: 'Indents' (one row per indent) and 'Lines' (every item)."""
    cur = indents.current_rows(lines, include_cancelled=True)
    cur = cur[cur["indent_id"].isin(ids)]
    po = po or {}
    summ = []
    for iid, part in cur.groupby("indent_id", sort=False):
        r = part.iloc[0]
        p = po.get(str(iid), {})
        summ.append({"Indent": iid, "Status": reports.STATUS_WORDS.get(r["status"], r["status"]),
                     "Delivery date": r["delivery_date"], "City": r["city"], "Customer": r["customer"],
                     "Store": r["store"], "Items": len(part), "Qty": float(part["qty"].sum()),
                     "Amount": round(float(part["amount"].sum()), 2),
                     "PO number": str(p.get("po_number", "") or ""), "Version": int(r["version"]),
                     "Created by": indents.creator_of(lines, iid)})
    s = pd.DataFrame(summ)
    if not s.empty:
        s = s.sort_values(["Delivery date", "Customer", "Store"]).reset_index(drop=True)
    det = reports.customer_df(cur)
    if not det.empty:
        day = dict(zip(cur["indent_id"], cur["delivery_date"]))
        det.insert(0, "Delivery date", det["Indent"].map(day))
    return reports.xlsx({"Indents": s, "Lines": det})


def _po_info() -> dict:
    try:
        po = indents.read_po_freeze()
    except Exception:  # noqa: BLE001 - PO numbers are optional in the download
        return {}
    if po is None or po.empty or "indent_id" not in po.columns:
        return {}
    return {str(r.get("indent_id", "")): r for r in po.to_dict("records")}


def render(user: User, lines: pd.DataFrame, shown_ids: list[str], key: str, po: dict | None = None) -> None:
    """A compact 'Bulk download' box. Nothing for non-owners."""
    if not user.is_owner or not shown_ids:
        return
    with st.expander(f"⬇ Bulk download (owner) · {len(shown_ids)} indents shown", expanded=False):
        all_on = st.checkbox(f"Select all {len(shown_ids)} indents shown", key=f"{key}_all")
        picked = shown_ids if all_on else st.multiselect(
            "Indents", shown_ids, key=f"{key}_pick", placeholder="Choose indents, or tick Select all")
        if not picked:
            st.caption("Tick **Select all** or choose indents to download.")
            return
        stamp = config.now_ist().strftime("%Y%m%d_%H%M")
        st.download_button(f"Download {len(picked)} indents (Excel)", build_xlsx(lines, list(picked), po if po is not None else _po_info()),
                           file_name=f"indents_{stamp}.xlsx", mime=reports.XLSX, type="primary",
                           icon=":material/download:", key=f"{key}_dl")
