# CLAUDE.md: MT Indent app (project context for Claude sessions)

Last updated: 17 Nov 2026. Owner of this work: MT Direct Sales team, Ninjacart (PTP Bangalore).

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
| **Mail schedule** | cron-job.org (exact, every hour 7:54-13:54 IST → workflow_dispatch) + GitHub Actions `.github/workflows/hourly-indent-mail.yml`, cron `30 2-8 * * *` UTC as backup | **Needs no GitHub secrets.** It runs `scripts/wake_and_send.py`, which uses Playwright to open `https://indent-salesapp.streamlit.app/?hourly=run` and wakes the sleeping app if needed. The app then sends that hour's e-mail with its own secrets. The app sends the production e-mail only at the send hours (default 8 AM), once (deduplicated via `Mail_Log`); other runs do nothing. Tested OK on 16 Nov 00:45: the app answered "outside the 8 AM-2 PM window". |
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
- **SKU_Map / Store_Map / Varieties**: legacy fallbacks, used only when All Cux City / Customer List are absent.
- **Access**: columns Email, Name, Role, Status (active/revoked), PIN_Hash, Updated_At, Updated_By, City (comma list), Stores (unused). It is edited only from the app.

### Output tabs (written by the app, append-only)

- **Indent_Lines**: one row per item per version. Columns:
  - indent_id, version, status (Submitted / Locked / Frozen / Cancelled), submitted_at, submitted_by
  - delivery_date, city, customer, store, expected_time
  - parent_sku, customer_sku_name, variety, lot, lot_size, qty, price, amount
  - change_note
- **Change_Log**: changed_at, indent_id, from_version, to_version, changed_by, change_type (header_changed / line_added / line_removed / qty…), customer_sku_name, field, old_value, new_value.
- **PO_Freeze**: indent_id, version, po_file_name, po_customer, po_store, confirmed_by, confirmed_at, po_file_link, po_number, po_total_qty, po_lines, kind (po / end = End of POs), po_qty_json (this PO's qty per SKU).
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
- **A PO that differs from the indent is still uploaded (17 Nov)** and the difference is **flagged**: qty
  differences, indent items not on the PO (blank = not on it), PO-only items (entered in the dialog). Shown on the
  indent's PO tab, in the SO/PO mail (PO qty + Diff columns) and in the tracker's **Indent vs PO** view.
- Most customers: one PO → indent **Frozen** and the **SO/PO e-mail** goes out at once (PDF + Excel).
- **Multi-PO customers** (secret `multi_po_customers`, default ["Swiggy"] = WH1/WH2): any number of POs, each
  e-mailed; the indent stays open until **End of POs** is pressed, which freezes it and shows the differences
  (all POs summed).
- **PO reader (17 Nov)**: `core/po_reader.py` (pdfplumber) reads the item table of a text PDF exactly (qty, code,
  unit cost, value), fills the PO number, checks qty × cost = value and lines = PO total, and matches lines to our
  SKUs: 1) **PO_Item_Map** tab (Customer, PO Item Code, PO Item Name, Customer SKU Name; filled automatically when a
  user picks/confirms a SKU), 2) same words + same pack ("2PC - X" = "X - 2 pcs (…)"), 3) close name ("? check").
  **PO lines are matched to the indent's own items first** (same words; pack may be written differently, e.g.
  "Kiwi Sungold - 2 pcs" = "1Pack - Kiwi Sungold"), then to the master (the live master has look-alike names
  that made matches ambiguous on 17 Nov: IN-001's PO was read right but 7 items didn't match). The check is
  only: same Customer SKU Name (spaces/case ignored) → same qty? An item not on the PO shows a **blank** PO qty
  ("Not on PO"), never 0. **Owner: Replace PO** on a frozen indent (one-PO customers): only the latest PO counts;
  e-mail again is optional (off). The user reviews "Our SKU" per line, then uploads. Scans/photos give no lines → type quantities by hand.
  Swiggy: PO number M… = WH1, B… = WH2 (secret `po_store_prefixes`); a mismatch with the indent's store is shown.
  Tested on the 4 sample POs: Zepto 22/22 lines read, totals ✓, 20 matched by name.
- **Lock** (manual freeze, "processing started"): status **Locked**: no edits, still waiting for its PO; a later
  PO upload still freezes it and sends the SO/PO mail.
- **Zepto cutoff 1 AM on the delivery day** (secret `customer_cutoff_hours`, default {Zepto = 1}); others 2 PM.

### Production, batching and tracker (owner + warehouse only)

