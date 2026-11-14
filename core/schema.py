"""Tab names, column headers and fixed lists used across the app.

The app always reads tabs by header name (see core/sheets.py), so the order
of columns in the Google Sheet does not matter. These lists are the canonical
names and the order used when the app creates a tab.
"""
from __future__ import annotations

import re

SKU_MAP = "SKU_Map"
STORE_MAP = "Store_Map"
VARIETIES = "Varieties"
ACCESS = "Access"
INDENT_LINES = "Indent_Lines"
CHANGE_LOG = "Change_Log"
PO_FREEZE = "PO_Freeze"
DRAFTS = "Drafts"

TABS: dict[str, list[str]] = {
    # Input tabs (maintained by the team). Only used when the sheet has no
    # "All Cux City" tab (see core/importer.py). "Variety" pre-selects the
    # variety and "Lot" fixes the lot for that SKU name; both optional.
    SKU_MAP: ["City", "Customer", "Parent SKU", "Customer SKU Name",
              "Spec-Origin", "Spec-Size", "Active", "Variety", "Lot"],
    STORE_MAP: ["City", "Customer", "Store Name"],
    VARIETIES: ["Parent SKU", "Variety"],
    # Access is edited from the app's Access page (owner only).
    ACCESS: ["Email", "Name", "Role", "Status", "PIN_Hash", "Updated_At", "Updated_By"],
    # Output tabs (written by the app, append-only).
    INDENT_LINES: ["indent_id", "version", "status", "submitted_at", "submitted_by",
                   "delivery_date", "city", "customer", "store", "expected_time",
                   "parent_sku", "customer_sku_name", "variety", "lot", "lot_size", "qty",
                   "price", "amount"],
    CHANGE_LOG: ["changed_at", "indent_id", "from_version", "to_version", "changed_by",
                 "change_type", "customer_sku_name", "field", "old_value", "new_value"],
    PO_FREEZE: ["indent_id", "version", "po_file_name", "po_customer", "po_store",
                "confirmed_by", "confirmed_at", "po_file_link"],
    DRAFTS: ["draft_id", "user_email", "updated_at", "payload_json"],
}

MASTER_TABS = [SKU_MAP, STORE_MAP, VARIETIES, ACCESS]
OUTPUT_TABS = [INDENT_LINES, CHANGE_LOG, PO_FREEZE, DRAFTS]

DEFAULT_CUSTOMERS = ["Swiggy", "Zomato", "Zepto", "Firstclub", "Namdhari"]
LOTS = ["Kg", "Pcs", "Tray", "Box", "Pack"]  # "Pack" = gram packs (was "gms")

STATUS_SUBMITTED = "Submitted"
STATUS_FROZEN = "Frozen"
STATUS_CANCELLED = "Cancelled"   # "deleted" indent: kept in the sheet, ignored elsewhere

ROLE_OWNER = "owner"
ROLE_SALES = "sales"
ACCESS_ACTIVE = "active"
ACCESS_REVOKED = "revoked"

TIMEZONE = "Asia/Kolkata"


def norm_header(name: object) -> str:
    """Normalise a header for matching: 'Spec - Origin', 'spec_origin' -> 'specorigin'."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())
