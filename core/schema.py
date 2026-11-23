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
MAIL_RECIPIENTS = "Mail_Recipients"
PO_ITEM_MAP = "PO_Item_Map"
MAIL_LOG = "Mail_Log"
DELIVERY_TIMES = "Delivery_Times"   # usual delivery time per store (20 Nov)
STORE_ALIASES = "Store_Aliases"     # Bulk indents: Excel tab name -> customer + store (20 Nov)
# Pre-production (22 Nov, owners only for now; core/preprod.py)
BATCHING_MASTER = "Batching_Master"  # filled by the team: country -> spec (counts) + box kg per SKU
PREPROD_ACTUAL = "Preprod_Actual"    # boxes taken out of storage, one row per SKU + spec per take-out round
PREPROD_FREEZE = "Preprod_Freeze"    # customer frozen / unfrozen for a day (last row wins)
BATCHING_PLAN = "Batching_Plan"      # pieces (kg) used from those boxes (last row per SKU + spec wins)

TABS: dict[str, list[str]] = {
    # Input tabs (maintained by the team). Only used when the sheet has no
    # "All Cux City" tab (see core/importer.py). "Variety" pre-selects the
    # variety and "Lot" fixes the lot for that SKU name; both optional.
    SKU_MAP: ["City", "Customer", "Parent SKU", "Customer SKU Name",
              "Spec-Origin", "Spec-Size", "Active", "Variety", "Lot"],
    STORE_MAP: ["City", "Customer", "Store Name"],
    VARIETIES: ["Parent SKU", "Variety"],
    # Access is edited from the app's Access page (owner only).
    ACCESS: ["Email", "Name", "Role", "Status", "PIN_Hash", "Updated_At", "Updated_By", "City", "Stores",
             "Admin_Page"],
    # Output tabs (written by the app, append-only).
    INDENT_LINES: ["indent_id", "version", "status", "submitted_at", "submitted_by",
                   "delivery_date", "city", "customer", "store", "expected_time",
                   "parent_sku", "customer_sku_name", "variety", "lot", "lot_size", "qty",
                   "price", "amount", "change_note"],
    CHANGE_LOG: ["changed_at", "indent_id", "from_version", "to_version", "changed_by",
                 "change_type", "customer_sku_name", "field", "old_value", "new_value"],
    PO_FREEZE: ["indent_id", "version", "po_file_name", "po_customer", "po_store",
                "confirmed_by", "confirmed_at", "po_file_link", "po_number", "po_total_qty",
                "po_lines", "kind", "po_qty_json"],
    DRAFTS: ["draft_id", "user_email", "updated_at", "payload_json"],
    # Who gets which e-mail, and which cities / customers / stores they see
    # (empty = all). Edited from the Access page.
    MAIL_RECIPIENTS: ["Email", "Name", "Team", "Hourly_Indent", "SO_PO", "Cities", "Customers",
                      "Stores", "Active", "Updated_At", "Updated_By"],
    MAIL_LOG: ["sent_at", "kind", "slot", "to", "status", "detail"],
    # Customer PO item (code or name) -> our Customer SKU Name, for reading PO PDFs.
    # Filled by the app when someone picks a SKU for a PO line; can be edited by hand.
    PO_ITEM_MAP: ["Customer", "PO Item Code", "PO Item Name", "Customer SKU Name", "Updated_At"],
    DELIVERY_TIMES: ["City", "Customer", "Store", "Time", "Updated_At", "Updated_By"],
    STORE_ALIASES: ["City", "Tab Name", "Customer", "Store", "Updated_At", "Updated_By"],
    BATCHING_MASTER: ["City", "Customer", "Customer SKU Name", "Parent SKU", "Country", "Spec", "Unit", "Box Kg"],
    PREPROD_ACTUAL: ["round_id", "saved_at", "saved_by", "delivery_date", "city", "group", "customer_sku_name",
                     "parent_sku", "country", "spec", "boxes", "reason"],
    PREPROD_FREEZE: ["delivery_date", "city", "group", "action", "at", "by"],
    BATCHING_PLAN: ["saved_at", "saved_by", "delivery_date", "city", "group", "customer_sku_name", "country",
                    "spec", "boxes", "used", "unit", "gt_qty", "dump"],
}

MASTER_TABS = [SKU_MAP, STORE_MAP, VARIETIES, ACCESS]
OUTPUT_TABS = [INDENT_LINES, CHANGE_LOG, PO_FREEZE, DRAFTS, MAIL_RECIPIENTS, MAIL_LOG]

DEFAULT_CUSTOMERS = ["Swiggy", "Zomato", "Zepto", "Firstclub", "Namdhari"]
LOTS = ["Kg", "Pcs", "Tray", "Box", "Pack"]  # "Pack" = gram packs (was "gms")

STATUS_SUBMITTED = "Submitted"
STATUS_FROZEN = "Frozen"
STATUS_CANCELLED = "Cancelled"   # "deleted" indent: kept in the sheet, ignored elsewhere
STATUS_LOCKED = "Locked"         # frozen by hand (processing started): no edits, still waiting for its PO
WAITING_FOR_PO = (STATUS_SUBMITTED, STATUS_LOCKED)
PO_KIND = "po"                   # PO_Freeze.kind: one uploaded PO
PO_END = "end"                   # PO_Freeze.kind: "End of POs" pressed (multi-PO customers)

ROLE_OWNER = "owner"               # Owner: his cities (empty = all); Access page only if Admin_Page = yes
ROLE_OWNER_FULL = "owner_full"     # Creator: everything (sheet value kept as owner_full)
OWNER_ROLES = (ROLE_OWNER, ROLE_OWNER_FULL)
ROLE_NAMES = {ROLE_OWNER: "Owner", ROLE_OWNER_FULL: "Creator", "sales": "Sales",
              "warehouse": "Warehouse"}   # shown on screen (21 Nov)


def role_name(role: str) -> str:
    r = str(role or "").strip().lower()
    return ROLE_NAMES.get(r, r)
ROLE_SALES = "sales"
ROLE_WAREHOUSE = "warehouse"   # production / batching only, no indents
ROLES = [ROLE_WAREHOUSE, ROLE_SALES, ROLE_OWNER, ROLE_OWNER_FULL]   # order in the pickers
ACCESS_ACTIVE = "active"
ACCESS_REVOKED = "revoked"

TIMEZONE = "Asia/Kolkata"


def norm_header(name: object) -> str:
    """Normalise a header for matching: 'Spec - Origin', 'spec_origin' -> 'specorigin'."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())
