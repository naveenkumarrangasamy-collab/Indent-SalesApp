# CLAUDE.md: MT Indent app (project context for Claude sessions)

Last updated: 16 Nov 2026. Owner of this work: MT Direct Sales team, Ninjacart (PTP Bangalore).

Read automatically by Claude Code. Keep it current when rules change.
The live user list and e-mail lists are NOT kept here (this repo is public); see the app's Access tab.

> **No secrets in this file, the repo or chat.** The service-account key, PINs, `pin_pepper`
> and the SMTP App password live **only** in Streamlit Cloud → app → Settings → Secrets.
> Never paste them into chat, commit them, or type them into forms for the user.

---

## 1. What the app is

The **MT Indent** app is a Streamlit web app for the Modern Trade (MT) Direct Sales team:

- Sales staff place **indents** (orders) for each customer store and delivery date.
- The team uploads the customer's **PO** against each indent.
- The warehouse uses the **Production** and **Batching** sheets to produce and dispatch.
- E-mails go out hourly (production report) and on every PO (SO/PO mail).

Customers: Zepto, Swiggy, Zomato, Firstclub, Namdhari, Flipkart, More, and others.

Main city: **PTP Bangalore**.

Products include Apple (with varieties), Avocado, Blueberry, Kiwi, Mandarin/Orange, Grapes,
Longan/Litchi and Grapefruit.

## 2. Systems and connections

| Piece | Where | Notes |
|---|---|---|
| **Code (GitHub)** | `naveenkumarrangasamy-collab/Indent-SalesApp`, branch `main` | Commit/push only to `main` of this repo. |
| **Hosting** | Streamlit Community Cloud: https://indent-salesapp.streamlit.app | Redeploys automatically on push to `main`, in about 1 minute. The direct app path (no iframe) is `https://indent-salesapp.streamlit.app/~/+/<page>`. |
| **Database** | Google Sheet `1cxOtb4Q4CQsgkYzdnCgetsQsibKFlpmzsKeV6yUoTuA` | Reached through a Google service account using `gspread`. The service account's `client_email` must have **Editor** on the sheet. |
| **E-mail sending** | Gmail SMTP, the team sender account with a Google **App password** | Port 587 STARTTLS, falling back to 465 SSL. The values `smtp_user`/`smtp_password` are kept in Streamlit Secrets. An unused older App password named "MT Indent" should be revoked; the one in use is "MT Indent mail". |
| **Hourly schedule** | GitHub Actions `.github/workflows/hourly-indent-mail.yml`, cron `30 2-8 * * *` UTC (8:00 AM–2:00 PM IST) | **Needs no GitHub secrets.** It runs `scripts/wake_and_send.py`, which uses Playwright to open `https://indent-salesapp.streamlit.app/?hourly=run` and wakes the sleeping app if needed. The app then sends that hour's e-mail with its own secrets. It is never forced, never sends outside 8–2, and sends once per hour (deduplicated via `Mail_Log`). Tested OK on 16 Nov 00:45: the app answered "outside the 8 AM-2 PM window". |
| **PO PDFs in Drive** | Optional `po_drive_folder_id` (a Shared-drive folder) | When it is not set, only the file name is recorded. |

### Streamlit secrets: key names only (the values stay in Streamlit)

Keys:

- `sheet_id`, `owner_email`, `owner_initial_pin`, `pin_pepper`, `master_refresh_minutes`
- `gcp_service_account_json` (the full JSON key, between triple quotes)
- `smtp_user`, `smtp_password`, `po_mail_to`

Optional keys:

- `edit_cutoff_days` (default 0), `edit_cutoff_hour` (14)
- `session_hours` (24), `delivery_days_ahead` (1)
- `delivery_from`/`delivery_to` (10:00/20:00)
- `hourly_mail_days` ([0]), `hourly_mail_from` (8), `hourly_mail_to` (14)
- `show_spec`, `variety_parents` (["Apple"]), `po_drive_folder_id`

The template is in `.streamlit/secrets.toml.example`. Never commit `.streamlit/secrets.toml`.

Simple `name = value` lines must come **before** any `[section]`. Duplicate keys break the TOML: this happened once with old smtp lines and was fixed.

### Tooling notes for Claude

