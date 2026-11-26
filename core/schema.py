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
DISPATCH_LINES = "Dispatch_Lines"    # what was loaded per indent + SKU (Delivery Order); last doc per indent wins
RETURN_LINES = "Return_Lines"        # returned per indent + SKU at the store (final invoice); last save wins
RETURN_GRADING = "Return_Grading"    # returns of day D graded MT / GT / Dump (last row per indent + SKU wins)
CITY_GRADING = "City_Grading"        # 25 Nov: MT / GT / Dump per city + fruit + take-out option (last row wins)
DISPATCH_LOCKS = "Dispatch_Locks"    # 25 Nov: owner unlocks of a dispatched indent (doc_no unlocked)
RETURN_USE = "Return_Use"            # MT stock used per SKU in Pre-production (last row per day + group + SKU)
PUSH_SUBS = "Push_Subs"                # 26 Nov: browser push subscriptions per login e-mail
PUSH_KEYS = "Push_Keys"                # 26 Nov: the app's push key (made once)
PREPROD_ENTRIES = "Production_Actual"  # 25 Nov: lots put on grading tables (Pre-Production Actual page)
BRAND_MASTER = "Brand_Master"         # 26 Nov: brands per SKU (Parent SKU + Origin + Variety + Size)
PROCESSED = "Processed"                # 25 Nov: MT / GT / dump out of each lot (Processed page)
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
    PROCESSED: ["entry_id", "saved_at", "saved_by", "production_date", "city", "parent_sku", "table_no", "lot_id",
                "size", "variety", "box_kg", "pcs_per_box", "boxes_moved", "cux_lot", "pack_kg", "mt_packs",
                "mt_loose_kg", "left_box", "left_kg", "left_pcs", "gt_box", "gt_kg", "gt_pcs", "dump_kg", "dump_pcs",
                "taken_kg", "used_kg", "mt_kg", "gt_kg_total", "dump_kg_total", "lotting_kg", "efficiency", "non_mt",
                "dump_pct", "comment"],
    PREPROD_FREEZE: ["delivery_date", "city", "group", "action", "at", "by"],
    BRAND_MASTER: ["Parent SKU", "Origin", "Variety", "Size", "Brand", "Added by", "Added at"],
    PREPROD_ENTRIES: ["entry_id", "saved_at", "saved_by", "production_date", "city", "parent_sku", "origin",
                      "variety", "brand", "size", "box_kg", "pcs_per_box", "table_no", "boxes_moved",
                      "stock_type"],
    BATCHING_PLAN: ["saved_at", "saved_by", "delivery_date", "city", "group", "customer_sku_name", "country",
                    "spec", "boxes", "used", "unit", "gt_qty", "dump", "mt_grade", "sample", "parent_sku",
                    "variety"],
    DISPATCH_LINES: ["saved_at", "saved_by", "doc_no", "indent_id", "delivery_date", "city", "customer", "store",
                     "customer_sku_name", "lot", "indent_qty", "dispatch_qty", "price", "reason", "vehicle",
                     "driver", "dispatched_at", "club_key", "per", "from_mt", "unit"],
    CITY_GRADING: ["saved_at", "saved_by", "delivery_date", "city", "club_key", "parent_sku", "variety", "unit",
                   "option", "boxes", "fruit", "mt", "gt", "dump"],
    DISPATCH_LOCKS: ["at", "by", "indent_id", "doc_no", "action", "reason"],
    RETURN_LINES: ["saved_at", "saved_by", "invoice_no", "indent_id", "doc_no", "customer_sku_name", "lot",
                   "dispatched", "returned", "reason", "billed", "price", "sample"],
    RETURN_GRADING: ["saved_at", "saved_by", "return_date", "pool_date", "indent_id", "city", "customer",
                     "customer_sku_name", "parent_sku", "variety", "unit", "spec", "returned", "mt", "gt", "dump"],
    RETURN_USE: ["saved_at", "saved_by", "use_date", "city", "group", "customer_sku_name", "parent_sku", "variety",
                 "unit", "qty"],
    PUSH_SUBS: ["Email", "Endpoint", "P256dh", "Auth", "Device", "Status", "Updated_At"],
    PUSH_KEYS: ["Key", "Value", "Created_At"],
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
