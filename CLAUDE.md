# CLAUDE.md: MT Indent app (project context for Claude sessions)

Last updated: 19 Nov 2026. Owner of this work: MT Direct Sales team, Ninjacart (PTP Bangalore).

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

- `edit_cutoff_days` (default 0), `edit_cutoff_hour` (23; was 14 until 18 Nov)
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
- Delivery date is **today or tomorrow** (`delivery_days_ahead` = 1). New indents and edits are allowed until **11:00 PM IST on the delivery day** (the cutoff; was 2 PM until 18 Nov, user moved it to 11 PM).
- There is one indent per city + customer + store + delivery date. A duplicate is refused and the user is pointed to the existing indent.
- An expected delivery time is required: a 30-minute slot from 10 AM to 8 PM, or typed in.
- **Lot** is detected from the SKU name: Kg; gm/g/pack → Pack; pc/pcs → Pcs; box → Box; tray → Tray. A Lot/UOM column in the master overrides it.
- Qty must be a whole number. The price must be above 0.
- **Apple needs a variety.** It is taken from the name (Royal Gala → Gala, Granny → Granny Smith, Red Delicious → RD) or picked by the user.
- **Attach the order (18 Nov)** — pictures switched OFF for now (secret `read_pictures`, default false; Excel
  and PDF only) — on Create / edit indent (above the unchanged Add item form; `pages_src/attach.py`,
  `core/order_reader.py`): a **picture** (free OCR: Tesseract, `packages.txt` tesseract-ocr; weak on angled phone
  photos — 18 Nov test: ~7 of 22 lines; better on screenshots), an **Excel** (Zepto format → the column of the
  chosen store, or any sheet with item + qty columns) or a **PDF** (po_reader). Lines are matched (po_reader.match,
  incl. a fuzzy letters-only fallback for OCR text) and put in the item list: 🟡 check (best guess / low OCR
  confidence), 🆕 new item (Parent SKU exists, e.g. Apple Fuji, Garlic once in the master), **red** = not readable
  or a **new Parent SKU (e.g. Mango) → never added automatically, needs real attention**: pick the SKU + qty or
  remove; Submit waits for red lines. File total vs read total is checked. Nothing is saved before Submit.
  **Exact names only (18 Nov, user):** a file line maps to our SKU only when its name in our style
  ("Kiwi Sungold - 2 PIECE" → "2PC - Kiwi Sungold") is exactly in the master (case/spaces ignored); no fuzzy
  matching on attach. Anything else → 🆕 new SKU (added on Submit) or red (new parent). A **"File vs item list"**
  table shows every file line, our SKU name and the change (✓ exact / 🆕 new, blue / 🔴 needs you). On edit,
  saved items not in the file are listed (set them to 0 if the file replaces them).
- **New items → master (anyone, on Submit/Update)**: `core/master_add.py` appends them to All Cux City and the New
  tab; in the New tab Spec-Repacking / Spec-Size / Spec-Origin (+ variety when Apple has none) are coloured
  **yellow** (highlight only; no Status text, user 18 Nov). Production shows such SKUs as
  **"mapping not done (name)"** (qty kept, own line, listed in the warning) until Spec-Size or Spec-Repacking is
  filled. Variety for an indent line also comes from the New tab's variety column now.
- **Item list (18 Nov)**: one table (data_editor): Parent SKU, Customer SKU name, Variety (choose for Apple when not
  fixed; also a picker under the table), Lot, Lot size, Qty, Price, 🗑 (Line total + order value hidden while every
  price is 1; secret `show_amounts` to show them later); saved items cannot be removed (qty 0).
- **Editing a saved indent:**
  - City, customer, store and delivery date are locked.
  - Saved items cannot be removed, only set to **qty 0**; only qty and price are editable.
  - New items can be added.
  - Every save is a new version, recorded with a Change_Log entry.