- The GitHub API for Actions and secrets is blocked from the Claude cloud proxy, so use Chrome (Claude in Chrome) for anything in the GitHub web UI.
- File uploads into Chrome from the user's computer need the user to pick the file. Use the **paste box** on the Import indents tab instead.
- In Chrome, the app runs in a same-origin iframe. Open `/~/+/<page>` to work on it directly.
- Glide data-editor cells: click, Enter, type, Enter.

## 3. People, roles and e-mail lists (live, 16 Nov 2026)

Sign-in is **e-mail + PIN** (4–6 digits, hashed with `pin_pepper`). A sign-in lasts 24 h. It is kept in localStorage plus a one-time `?s=` token, so a refresh keeps the user signed in.

| Role (sheet value → shown as) | Can do |
|---|---|
| `sales` → sales | Create/edit indents and upload POs, limited to their **cities** (empty = only their own indents). **No** production, batching or tracker pages. |
| `warehouse` → warehouse | Production sheet, Batching sheet and Hourly tracker only (for their cities; empty = all). Cannot make indents. |
| `owner` → **Owner L** (limited owner) | Everything **except** Import indents and Start fresh. Cannot grant the Owner role. |
| `owner_full` → **Owner** (full owner) | Everything. Only an Owner can grant or change the Owner role. Any owner could do this only until the first Owner existed. |

- Owners always see all cities.
- A user mapped to one city has no City filter on production.
- The `owner_email` in secrets can always sign in.

## 4. Google Sheet: tabs and columns (the "database")

The app reads columns **by header name**, ignoring case, spaces, `-` and `_`. Column order does not matter.

### Input/master tabs (maintained by the team; the app reads them every 5 minutes, cached)

- **All Cux City**: the master list of customer SKU names. Columns: City, Customer, Parent SKU, Classification, Customer SKU Name.
  - Classification = the variety for Apple; when it equals the parent, there is no fixed variety.
  - Optional columns: `Lot`/`UOM`; `<Parent> Variety` (e.g. "Apple Variety") listing the varieties.
  - The live sheet now holds every SKU used in the 16 Nov indents (131 SKU names).
- **Mapping Whole**: the spec per origin. Columns: City, Customer, Parent SKU, Customer SKU Name, Spec-Origin, Spec-Size.
  - Optional columns: Active (Y), Grade (Spec-Grade), Box Kgs (Box-Kg), Lot/UOM.
  - Default active origins: Avocado Tanzania, Blueberry Peru, Mandarin RSA.
- **Customer List**: the stores. Columns: `Customer List` (customer), `Store names`, optional `City` (no city = every city).
  - Stores include Zepto - Yalachanayakanapura, Swiggy WH1, Swiggy WH2, Flipkart, FIRST CLUB PTP BLR, More_BLR EKRAJPURA, and Namdhari (store not given). The last was added 16 Nov; rename it when the real store is known.
- **Apple Varity / Apple Variety** tab (optional): the list of Apple varieties. The default list is used when there is none.
- **Box_Conversion** (optional): columns Parent SKU, Spec, Box, Pcs per box, Kg per box. It can be created from the Production page.
- **SKU_Map / Store_Map / Varieties**: legacy fallbacks, used only when All Cux City / Customer List are absent.
- **Access**: columns Email, Name, Role, Status (active/revoked), PIN_Hash, Updated_At, Updated_By, City (comma list), Stores (unused). It is edited only from the app.

### Output tabs (written by the app, append-only)

- **Indent_Lines**: one row per item per version. Columns:
  - indent_id, version, status (Submitted / Frozen / Cancelled), submitted_at, submitted_by
  - delivery_date, city, customer, store, expected_time
  - parent_sku, customer_sku_name, variety, lot, lot_size, qty, price, amount
  - change_note
- **Change_Log**: changed_at, indent_id, from_version, to_version, changed_by, change_type (header_changed / line_added / line_removed / qty…), customer_sku_name, field, old_value, new_value.
- **PO_Freeze**: indent_id, version, po_file_name, po_customer, po_store, confirmed_by, confirmed_at, po_file_link, po_number, po_total_qty, po_lines.
- **Drafts**: draft_id, user_email, updated_at, payload_json. Autosaved drafts; the "draft restored" message was removed.
- **Mail_Recipients**: Email, Name, Team (Ground/Central), Hourly_Indent, SO_PO, Cities, Customers, Stores, Active, Updated_At, Updated_By. Customers and Stores are ignored now.
- **Mail_Log**: sent_at, kind (hourly / so / sample / test), slot, to, status, detail.
- **Production_Sheet / Batching_Sheet**: snapshots published by the owner from the Production/Batching pages.
- **Backup_YYYYmmdd_HHMM_<tab>**: made by Start fresh. The 15 Nov ~22:38 reset backed up Indent_Lines (36 rows), Change_Log (21), PO_Freeze (3) and Drafts (4).

