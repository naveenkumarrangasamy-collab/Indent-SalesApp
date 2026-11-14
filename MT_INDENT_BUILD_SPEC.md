# MT Indent App: Streamlit Build Spec

Hand this file to Claude Code as the project brief (save it in the repo root, and copy the "Kickoff prompt" at the end into the first message).

## 1. What we are building

A web app for the MT Direct Sales team (customers: Swiggy, Zomato, Zepto, Firstclub, Namdhari) to raise sales-order indents. Every submitted indent and every later correction is saved in a Google Sheet. The SKU mapping and the customer-to-store mapping are read from the same Google Sheet. A production sheet then shows what has to be produced from the submitted indents.

Process being replaced: MT SO to Dispatch, streamlining.

Users and roles:
- **Owner**: grants access, sees everything, edits master data in the sheet.
- **Sales**: signs in with a work email the owner has approved, raises and corrects their own indents.

## 2. Tech stack

- Python 3.11+, Streamlit 1.42 or newer (built-in `st.login` / `st.user` for sign-in)
- `Authlib` (needed by `st.login`)
- `gspread` and `google-auth` (Google Sheets access through a service account)
- `pandas`
- Hosting: Streamlit Community Cloud, or any server or container that can run `streamlit run app.py`

## 3. Repository structure

```
mt-indent/
├── app.py                    # entry point: login gate, sidebar navigation
├── requirements.txt
├── .streamlit/
│   ├── config.toml           # theme (green accent), hide default menu
│   └── secrets.toml          # NOT committed: auth, service account, sheet id
├── pages_src/                # one module per screen (called from app.py)
│   ├── delivery.py           # step 2: delivery details
│   ├── items.py              # step 3: parent SKU, SKU name, variety, lot, qty, price
│   ├── my_indents.py         # list, open, correct, version history, PO freeze
│   ├── production.py         # production sheet
│   └── access.py             # owner only: manage who can sign in
├── core/
│   ├── auth.py               # st.login wrapper, role lookup from Access tab
│   ├── sheets.py             # gspread client, read/append helpers, caching
│   ├── masters.py            # SKU map, store map, varieties loaders
│   ├── lots.py               # lot auto-detection from the SKU name
│   ├── indents.py            # build, validate, submit, version, diff
│   ├── changelog.py          # compare two versions into Change_Log rows
│   ├── production_calc.py    # aggregation for the production sheet
│   └── models.py             # dataclasses: IndentHeader, IndentLine
└── tests/
    ├── test_lots.py
    ├── test_changelog.py
    └── test_production_calc.py
```

## 4. Google Sheet layout

One spreadsheet, shared as **Editor** with the service account's email. Sheet id goes in `secrets.toml`. Tab names are fixed; header row is row 1; the app must read by header name, not by column position.

### 4.1 Input tabs (maintained by the team; the app only reads)

**SKU_Map** (one row per customer SKU name per origin; replaces the working sheet shown in the screenshot)

| City | Customer | Parent SKU | Customer SKU Name | Spec-Origin | Spec-Size | Active |
|---|---|---|---|---|---|---|

- `Active` is `Y` for the origin currently being sourced (the yellow-highlighted rows in the working sheet) and blank or `N` otherwise. The production sheet uses the Active row of each SKU. Exactly one active row per (City, Customer, Customer SKU Name) is expected; the app must warn the owner if there are zero or more than one.

Seed rows from the screenshot (City = Bangalore, Customer = Zepto, Active shown as Y/N):

