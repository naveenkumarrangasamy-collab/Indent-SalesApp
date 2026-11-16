"""Speed / draft behaviour: closed edits are not reopened; adding items does not force a sheet write."""
import streamlit as st

from core.models import IndentHeader, IndentLine
from pages_src import state


def _edit_state(day: str, po_fix=None):
    hdr = IndentHeader(delivery_date=day, city="PTP Bangalore", customer="Swiggy", store="Swiggy WH1").to_dict()
    st.session_state[state.KEY] = {**state.blank(), "mode": "edit", "indent_id": "IN-002", "base_version": 1,
                                   "base": {"header": hdr, "lines": []}, "header": hdr, "po_fix": po_fix}


def test_closed_edit_is_cleared_but_open_or_po_fix_kept():
    _edit_state("2020-01-01")
    assert state.drop_closed_edit() == "IN-002" and state.get()["mode"] == "new"
    _edit_state("2020-01-01", po_fix={"po_qty": {}})
    assert state.drop_closed_edit() is None and state.get()["mode"] == "edit"
    _edit_state("2099-01-01")
    assert state.drop_closed_edit() is None and state.get()["mode"] == "edit"


def test_adding_items_does_not_force_an_immediate_sheet_write():
    st.session_state[state.KEY] = state.blank()
    st.session_state.pop("draft_force", None)
    state.set_lines([IndentLine(parent_sku="Kiwi", customer_sku_name="1Pc - Green Kiwi", lot="Pcs", qty=1, price=1)],
                    structural=True)
    assert st.session_state.get("draft_dirty") and not st.session_state.get("draft_force")
    assert state.THROTTLE_SECONDS == 60