- **Production sheet** (16 Nov, third version): its base is the **New** tab of the Google Sheet, filled by hand,
  one row per SKU name: City, Customer, Parent SKU, Customer SKU Name, variety, Spec-Repacking, Spec-Size,
  Spec-Origin (matched to indent lines by City + Customer + Customer SKU Name, ignoring case/spaces; a row with
  no City matches every city). All customers together. Columns:
  City, Parent SKU, Variety, Repacking, Spec-Size, Lot Size, Qty, **Total**, then **Boxes @ count 1..n**.
  Spec-Origin is **not** shown and not used to split rows.
  - One row per City + Parent SKU + Variety + Repacking + Spec-Size + Lot Size; Qty is the sum.
  - **Variety only for Apple** (`variety_parents`); every other parent shows no variety.
  - **Total** clubs every customer for the same City + Parent SKU + Repacking + Spec-Size + Lot Size:
    Kg packs ("1 Kg", plain Kg lot) → total **kilos** ("700 Kg"), never repacking units (box kg not known yet;
    the team converts by hand). Others → repacking units, no conversion: 10 + 20 two-piece packs = "30 Punnet".
  - **Boxes @ count N**: one column per count in Spec-Size (22C, 24C → 2 columns; Snacky apple has 4). Only for
    piece lots (1 Pcs, 2 Pcs): boxes = club pieces ÷ count, rounded up, shown as "22C: 20". Blank for kg, gm,
    pack or box lots and for sizes that are not counts (16mm, Blue, RSA 2,3: counts must be ≥ 10).
  - Lot Size comes from the SKU name (e.g. "2 Pcs", "1 Kg"), else the lot.
  - A SKU name missing from New shows Spec-Size "not in New tab (name)", is never clubbed, and is listed in a
    warning on the page.
  - Tiles: only Indents, Delivery points, Customers (no per-unit tiles).
  - **No** customer names, Customer SKU Name or customer-specific logic.
  - The page has **two views** (tabs): **By spec size** (the table above) and **Make-ready list**.
- **Make-ready list** (production page, 2nd view; for the ground team): all customers **and all sizes** together,
  one row per City + Parent SKU + Variety (Apple only) + Repacking + Pack. Columns:
  (City only when several cities) Parent SKU, Variety, Repacking, Pack, Make ready, Fruit needed.
  - Pack = lot size from the SKU name (1 Pcs, 2 Pcs, 200 gm, 1 Kg, 1 Box).
  - Unit packs (Punnet, Pack): Make ready = number of packs ("50 Punnet"); Fruit needed = pieces for piece
    packs (10 × 2 Pcs = "20 pcs"), kilos for kg packs, **blank for gram packs** (the packet count is the answer).
  - **Loose**: Repacking Tray/Box/Crate with a piece or kg pack → the fruit goes in loose: "7 pcs loose"
    (More's 7 avocados into trays, NOT 7 trays), "700 kg loose".
  - **Spec Size** (17 Nov, ONE last column, user's format): pieces at each count of the New-tab spec, joined by
    " | ": "20C : 100PC | 22C : 100PC"; kg packs "18C : 70KG"; else the spec text. No other extra columns.
    Counts always shown with C (also Spec-Size on the production sheet). Also in the production e-mail.
  - The pack itself a container ("1 Box", Namdhari green apple) → "10 Box", Fruit needed blank. **Known gap**
    (user asked to be reminded): box packs have no kg/pieces yet; fix later.
  - Mapping Whole / spec labels are only a fallback for the Batching sheet when there is no New tab. A permanent
    master for production is to be fixed later (user: "take it from New for now").
- **Zepto D+1** (17 Nov): below the production tabs, a separate table for `next_day_customers` (default
  ["Zepto"]): their indents for the **next** delivery day (selected date + 1), processed today; two tabs
  Make-ready list / By spec size, with CSV/PDF. Not part of the main tables or the e-mail.
- **Batching sheet:** **one table** with columns City, Customer, Delivery point, Parent SKU, **Customer SKU Name**, Variety, Lot, Lot Size, Spec, Qty, Indent. Downloads: PDF/Excel/CSV.
  - **Temporary (16 Nov)**: when the New tab exists, Spec = New tab Spec-Size, Variety = Apple only (New tab first),
    Lot Size as on production, so batching matches the production sheet; missing SKUs show "not in New tab (name)"
    and are listed in a warning. Without a New tab it falls back to Mapping Whole. The user will decide the
    permanent master (where production and batching pull from) later.
- **Hourly tracker:** two tabs. **Indent changes**: 8 AM–2 PM columns per customer/store row; changed cells are amber, shown as previous → new (▲/▼), unchanged cells green. **Indent vs PO**: per store and item, indent qty, PO qty (all POs), difference, status (Match / Differs / Not on PO / Not on indent / No PO yet / more coming); differences in red. It has a Status column and a detail dialog when a cell is clicked. Owner and warehouse only.
- The City/SKU report was removed.

### Home page

- Fits one screen on laptop and phone.
- One row holds: the title + scope, a Today/Tomorrow switch, Create indent, and Upload PO · n.
- City pills appear when there is more than one city.
- 3 tiles plus a green/yellow bar.
- One compact line per customer: green "PO uploaded" or yellow "Waiting for PO · n".
- No Amount/Edits tiles and no yesterday.

### E-mails (formats must stay consistent)

- **Production e-mail** (list "Production e-mails", Team = Ground; was called "Indent e-mails"): **every hour
  8 AM-2 PM IST, exactly on the hour** (secret `production_mail_hours`, default = hourly_mail_from..to = 8..14;
  16 Nov: briefly 8 & 9 only, so 10 AM was missed; user wants every hour, no gaps). Exact timing: **cron-job.org**
  starts the GitHub workflow (workflow_dispatch, via a token kept only in cron-job.org) every hour 7:54-13:54 IST
  (cron-job.org account kathiramirthees@gmail.com, job "MT Indent production mail (hourly 8 AM-2 PM IST)", crontab
  `24 2-8 * * *` UTC, POST .../actions/workflows/hourly-indent-mail.yml/dispatches body {"ref":"main"}, classic
  token "MT Indent exact mail trigger (cron-job.org)" of GitHub user Kathiramirtheeswaraa, repo scope, no expiry;
  test run 16 Nov 08:39 → 204 OK); the
  job wakes the app, waits until hh:00:00 and opens `?hourly=run`. Backup: GitHub's hourly schedule (often 10-60
  min late; on 16 Nov it never fired at all, so cron-job.org is the real trigger). The app accepts a run from 5 min before a send hour to 3 h after (later slot wins) and sends each slot
  once via Mail_Log. 16 Nov: GitHub's scheduled 8 AM run never came; the mail was sent by a manual run at 8:11. Content: **both tables**: 1) Make-ready list, 2) By spec size, in the body and as PDF
  (two sections) + Excel (two sheets), per recipient, scoped by their cities. No customer-level section, no
  batching. Recipients are added by the user in Access → E-mails.
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
- **Zepto Excel upload** (17 Nov; page "Zepto Excel upload" in the Indents menu, sales + owners; Zepto in the
  Bangalore city only): Zepto's indent Excel (Product Name, UOM, EAN, Pack Date, one qty column per warehouse
  "… Final", Summation). Each warehouse column with qty → one indent; store picked per column (guess: HSK →
  Yalachanayakanapura, NLM → Nelamangala). Delivery date = Pack Date when open for Zepto, else the next open day;
  price for every line (default 1); expected time. Products matched like PO lines (PO_Item_Map by EAN/name, name +
  pack, close); **creating is blocked until every product is mapped or skipped** (if a SKU is missing, add it to
  All Cux City and press Refresh master). Picks are saved to PO_Item_Map. Duplicates point to the existing indent.
  `core/zepto_import.py`, `pages_src/zepto_upload.py`. Tested on the 17 Nov file: 22 products, 3,397 qty.
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
  - `models.py`, `lots.py`, `boxes.py` (only `per_lot`: what one lot is in pcs / kg).
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
- `tests/`: pytest, **149 tests passing**. Run `python -m pytest -q` and `python -m pyflakes core pages_src app.py`.
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