```
Avocado,1PC - Snacky Avocado Imported,Tanzania,"22C, 24C",Y
Avocado,1PC - Hass Avocado Imported,Tanzania,"20C, 22C",Y
Avocado,1PC - Large Avocado Imported,Tanzania,"16C, 18C, 14C",Y
Avocado,2PC - Mini Avocado Imported,Tanzania,"26C, 28C",Y
Avocado,(same four SKU names),Kenya,(same sizes),N
Avocado,(same four SKU names),Australia,(same sizes),N
Blueberry,1PC - Blueberry Imported,Peru,"14mm, 16mm",Y
Blueberry,1PC - Bloom Blueberry Imported,Peru,"18mm, 20mm",Y
Blueberry,(same two SKU names),Chile,(same sizes),N
Blueberry,(same two SKU names),Poland,(same sizes),N
Mandarin,3PC - Baby Orange Imported,China,"60, 65",N
Mandarin,2PC - Bloom Baby Orange,China,"55, 50",N
Mandarin,3PC - Baby Orange Imported,RSA,"2C, 3C",Y
Mandarin,2PC - Bloom Baby Orange,RSA,1C,Y
Mandarin,3PC - Baby Orange Imported,Australia,"2C, 3C",N
Mandarin,2PC - Bloom Baby Orange,Australia,1C,N
```

The screenshot is cut off at the bottom, so the sheet is the source of truth. Expand "(same ...)" rows into full rows when seeding. The same structure repeats for every city and customer.

**Store_Map**

| City | Customer | Store Name |
|---|---|---|

Once a customer is chosen, the store dropdown lists only the stores for that city and customer.

**Varieties** (only parents that need a variety; today that is Apple)

| Parent SKU | Variety |
|---|---|

**Access**

| Email | Role | Status |
|---|---|---|

`Role` is `owner` or `sales`. `Status` is `active` or `revoked`. Only `active` emails get in.

### 4.2 Output tabs (written by the app; append-only)

**Indent_Lines**: every submitted version, one row per SKU line.

| indent_id | version | status | submitted_at | submitted_by | delivery_date | city | customer | store | expected_time | parent_sku | customer_sku_name | variety | lot | qty | price | amount |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

- `status` is `Submitted` or `Frozen`.
- Never edit or delete rows. A correction appends a new version. The current version of an indent is the highest `version` for that `indent_id`.
- Timestamps are ISO 8601 in Asia/Kolkata (e.g. `2026-11-14T18:20:05+05:30`).

**Change_Log**: one row per changed field or line when version N+1 replaces version N.

| changed_at | indent_id | from_version | to_version | changed_by | change_type | customer_sku_name | field | old_value | new_value |
|---|---|---|---|---|---|---|---|---|---|

- `change_type` is `header_changed`, `line_added`, `line_removed` or `line_changed`.
- Example: qty of "1PC - Hass Avocado Imported" changed from 30 to 40 gives one row with `field=qty`, `old_value=30`, `new_value=40`.

**PO_Freeze**

| indent_id | version | po_file_name | po_customer | po_store | confirmed_by | confirmed_at |
|---|---|---|---|---|---|---|

**Drafts** (autosave; one current row per user and draft)

| draft_id | user_email | updated_at | payload_json |
|---|---|---|---|

## 5. Business rules

### 5.1 Sign-in and access
1. Page 1 is sign-in with Google or Microsoft (OIDC) through `st.login`.
2. After login, read `Access`. If the email is not found or `Status` is not `active`, show "Access is not granted for <email>. Ask the indent owner to add your email." and stop.
3. Owner sees the Access page (add, revoke, list). Access changes are written to the `Access` tab.

### 5.2 Page 2: delivery details
Fields, in this order: delivery date, city name, customer name, store name, expected delivery time.
- City list comes from `SKU_Map` and `Store_Map`.
- Customer list is the five MT Direct Sales customers (or the customers found in the maps for that city).
- Store name options: `Store_Map` filtered by city and customer.
- Changing city or customer clears the items already added and tells the user why (SKU names are mapped per city and customer).
- All five fields are required before Continue.

### 5.3 Page 3: items
For each line, in this order: parent SKU, customer SKU name, variety (Apple only), lot, qty, price.
- Parent SKUs offered: those in `SKU_Map` for the chosen city and customer.
- Customer SKU names offered: those under the chosen parent, for that city and customer.
- **One entry per customer SKU name per indent.** A name already added is not offered again.
- Variety: shown and required only when the parent has rows in `Varieties` (today: Apple).
- Lot options are exactly: `Kg`, `Pcs`, `Tray`, `Box`, `gms`.
- Qty must be greater than 0. Price (per lot) must be greater than 0. Amount = qty x price.
- Show spec (origin and size from the Active row) under each SKU name, and a running total.