- **Deleting:** nobody deletes items or indents, **except an owner**, who can delete (cancel) an indent until **T-2**, even after the cutoff. Deleted indents are kept as Cancelled.
- The "Edit qty / price" action is on All indents.
- **All indents cards (19 Nov)**: the table is replaced by one card per indent (max 40) listing every line item
  (qty > 0) with **Edit** and **Delete** per line (Delete = qty 0, history kept; anyone who can edit the indent,
  before the cutoff and before a PO/lock), **Add item** (dialog: Parent SKU → this customer's SKUs not on the
  indent, variety for Apple, qty, price), Upload PO and **Open** (full detail: versions, change log, PO, lock,
  change date, delete indent). The customer pill shows only that customer's cards.
- **All indents filters (18 Nov)**: buttons on top like Create indent: Delivery date (Yesterday / Today (default) /
  Tomorrow / All dates), City (only when >1 city), Customer (with counts); then Search + Status.

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
- **Zepto cutoff = 11 PM like everyone** (18 Nov; was 1 AM). Per-customer override still possible via secret `customer_cutoff_hours` (default {} now).

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
  - **Spec Size** (17 Nov 3 AM, ONE last column, approved): a count = fruit per box/tray. Piece packs → boxes at
    each count of the New-tab spec, rounded up: 900 pcs at "90, 100" → "90C: 10 Box | 100C: 9 Box". Avocado and
    Blueberry say **Tray** (`tray_parents`). **Blueberry is always "Punnet"** (Pack column too, whatever the gram
    size) and 12 punnets = 1 tray (`punnets_per_tray` {Blueberry = 12}): 119 punnets, 16mm → "16mm: 10 Tray".
    Kg packs "18C: 70 kg"; gram/box packs → the spec only. SKUs in one row with different specs → one part each.
    Later: 10 kg box for 56/60-count trays.
  - The pack itself a container ("1 Box", Namdhari green apple) → "10 Box", Fruit needed blank. **Known gap**
    (user asked to be reminded): box packs have no kg/pieces yet; fix later.
  - Mapping Whole / spec labels are only a fallback for the Batching sheet when there is no New tab. A permanent
    master for production is to be fixed later (user: "take it from New for now").
- **By customer** (19 Nov, user-approved; 3rd tab on the Production page): one section per customer + city, **all its
  stores clubbed** (Swiggy WH1 + WH2 = "Swiggy · WH1 + WH2"), **cold-room stores apart** ("Swiggy Cold Room").
  **One row per exact Customer SKU Name** (only case/spaces ignored; Snacky Avocado and Avocado never clubbed).
  Columns: Parent SKU, Customer SKU Name, Variety (only when any), Repacking, Spec-Size (that line's own New-tab
  spec, e.g. "22C, 24C"; "to fill" / "not in New tab"), one qty column per store, Total, **At spec** (boxes/trays
  at each count for piece packs, kg for kg packs, Blueberry 12 punnets a tray); Total row. **No Origin.**
  PDF = one customer per page, Excel = one sheet per customer. `production_calc.make_ready_by_customer`,
  `customer_group`, `_spec_cells`. Also mailed every hour as a **second PDF** (`Production_by_customer_*.pdf`).
- **D+1 customers** (17 Nov 2:30 AM; secret `next_day_customers`, default {Zepto = ["Bangalore"]}, a word of the
  city; per customer/city, more later): their rows are **left out of the main production tables** for the selected
  date and shown in their own section at the bottom: **Today's order** (delivery = selected date) above, **Next-day
  order (process today)** (delivery = date + 1) below; each with Make-ready list / By spec size + CSV/PDF.
  The production e-mail is unchanged (all customers).