0. PO reader built; needs a More PO sample to confirm its layout.
1. Add the **Production e-mails** recipients (Access → E-mails). The user will do this later. Until then the 8 AM run reports "no active recipients".
7. **Remind the user**: box packs ("1 Box", e.g. Namdhari green apple) show only "N Box" on the make-ready list;
   box kg / pieces per box are not known yet. Also box counts for kg and gram packs need box weights.
2. Namdhari: confirm the real store name (rename it in the Customer List) and confirm whether rates are per tray/box or total.
3. More: decide whether the Hubli and Mangalore supply need their own stores (and separate indents).
4. Master data clean-up: the duplicate "2PC - Snacky Kiwi", and whether Orange Imported sits under the Orange or Mandarin parent.
5. Revoke the unused Gmail App password "MT Indent".
6. Upgrade the GitHub Actions versions later; GitHub warns about the Node 20 deprecation, but it is harmless for now.

## 7. Speed rules (16 Nov night: "make it light and fast")

- Item form (Create indent), Home, All indents and Upload PO bodies are `st.fragment`s: their toggles and filters
  rerun only that part. Adding an item reruns the whole app once (to refresh the table).
- Downloads (PDF / Excel / CSV) are built only when clicked (`data=lambda: ...`, `on_click="ignore"`).
- Draft autosave writes to the Drafts tab at most once a minute (`state.THROTTLE_SECONDS = 60`); adding or
  removing an item does not force a write. An edit draft whose edit time has closed (and is not a PO fix) is
  cleared instead of reopening (`state.drop_closed_edit`), so Create indent never gets stuck on it.
- Indent_Lines is cached 60 s, already prepared (`indents._cached_lines`); every save clears the cache at once.
- Dialog buttons set `pending_*` and the dialog opens in the same run (no extra `st.rerun()`).
- Removed dead code: Box_Conversion / box conversion, spec mapping list, Mapping Whole "Repacking" column,
  the old hourly indent mail (overall / customer level), send_po_mail, unused helpers.

## 9. Working style the user expects

- Keep replies short: what changed and what the user must do. The user finds long, back-and-forth messages heavy.

- Short, plain-language replies. Do the work end to end (including in Chrome when asked). Ask only when the choice really matters.
- On-screen labels stay short, with no explanations inside dropdowns (e.g. roles show as "Owner", "Owner L").
- Keep the e-mail formats stable once agreed.
- Test before pushing: run pytest and pyflakes; check the live app after the redeploy.