### 5.4 Lot auto-selection from the SKU name
Implement in `core/lots.py` and unit-test it.
- Look for the first unit word in the customer SKU name, case-insensitive, matched on word boundaries (a digit may directly precede it, as in `1PC`):
  - `kg` or `kgs` gives `Kg`
  - `gm`, `gms`, `gram`, `grams` gives `gms`
  - `pc`, `pcs`, `piece`, `pieces` gives `Pcs`
  - `box` or `boxes` gives `Box`
  - `tray` or `trays` gives `Tray`
- If several appear, the one that appears first in the name wins.
- The lot is pre-selected but the user can change it.
- Names with no unit word: **open decision** (see section 11). Until decided, leave the lot unselected and require a choice.
- Note: every SKU name in the current sheet contains `1PC`, `2PC` or `3PC`, so they all resolve to `Pcs`.

### 5.5 Draft autosave
- Keep the working indent in `st.session_state`.
- Persist it to the `Drafts` tab: when a line is added or removed, when Continue or Back is pressed, and at most once every 15 seconds for quantity or price edits.
- Do this because Google Sheets enforces per-minute write quotas per user and per project (check the current limits in Google's documentation). Never write to the sheet on every keystroke.
- Show "Autosaved hh:mm:ss" and restore the draft on next login.

### 5.6 Submit, correct, version
- Submit writes version 1 of the indent to `Indent_Lines` (batch append, one call).
- Indent id format: `IND-YYYYMMDD-<CITY3>-<4 digit running number>`. Compute the running number from existing ids in the sheet.
- Editing a submitted indent loads its current version into the form. "Update indent" is enabled only when something changed.
- Update appends version N+1 to `Indent_Lines` and the differences to `Change_Log` (`core/changelog.py`). Store who changed it and the timestamp.
- The UI shows the last 10 versions of an indent with date, time and who; the sheet keeps all of them. "Load" on an old version copies it into the form; it is only saved when the user presses Update.
- A frozen indent cannot be edited.

### 5.7 Indent freeze with PO
- A PO can be uploaded only against a submitted indent with no unsaved changes.
- After upload, ask: "Is the selected PO for customer <X> and store <Y>?" with Confirm and Cancel.
- Confirm writes a row to `PO_Freeze`, appends a copy of the current version with `status=Frozen`, and makes the indent read-only.
- Storing the PO file itself (Drive folder) is optional; at minimum store the file name.

### 5.8 Production sheet
- Shows only indents that have been created and submitted. No hourly batching, no time-slot forms.
- Filters: delivery date and city.
- Which indents count: indents created by the signed-in user. Owner sees all. This is an **open decision** (section 11).
- Use the current (highest) version of each indent.
- Aggregate by: Parent SKU, then variety (if any), then spec (Active origin and size), then lot. Output total qty per group, and list the customer SKU names that feed each group.
- Provide a "Download CSV" button (`st.download_button`).

## 6. Screens and navigation

Sidebar: **Indent** (Delivery then Items), **My indents**, **Production sheet**, and **Access** (owner only). Show the signed-in email and a Sign out button.

1. Sign-in page (shown when `st.user.is_logged_in` is false).
2. Delivery page.
3. Items page, with a summary strip of the delivery details and an Edit button back to page 2.
4. My indents: table of indents with status, version, last edited; open one to correct it, see versions, upload a PO.
5. Production sheet.
6. Access (owner).

Visual style: clean, light, green accent (`#1c6b49`), dense tables, tabular numbers for quantities. Mobile friendly (`layout="wide"` on desktop, columns that stack).

## 7. Configuration

`.streamlit/secrets.toml` (never commit):

```toml
sheet_id = "<spreadsheet id from the URL>"
owner_email = "<owner email>"

[auth]
redirect_uri = "https://<your-app-host>/oauth2callback"
cookie_secret = "<long random string>"

[auth.google]
client_id = "<google oauth client id>"
client_secret = "<google oauth client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[gcp_service_account]
# paste the service account JSON fields here
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "..."
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

For Microsoft sign-in, use a `[auth.microsoft]` block with that provider's metadata URL and call `st.login("microsoft")`.

Setup steps:
1. Create a Google Cloud project, enable the Google Sheets API, create a service account and download its JSON key.
2. Share the spreadsheet with the service account's `client_email` as Editor.
3. Create an OAuth client (for sign-in) and add the app's `/oauth2callback` URL as an authorised redirect.

## 8. Data access and performance

- Read master tabs (`SKU_Map`, `Store_Map`, `Varieties`, `Access`) with `st.cache_data(ttl=300)` and give the owner a "Refresh data" button that clears the cache. Edits in the sheet therefore appear within five minutes or on refresh.
- Read the output tabs without long caching, because other users write to them.
- Write with `append_rows` in one call per submit. Do not read-modify-write cells.
- Retry with back-off on HTTP 429 or 5xx from the Sheets API, and show a clear message if saving fails. Never tell the user "submitted" unless the append succeeded.
- Compute the next version number and indent id right before writing, and re-check after writing that no other row has the same indent id and version (two people saving at once).

## 9. Testing checklist

- Lot detection: `1PC - Snacky Avocado Imported` gives Pcs; `5 Kg Tray Mix` gives Kg; `Mixed Box 2Kg` gives Box; a name with no unit gives none.
- Store dropdown shows only stores of the selected city and customer; changing customer clears items.
- A customer SKU name cannot be added twice.
- Variety appears for Apple only and is required there.
- Submit writes the expected rows; Update writes a new version and the right Change_Log rows (added, removed, qty changed, header changed).
- Only the last 10 versions show in the UI; all stay in the sheet.
- PO confirm freezes the indent and blocks edits.
- Production sheet: totals match the Indent_Lines current versions; no hourly tabs; filters work.
- A user not in `Access` is blocked; a revoked user is blocked; only the owner sees the Access page.
- Sheet unavailable or quota error shows an error and does not lose the draft.

## 10. Build order for Claude Code

1. Project skeleton, `requirements.txt`, config, secrets template, login gate with the Access check.
2. `core/sheets.py` and `core/masters.py`: load `SKU_Map`, `Store_Map`, `Varieties`, `Access` (with a local CSV fallback for development).
3. `core/lots.py` with tests.
4. Delivery page and Items page, with draft in session state.
5. Submit, versioning, `Indent_Lines` writes.
6. `core/changelog.py` with tests, then the Update flow and `Change_Log` writes.
7. My indents page with version history, then PO upload and freeze.
8. Production sheet and CSV download.
9. Access page, draft autosave to the `Drafts` tab, error handling and retries.
10. Deployment notes in a README.

## 11. Open decisions (confirm before building the related part)

1. **Lot when the SKU name has no unit word**: default to a parent-level lot, or require the user to choose? (Current spec: require a choice.)
2. **Active origin**: is the yellow highlight in the working sheet the right way to say which origin is being sourced, and who updates it?
3. **Production sheet scope**: should a sales person see only their own indents, or all indents for the city and date? (Current spec: sales see their own, owner sees all.)
4. **Apple**: the Apple customer SKU names, origin and sizes, and the list of varieties are not in the screenshot. They need to be added to `SKU_Map` and `Varieties`.
5. **Other cities and customers**: `SKU_Map` and `Store_Map` need rows for them; until then the app shows "mapping pending" for that city and customer.
6. **PO file storage**: save only the file name, or also upload the file to a Google Drive folder?
7. **Hosting and sign-in provider**: Streamlit Community Cloud or a company server; Google or Microsoft sign-in.

## 12. Kickoff prompt for Claude Code

> Read MT_INDENT_BUILD_SPEC.md in this repo. Build the MT Indent Streamlit app step by step, following section 10. Start with steps 1 to 3, add a local CSV fallback so I can run it without Google credentials, write the tests listed in section 9 for lot detection, then stop and show me how to run it. Ask me about any open decision in section 11 before you build the part that depends on it.