- **Batching sheet:** **one table** with columns City, Customer, Delivery point, Parent SKU, **Customer SKU Name**, Variety, Lot, Lot Size, Spec, Qty, Indent. Downloads: PDF/Excel/CSV.
  - **Temporary (16 Nov)**: when the New tab exists, Spec = New tab Spec-Size, Variety = Apple only (New tab first),
    Lot Size as on production, so batching matches the production sheet; missing SKUs show "not in New tab (name)"
    and are listed in a warning. Without a New tab it falls back to Mapping Whole. The user will decide the
    permanent master (where production and batching pull from) later.
- **Hourly tracker (19 Nov v3, user-approved; `core/tracking.grid`, `pages_src/tracker.py`)**: ONE view. Filters:
  delivery date, city (>1), customer pills with counts, "Only changed items" toggle (off = every SKU). Customer
  (A-Z) → store/indent header (entered, edited times, PO time, items, qty, changes) → every item. Columns every 30
  min from 8 AM (+ Now) and a last **PO vs indent** column (No PO yet / "PO n · Match" green / "PO n · −3" red).
  Cell = qty; **only in the half hour it changed** the change in brackets: green (+46), red (−50), yellow (±) =
  changed and back. After that the qty stays **yellow** (went up) or **red** (went down) **until the PO**; from the
  PO (status Frozen) on, plain. An item entered and changed in the same half hour is compared with what was first
  entered; an item added to an existing indent shows (+qty). PDF (one customer per page) + Excel downloads.
  Old tabs (By customer / By store / Indent vs PO) removed. **Not in the mail yet** (user will decide later).
- **Production e-mail content (19 Nov)**: back to the first format: 1) Make-ready list, 2) By spec size (body +
  PDF + Excel) + the **Production_by_customer PDF**. The SKU-changes / Indent-vs-PO sections were removed.
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
- **SO/PO**: sent on every PO upload to the PO list. **Attachments (17 Nov): only the PO as PDF (the customer's
  uploaded file) + the PO as Excel** (`PO_<indent>_<po no>.xlsx`: items, indent qty, PO qty, Diff). No SO PDF.

### Owner tools

- **Bulk download** (owners only) on All indents and Upload PO: tick "Select all" or pick indents. It downloads one Excel with two sheets: **Indents** (one row each, including the PO number) and **Lines** (every item).
- **Add SKUs** (Access tab, owners; 18 Nov): paste SKU names (order style or ours) for a city + customer →
  preview table (editable Parent SKU / our name; ✓ already in master by exact name / 🆕 will be added / 🔴 pick an
  existing Parent SKU) → "Add to the sheet" writes
  them to All Cux City + New tab (yellow spec cells only, no status text) via `master_add.add_items`. `pages_src/add_skus.py`.
  19 Nov: an **Origin** column (country from the name, else the parent's most used origin in New; editable;
  "Tanzania, Kenya" = one New-tab row per origin, first = in use — production reads the first row). When "Our SKU
  name" differs from the pasted name, the pair is saved to PO_Item_Map, and **Attach the order** uses that exact
  saved name first (e.g. Zomato "BH-Valencia Navel Orange Imported, (350) g" → "3PC - BH-Valencia Navel Orange
  Imported"). Zomato style names: "BH - Green Kiwi, 3 pieces" → "3PC - BH - Green Kiwi".
- **Fill empty New-tab rows from Mapping Whole** (Access → Add SKUs, expander; 19 Nov; `core/fill_new.py`): every
  New-tab row with no Spec-Size and no Spec-Origin gets the closest Mapping Whole SKU (same name, else same parent
  + most alike name, same pack preferred): its Active (else first) origin + size fill the row, repacking from the
  reference's New row; other origins → extra New rows. Editable preview, then "Write".
- **Add a store** (Access → Add SKUs, expander): City + Customer + Store → Customer List (how a new city starts).
  18 Nov: PTP Hyderabad and PTP Mumbai added with Swiggy, Zepto, Zomato (placeholder stores "<Customer> - <City>").
- **Import indents** (Access tab; **Owner only**, not Owner L):
  - Input is an Excel upload or rows pasted as text (tab, `|` or comma separated, header first).
  - Columns: Delivery date, City, Customer, Store, Parent SKU, Item / Customer SKU Name, Qty, and optional Price/Rate.
  - Options: one city for all rows, one price for all rows (default **1**) or the file's price, and the expected time.
  - Each customer + store + date becomes one indent.
  - If the store isn't found and the customer has **one** store in the master, that store is used.
  - Missing SKUs/stores can be added to All Cux City / Customer List first. Creating indents is blocked until they are added.
- **Zepto Excel upload** — **page removed 18 Nov** (Attach the order on Create indent handles Excel/PDF for every
  customer); `core/zepto_import.py` is kept for the reader. Old notes: (17 Nov; Zepto in the
  Bangalore city only): Zepto's indent Excel (Product Name, UOM, EAN, Pack Date, one qty column per warehouse
  "… Final", Summation). Each warehouse column with qty → one indent; store picked per column (guess: HSK →
  Yalachanayakanapura, NLM → Nelamangala). **Delivery date is picked on the page** (default = the file's Pack Date;
  yesterday/today/tomorrow; owners may pick a closed day = retro order, `submit_new(retro=True)`; 17 Nov: an
  order meant for 17 was created for 18, hence this);
  price for every line (default 1); expected time. Products matched like PO lines (PO_Item_Map by EAN/name, name +
  pack, close); **creating is blocked until every product is mapped or skipped** (if a SKU is missing, add it to
  All Cux City and press Refresh master). Picks are saved to PO_Item_Map. Duplicates point to the existing indent.
  `core/zepto_import.py`, `pages_src/zepto_upload.py`. Tested on the 17 Nov file: 22 products, 3,397 qty.