## 5. Business rules (all agreed with the user)

### Indents

- Indent numbers are unique and running: **IN-001, IN-002…**. Only `IN-` ids are counted, and they restart after Start fresh.
- Delivery date is **today or tomorrow** (`delivery_days_ahead` = 1). New indents and edits are allowed until **2:00 PM IST on the delivery day** (the cutoff).
- There is one indent per city + customer + store + delivery date. A duplicate is refused and the user is pointed to the existing indent.
- An expected delivery time is required: a 30-minute slot from 10 AM to 8 PM, or typed in.
- **Lot** is detected from the SKU name: Kg; gm/g/pack → Pack; pc/pcs → Pcs; box → Box; tray → Tray. A Lot/UOM column in the master overrides it.
- Qty must be a whole number. The price must be above 0.
- **Apple needs a variety.** It is taken from the name (Royal Gala → Gala, Granny → Granny Smith, Red Delicious → RD) or picked by the user.
- **Editing a saved indent:**
  - City, customer, store and delivery date are locked.
  - Saved items cannot be removed, only set to **qty 0**; only qty and price are editable.
  - New items can be added.
  - Every save is a new version, recorded with a Change_Log entry.
- **Deleting:** nobody deletes items or indents, **except an owner**, who can delete (cancel) an indent until **T-2**, even after the cutoff. Deleted indents are kept as Cancelled.
- The "Edit qty / price" action is on All indents.

### PO upload

- Upload PO is on Home, on All indents and as its own page. It has cards, filters (Show / Delivery date / City / Search / Customer) and 3 tiles.
- PO number is optional. The user enters the PO qty per item.
- **PO qty must match the indent for every item.** A mismatch **blocks** the upload. The fix flow, "Edit indent to match PO", is allowed even after the cutoff (`po_fix`).
- Once it matches, the indent is **Frozen** (no more edits) and the **SO/PO e-mail** goes out immediately to the PO list, with a PDF + Excel.

### Production, batching and tracker (owner + warehouse only)