- **Swiggy Bangalore** POs/GRNs come from Moksh (procurement_blr@mokshepl.com, files MOKS-1N60000590-*): PO numbers
  MBFPO (BLR FNV1 / WH1), BLRPO (Bangalore FNV2 / WH2), BLNPO (Bangalore, "Bulk PP" items). Swiggy names look like
  "Longan 100.0 g" → our style "100gm - Longan" (`master_add.new_sku_name`).
- **Swiggy Hyderabad**: Cloudkart (procurement@cloudkart.co, files CVPL-1N60000590-*), PO numbers HDFPO. Others seen:
  Cloudstore (Panvel/Mumbai, CMPPO), Jupiterkart (Chennai, CHNPO), PJTJ (NCR: NCRPO/GGMPO).
- **Change date** (owner, All indents → an indent): move an indent to another delivery day (2 days back to
  tomorrow), ignoring the cutoff; same status, new version + Change_Log (`indents.move_date`).
- **Start fresh** (Owner only): type CLEAR. It backs up the indent tabs to Backup_ tabs and then empties them.

### 19 Nov afternoon (user-approved)

- **Name links with owner approval**: a PO / order name that is not exactly ours gets a suggestion
  (`po_reader.suggest` / `_soft`: every word of our SKU in the name, small spelling slips allowed, markers agree;
  'Avocada Jumbo (PCS) - FK - Grade A' → '1Pc - Avocado Jumbo - FK'). Upload PO: an **Approve** column (owners
  only) saves the link to PO_Item_Map; others' picks count for that PO only. Attach the order: a **"look like items
  we have"** box: Owner **Approve** (use ours + save link) / others **Use ours** (this order only) / **Keep as new**.
- **PO vs indent uses PO_Item_Map** (`indents.po_vs_indent(..., item_map | customer=)`), so linked names match.
- **Hourly tracker**: PO-only items (on the PO, not on the indent) show last in their indent, name in red,
  "Not on indent · PO n".
- **Sheet tabs Indent_vs_PO and Indent_Changes** (`core/sheet_views.py`): rebuilt after every save (indents.*
  write functions wrapped by `_with_views`, background thread on Google) and once after a redeploy. Indent_vs_PO:
  one row per item, Result Match / Differs / Not on PO / Not on indent (red rows) / No PO yet / More POs coming.
  Indent_Changes: item changes only (qty/price, added, removed, delivery moved), newest first. The app never reads them.
- Mail_Log stays (stops double hourly mails). The 4 Backup_20261115_2238 tabs: user to decide.

### 19 Nov night (user-approved)

- **Attach the order, editing a saved indent**: "File vs saved indent" table: In the file, Our SKU name, **Saved**,
  **File**, Change (🟡 +n up, 🔻 −n down, 🆕 new/added, ✓ same, 🔴 not in file); changed lines first, "Only
  changed lines" toggle; saved items missing from the file get **Set 0 / Keep** buttons; a file equal to the saved
  indent → green "Same as the saved indent … Nothing to update." File qty still replaces (never adds to) saved qty.
- **Customer check on attach**: `order_reader.whose` finds customer names in the file (text, file name, Zepto
  format) using `config.customer_aliases()` (secret `customer_aliases`; More only by "more retail"/"more_blr"/…,
  never the plain word); if the file names only other customers, nothing is added ("looks like a X order").
  A file naming nobody is allowed.
- **No-PO customers** (secret `no_po_customers`, default ["More"]): Upload PO takes a **screenshot** (PNG/JPG/WEBP)
  or PDF; PO number optional; PO qty starts from the indent qty. SO/PO mail attaches the screenshot as is
  (`mailer.file_mime`). To be refined as we go.
- **Picture reading with Gemini** (`core/ai_reader.py`; user chose Gemini over Mistral / Cloud Vision): secret
  `gemini_api_key` (user adds it; pictures switch on when it is set; `read_pictures` overrides), `gemini_model`
  (default gemini-3.8-flash, falls back to gemini-2.5-flash on 404). JSON answer: customer, store, total, lines
  (name, pack, qty, sure). Used by Attach the order (photo shown next to the list for comparison; unsure lines =
  🟡 check) and by Upload PO screenshots of no-PO customers (lines → the same "Our SKU" table; "⚠ hard to read";
  total vs lines checked). Without a key: Tesseract fallback (pictures off by default). Free-tier data may be used
  by Google; a paid key avoids that. Not tested against the live API from the Claude cloud (network blocked).

- **New customers without SKU names (19 Nov, user: "collect data and start things")**: Create indent no longer
  stops at "Mapping pending": Attach the order still shows; every line becomes a 🆕 new item (Parent SKU guessed
  from all cities' parents, `PARENT_HINTS` e.g. Baby Orange → Mandarin; a new parent stays red) and is added to
  All Cux City + New on Submit; the file name (and its code) → our name is saved to PO_Item_Map
  (`attach.links_to_save`), so each order teaches the next one.
- **Name style for pack inside the name** (`master_add._mid_pack`, Bigbasket): 'Fresho Kiwi - Green 3 pcs ( 240 Gms *)'
  → '3PC - Fresho Kiwi - Green (240 Gms)', 'Fresho Baby Orange 1 kg ( Imported)' → '1Kg - Fresho Baby Orange (Imported)'.
- **Excel reader**: name heads include "Sku Description"; code column (Sku Code / EAN) kept; when no qty header,
  the first mostly-numeric column right of the names is the qty (Bigbasket puts the store name there); a '-'
  name row is the total.
- 19 Nov: PTP Hyderabad · Bigbasket added with placeholder store "Bigbasket - PTP Hyderabad" (rename later).

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
- `tests/`: pytest, **185 tests passing**. Run `python -m pytest -q` and `python -m pyflakes core pages_src app.py`.
- `MT_INDENT_BUILD_SPEC.md` is the original build spec. `README.md` is the setup guide.
- Requirements: streamlit>=1.67, gspread, google-auth, pandas, tzdata, fpdf2, openpyxl, pdfplumber; packages.txt: tesseract-ocr.

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