- **Production sheet:** all customers together, one row per City + Parent SKU + Variety + Lot + Lot Size + Spec, with Total Qty. There are **no customer names and no Customer SKU Name** (removed on 16 Nov at the user's request).
  - **Box conversion** adds Units / Box / Boxes. Count specs (22C = 22 pcs per box); avocado up to 36C uses a 4 kg box, otherwise 10 kg (65C = 65 pcs in 10 kg). Box Kgs come from Mapping Whole or Box_Conversion; "not mapped" means unknown.
  - Unmapped specs show as "spec not mapped (name)" and are never merged.
  - The page also has a spec mapping list download.
- **Batching sheet:** **one table** with columns City, Customer, Delivery point, Parent SKU, **Customer SKU Name**, Variety, Lot, Lot Size, Spec, Qty, Indent. Downloads: PDF/Excel/CSV.
- **Hourly tracker:** 8 AM–2 PM columns per customer/store row. Changed cells are amber (▲/▼) and unchanged cells green. It has a Status column and a detail dialog when a cell is clicked. Owner and warehouse only.
- The City/SKU report was removed.

### Home page

- Fits one screen on laptop and phone.
- One row holds: the title + scope, a Today/Tomorrow switch, Create indent, and Upload PO · n.
- City pills appear when there is more than one city.
- 3 tiles plus a green/yellow bar.
- One compact line per customer: green "PO uploaded" or yellow "Waiting for PO · n".
- No Amount/Edits tiles and no yesterday.

### E-mails (formats must stay consistent)

- **Hourly** (8 AM–2 PM, the production report only): PDF + Excel per recipient, scoped by their cities. There is no customer-level section and no batching report.
- **SO/PO**: sent on every PO upload to the PO list, with the PO lines as PDF + Excel.

### Owner tools

- **Bulk download** (owners only) on All indents and Upload PO: tick "Select all" or pick indents. It downloads one Excel with two sheets: **Indents** (one row each, including the PO number) and **Lines** (every item).
- **Import indents** (Access tab; **Owner only**, not Owner L):
  - Input is an Excel upload or rows pasted as text (tab, `|` or comma separated, header first).
  - Columns: Delivery date, City, Customer, Store, Parent SKU, Item / Customer SKU Name, Qty, and optional Price/Rate.
  - Options: one city for all rows, one price for all rows (default **1**) or the file's price, and the expected time.
  - Each customer + store + date becomes one indent.
  - If the store isn't found and the customer has **one** store in the master, that store is used.
  - Missing SKUs/stores can be added to All Cux City / Customer List first. Creating indents is blocked until they are added.
- **Start fresh** (Owner only): type CLEAR. It backs up the indent tabs to Backup_ tabs and then empties them.

## 6. Code map (repo root)

- `app.py`: entry point.
  - **Stale-module purge**: Streamlit Cloud keeps old modules after a redeploy, so on start the app drops core/pages_src modules if any file changed. It iterates over `list(sys.modules)`, which fixes the "dictionary changed size" crash of 16 Nov.
  - Handles the `?hourly=run` trigger.
  - Sign-in gate pages for every path.
  - Navigation by role.
- `core/`:
  - `schema.py`: tabs, columns and roles; `role_name()` gives the names shown on screen.
  - `auth.py`: User, PINs, sessions, `resolve_user`.
  - `config.py`: secrets/settings.
  - `sheets.py`: GoogleBackend (gspread) and LocalBackend (CSV in `data/`, seeded from `data/seed`).
  - `masters.py`: master lookups, cached.
  - `importer.py`: builds the SKU/store maps from All Cux City, Mapping Whole and Customer List.
  - `indents.py`: submit/update/freeze/cancel, versions, the IN-### numbering, `backup_and_clear`.
  - `models.py`, `lots.py`, `boxes.py`.
  - `production_calc.py`: production, batching, unmapped and the spec list.
  - `reports.py`: e-mail/report frames, xlsx, PDFs via `pdf_report.py`.
  - `hourly.py`, `mailer.py`, `recipients.py`.
  - `bulk_import.py`: the Excel/paste import.
  - `changelog.py`, `drafts.py`.
- `pages_src/`:
  - `home`, `indent` (with `delivery`, `items`, `state`, `indent_actions`), `my_indents` (All indents), `po_upload`
  - `production` (production + batching), `tracker`
  - `access` (with `mail_admin`, `import_indents`), `bulk_download`
  - `login`, `common` (CSS, sidebar, session).
- `scripts/wake_and_send.py`: the hourly trigger. `scripts/hourly_mail.py` is the manual run for a machine that has secrets.
- `tests/`: pytest, **137 tests passing**. Run `python -m pytest -q` and `python -m pyflakes core pages_src app.py`.
- `MT_INDENT_BUILD_SPEC.md` is the original build spec. `README.md` is the setup guide.
- Requirements: streamlit>=1.67, gspread, google-auth, pandas, tzdata, fpdf2, openpyxl.

**Commit message trailer used in this project:**

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
```

- **Files produced earlier** (outside the repo):
  - `Indents_16-Nov-2026_customer_x_store.xlsx`, with sheets: All indents, Customer x Store, Notes.
  - `Missing_SKUs_vs_master.xlsx`: 28 missing, 24 rows to add, 10 matched. This is now resolved, because the live master has all of them.
  - A dummy PO PDF, `TEST_PO_IND-20261114-PTP-0001.pdf`, used for testing.

## 8. Open items and next steps

1. Add the **Indent e-mails** recipients (Access → E-mails). The user will do this later. Until then the hourly run reports "no active recipients".
2. Namdhari: confirm the real store name (rename it in the Customer List) and confirm whether rates are per tray/box or total.
3. More: decide whether the Hubli and Mangalore supply need their own stores (and separate indents).
4. Master data clean-up: the duplicate "2PC - Snacky Kiwi", and whether Orange Imported sits under the Orange or Mandarin parent.
5. Revoke the unused Gmail App password "MT Indent".
6. Upgrade the GitHub Actions versions later; GitHub warns about the Node 20 deprecation, but it is harmless for now.

## 9. Working style the user expects

- Short, plain-language replies. Do the work end to end (including in Chrome when asked). Ask only when the choice really matters.
- On-screen labels stay short, with no explanations inside dropdowns (e.g. roles show as "Owner", "Owner L").
- Keep the e-mail formats stable once agreed.
- Test before pushing: run pytest and pyflakes; check the live app after the redeploy.

