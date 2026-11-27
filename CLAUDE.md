# CLAUDE.md: MT Indent app (project context for Claude sessions)

Last updated: 21 Nov 2026. Owner of this work: MT Direct Sales team, Ninjacart (PTP Bangalore).

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

- **Auto-redeploy stopped on 23 Nov** (pushes reach GitHub but the app keeps the old code). After every push,
  **reboot from Chrome**: share.streamlit.io (signed in as GitHub user Kathiramirtheeswaraa, user-approved
  24 Nov) → workspace menu top-left → **naveenkumarrangasamy-collab** → indent-salesapp ⋮ → Reboot → Reboot.
  The app is back in ~1 min (first load may show an error page; reload). No data is touched.

- The GitHub API for Actions and secrets is blocked from the Claude cloud proxy, so use Chrome (Claude in Chrome) for anything in the GitHub web UI.
- File uploads into Chrome from the user's computer need the user to pick the file. Use the **paste box** on the Import indents tab instead.
- In Chrome, the app runs in a same-origin iframe. Open `/~/+/<page>` to work on it directly.
- Glide data-editor cells: click, Enter, type, Enter.

## 3. People, roles and e-mail lists (live, 16 Nov 2026)

Sign-in is **e-mail + PIN** (4–6 digits, hashed with `pin_pepper`). A sign-in lasts 24 h. It is kept in localStorage plus a one-time `?s=` token, so a refresh keeps the user signed in.

| Role (sheet value → shown as) | Can do |
|---|---|
Shown in this order in the pickers (21 Nov): **Warehouse, Sales, Owner, Creator** (sheet values unchanged).

| Role (sheet value → shown as) | Can do |
|---|---|
| `warehouse` → Warehouse | Production sheet, Batching sheet and Hourly tracker only (for their cities; empty = all). Cannot make indents. |
| `sales` → Sales | Create/edit indents and upload POs, limited to their **cities** (empty = only their own indents). **No** production, batching or tracker pages. |
| `owner` → **Owner** | Everything **except** Import indents, Start fresh and the E-mails tab, **only in his cities** (City column; empty / "All cities" = all). The **Access page only if Admin_Page = yes** (Access tab column; set by the Creator, default no). On Access he sees/adds/edits only Warehouse and Sales users in his cities and can never give Owner or Creator. |
| `owner_full` → **Creator** | Everything, all cities. Only the Creator gives Owner/Creator, sets an Owner's cities and Access page, and sees the **E-mails** tab. The `owner_email` in secrets is always the Creator. |

- City picker on Access: an **All cities** tick + the city list (Owner: empty = all; Sales/Warehouse: every city listed).
- A user mapped to one city has no City filter on production.
- The `owner_email` in secrets can always sign in (as Creator).

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
- **Access**: columns Email, Name, Role, Status (active/revoked), PIN_Hash, Updated_At, Updated_By, City (comma list), Stores (unused), Admin_Page (yes/no, Owners only; added 21 Nov). It is edited only from the app.

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
- **Apple needs a variety.** 21 Nov: **the name wins** when it names one (Royal Gala → Gala, Granny / **Green** → Granny Smith, Queen → Queen, Red Delicious → RD; `masters.name_variety`), else the New tab, else All Cux City, else the user picks. The list = the sheet's Apple Varity list **plus** the full built-in list (the sheet had only Gala, Envy, so Granny Smith / Queen could not be found).
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
- **Production e-mail content (21 Nov)**: **Production by customer only** (see 21 Nov night).
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
- **Import indents** (Access tab; **Creator only**):
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


### 20 Nov morning (user-approved)

- **Pictures removed** (user: "we don't want pictures"): no Gemini / OCR.space / Read order picture page;
  `read_pictures` off. More's screenshot can still be attached as its PO (not read). The secrets
  `gemini_api_key` / `ocrspace_api_key` are unused now.
- **Bulk indents page** (Indents → Bulk indents, `pages_src/bulk_indents.py`, `core/bulk_tabs.py`; sales in
  their cities + owners): one Excel per city, **one tab per store** (tab name = store; Template button), columns
  Customer SKU name | UOM | Qty. Tab → store: remembered tab name (Store_Aliases) → exact store name → customer
  with one store → one close name → else type customer + store (new ones are created). Per tab: 🆕 new indent /
  🟡 update IN-0xx (only if a qty changed or an item is new; saved items not in the tab stay) / ✓ same, skipped /
  🔴 needs you (no time, new fruit, PO done/locked). Same SKU twice in a tab is added up. On save: new stores →
  Customer List, new SKUs → All Cux City + New (yellow), name links → PO_Item_Map, times → Delivery_Times,
  tab names → Store_Aliases.
- **Delivery times page** (Admin → Delivery times, `pages_src/delivery_times.py`, tab **Delivery_Times**: City,
  Customer, Store, Time): the usual time per store; Create indent and Bulk indents start from it; a new store's
  time is typed once and saved.
- **Create indent**: the "Mapping pending" stop is gone (a customer without SKUs can attach its order);
  **＋ New customer / store** (popover; added to the Customer List + its time to Delivery_Times on Submit);
  **Customer SKU name is a dropdown on every line** (rename = qty moves to the new name; a saved name stays at 0);
  **↻ Refresh SKUs** next to "Items for …".
- Attach: the same SKU twice in one file is **added up** ("➕ combined 370 + 49"), no longer red.
- Names: Zepto UOM "1 Pack" → **"1Pack - …"** (was 1PC), matching the master.
- Apple variety: the **New tab variety wins** (`Masters.new_tab_variety`, `default_variety`), and it is fixed on
  the line when set.
- **Access → Duplicate names** (`bulk_tabs.duplicate_names`): per city + customer, one name on several rows or
  several names with the same words (e.g. 1Pack ×3 / 2PC - Kiwi Sungold / 2PC - Sungold Kiwi).
- Not done (waiting on user's yes): IN-023 data fix (Kiwi Sungold 2PC → 1Pack; Apple varieties Gala → Granny Smith / Queen).

### 21 Nov night (user-approved)

- **Create indent starts from the store's last order** (`items._prefill`, `indents.last_order`): picking the
  store of a new indent loads the items of that store's latest indent before the delivery date (current version,
  qty > 0, exact names) at **qty 0, price 1** (variety from the name). Lines left at 0 are **not saved**
  (`items.to_save`); all zero → "Enter a quantity for at least one item." Lines can be removed / added. No
  indent number shown. Only when the list is empty (or only zeros). Price stays a plain number, default 1:
  **no ₹ and no amounts/totals** anywhere on Create indent (add form, phone cards, edit dialog, review).
- **Roles** renamed / Owner city-scoped / Access page flag / E-mails Creator only (section 3).
- **Access → Duplicate names → Apple variety vs name** (`core/variety_fix.py`): lists New / All Cux City /
  Mapping Whole Apple rows whose variety column disagrees with the name; "Fix n row(s)" writes the name's variety.
- **No "Page not found"**: Streamlit serves the default page only at "/", so `/signin` was unknown. The sign-in
  gate's default is `login`, and `signin` + every old/role-missing address (GATE_PATHS) is its own page; signed
  in, those addresses are hidden menu pages that `st.switch_page` to Home (Production for warehouse)
  (`common.hide_nav_links`, `st.navigation(expanded=True)`).
- **Bulk indents page removed from the menu** (user, 21 Nov 2 AM); `/bulk-indents` redirects to Home. Code
  (`pages_src/bulk_indents.py`, `core/bulk_tabs.py`) kept. Redirect pages are made for every address not used by
  *this user's menu* (a page built but not in the menu does not reserve its address).
- **Item numbers (#) everywhere items are listed** (user, 21 Nov 2:15 AM; `common.numbered` adds a "#" first
  column, 'Total' rows get none): Create indent item table + phone cards + review, All indents cards and the
  Open detail, Upload PO items, Production (By spec size, Make-ready, By customer, D+1 tables), Batching sheet,
  Hourly tracker (per indent, also its Excel/PDF), Upload PO dialogs (read-from-PDF and qty tables, differences),
  Attach "File vs item list", SO/PO mail items (`reports.so_df`). Cards show a small muted number (`.mt-num`,
  `common.num_label`); tables a narrow "#" column. Page downloads include it.
- **Hourly production e-mail = Production by customer ONLY** (user, 21 Nov 2:18 AM; replaces the 19 Nov format):
  body = one numbered table per customer (`reports.by_customer_view`), attachment = one PDF
  `Production_by_customer_<date>_<hh>.pdf` (one customer per page). No make-ready / spec-size tables, no Excel.
  Same hourly trigger and Mail_Log.
  **Look (user, 21 Nov 8 AM):** centred; ONE very light blue (#E4F0FB) only for the header band and table
  headers, everything else white, **all text black**, thin grey-blue lines, bold Total row (no fills, no amber,
  no green). Palette in `reports.MAIL` / `pdf_report.PDFC`. PDF = `pdf_report.customers_pdf`: customers one
  after another, as many per page as fit; a customer that does not fit the space left starts on a fresh page;
  one longer than a page continues with "(continued)" + column header, numbers carrying on; never a page with
  only the Total row.
- Not done yet: the visible refresh when switching pages (user item 5).

### 22 Nov (user-approved; OWNERS ONLY while being tried — nothing changes for sales / warehouse)

- New menu section **"Pre-production (owners, trial)"** with two pages (`pages_src/preprod_actual.py`,
  logic `core/preprod.py`, tests `tests/test_preprod.py`). Production sheet / Batching sheet are unchanged
  (the user will merge later; the Production sheet is to be called "Pre-production estimate" then).
- **Pre-production actual** (`/preprod-actual`): per delivery date + city + customer (stores clubbed, cold
  rooms apart, like By customer). Per SKU: need (qty × pieces per pack, or kg), **Country** (gives the counts /
  sizes and box kg; fixed after the first take-out), suggested boxes, then **boxes taken out at each count**.
  **Save take-out · round n** records one trip (reason: First take-out / More for grading loss / Short in
  first take-out / Other); trips add up; history table. Status 🟢 Enough / 🟡 Not enough / 🔴 Not started.
  **Freeze** (lock, last step, needs no unsaved boxes) closes the customer; owner can Unfreeze.
- **Batching plan** (`/batching-plan`): frozen customers only. One row per SKU + count with the boxes taken
  (read only) and **Used** (good pcs / kg) to enter; per item: needed, max (+`batching_extra_pct`, default
  10 %), used, extra/short, **left in boxes** (auto), status Covered / Short / Pending / Over limit. Saving is
  blocked when over the limit or when used > what the boxes hold.
- Tabs (created on first save, append-only, last row wins): `Preprod_Actual`, `Preprod_Freeze`,
  `Batching_Plan`. Country master: **`Batching_Master`** (City, Customer, Customer SKU Name, Parent SKU,
  Country, Spec "90, 100, 110", Unit Box/Tray, Box Kg) — the user will fill it; until a SKU is there the New
  tab (Spec-Origin + Spec-Size) and then Mapping Whole (Spec-Origin, Spec-Size, Box Kgs) are used.
- **New Mapping sheet** (22 Nov evening; `core/mapping_sheet.py`, secret `mapping_sheet_id`, default
  `1A2zerkNL46XIlJwaBH2kL5TcaT04b_nfk4TVKG54-nM`; service account has **Viewer**): the team's master.
  Tabs: Parent (Parent SKU, Variety/grade, Origin, Spec, Origin Lot = box kg, built from the fruit tabs),
  Customer (City "PTP …", warehouse-style customer, SKU Code, Parent SKU, customer SKU Name, Packaging),
  Combination (customer variety / spec / country, as typed), **Combination 1** (one row per SKU × country ×
  grade: Country, Variety (Parent tab), Country Spec, Origin Lot, Note; unmatched rows light red), Review.
  **Pre-production pages read Combination 1 first**: match only inside the same city + customer
  ("Zepto (KWPL)" = Zepto, Hyperpure = Zomato, Swiggy - X = Swiggy, Metro = Metro), by our-style name
  (`our_name`: '2PC - …', '200GM - …', '1KG - …', case ignored) or one clear close name with the same pack;
  else the Parent tab for the parent (+ variety); else the old masters. Option label "Country · Grade"
  (+ "· lot" when the same grade has two box weights); the page shows "From: …". Production / Batching
  sheet still use the old sheet. Old sheet's Customer List got 29 yellow rows (new cities / FCs) on 22 Nov.
  22 Nov night: Customer + Combination tabs got a **Customer SKU Name** column (col F, our style; the old
  sheet's exact name when the same city + customer has it) and 120 old-sheet-only SKUs appended (yellow;
  Combination rows with no spec/country light red). Combination 1 rebuilt (4,862 rows, cols A–O, Note in O:
  red = not in Parent tab, yellow = from old sheet). The app matches on that column first.

### 23 Nov (user-approved; trial — "go back to old format" = secret `master_source = "old"`)

- **Master switch** `mapping_sheet.use_new()` (secret `master_source`, default "new"). "old" puts Create indent
  and the pre-production countries back exactly as before 23 Nov. The old sheet is never changed by the app for
  this; its yellow rows (All Cux City 201–501, New 99–538, added 22 Nov) stay.
- **Create indent SKU list**: old SKU map + every Combination 1 Customer SKU Name it lacks (same city + customer;
  only cities that already have stores/SKUs in the old sheet), each name once (`mapping_sheet.sku_rows`,
  `masters._new_mapping_sku`). No country / box asked at indent time. Stores still from the old Customer List.
- **Counts allowed = customer spec ∩ country spec** (`mapping_sheet.allowed`, Combination 1 "Customer Spec"):
  Flipkart Avocado 18/20/22 → Tanzania 18C–22C, Kenya not offered if it has none of them; if no country fits,
  each country's own spec is shown. Applies to **every fruit** (user 23 Nov 00:44); "14mm+" = "14mm", plain "27" = "27mm" (Kiwi);
  the country's own label is shown. Checked 23 Nov: 524 SKUs, 436 match, 87 have no customer spec (all
  country sizes), 1 (Swiggy Bulk PP Royal Gala large, "30c") matches no country.
  Secret `full_spec_parents` (default []) can exempt a fruit.
- **Production sheet → "Estimate (new sheet)" tab (owners only)**: per customer: Need (pcs / kg, firm),
  Countries, Counts allowed, Box kg, **≈ Boxes** = range over every allowed country + count
  (`preprod.box_range`, `estimate_rows`). **Every Blueberry is a punnet on the estimate** (12 a tray, any size;
  `box_range`). Pre-production actual / Batching plan: Blueberry in **punnets**, 1 tray = 12 punnets at
  any size (user 23 Nov 12:36), boxes still entered per size; In boxes / Left over = trays × 12.
  Exact boxes on Pre-production actual.
  The other production tabs, mails and Batching sheet are unchanged (old sheet).

- **Batching plan look (23 Nov, user-approved preview)**: step 1 = one row per SKU + count, grey read-only
  columns and ONE yellow **Used** box per row (number_input in a `st-key-bpin*` container, CSS `BP_CSS`);
  step 2 **Per item** = tiles (Items / Covered / Short / Still to enter) + one bordered card per item: Needed
  (max), Used, Extra/short, **Left over** (taken out − used), yellow **GT Qty** and **Dump** to type, **Back to
  box** = left over − GT − Dump (auto; save blocked when negative), status chip. GT/Dump saved in Batching_Plan
  as a row with spec `_item` (cols `gt_qty`, `dump`; `preprod.item_saved`, `back_to_box`).

- **Pre-production counts look (23 Nov, user-approved preview)**: each count box labelled only "90C" (no
  "· 0 taken"), 5 per row (wraps), no +/- buttons, green when a number is typed (`st-key-pacnt_has*`), a small
  green "N taken" under a count only when something is saved there (`PA_CSS`). Suggested reads
  "90C 6 · 100C 5 Box".

### 23 Nov evening: Dispatch → Returns → Invoice (user-approved preview; OWNERS ONLY, trial)

- Menu **"Dispatch (owners, trial)"**: Dispatch (`/dispatch`), Returns (`/returns`), Dispatch check
  (`/dispatch-check`); `pages_src/dispatch.py`, logic `core/dispatch.py`, tests `tests/test_dispatch.py`.
- **Dispatch**: indents whose customer is frozen in Pre-production. One row per item: Indent, Batched (Batching
  plan used ÷ pieces per lot, minus what other stores of the same customer already dispatched), yellow
  **Dispatch qty** (starts from batching), vs indent (Same / short / +extra / over the 10 % limit) and vs batching
  (Matches / over / under). Over limit or over batching needs a reason. Vehicle, driver, time →
  **Delivery Order** `DO-IN046-1` (proforma PDF; a re-dispatch makes -2 and replaces it). Tab `Dispatch_Lines`.
- **Returns**: dispatched indents; yellow Returned + reason (Damaged / Quality / Over PO qty / Short shelf life /
  Other); Billed = dispatched − returned → **final invoice** `INV-IN046` (PDF, rate = indent price, GST from secret
  `gst_pct` {parent: %}, HSN from `hsn_codes`). Tab `Return_Lines`. Seller details: secrets `company_name`,
  `company_address`, `company_gstin` (until set the PDFs show [NAME] etc.).
- **Dispatch check**: tiles + one row per indent with dots Indent / PO / Pre-production / Batching / Dispatch /
  Returns / Invoice and a note; item-by-item trail (Indent, PO, Taken out, Batched, Dispatched, Returned, Billed).
- **Required (indent) qty shown till the end** (user 23 Nov 8 PM): Batching plan step 1 has a **Required** column (once per item), per-item cards say Required, Dispatch / Returns / Dispatch check trail all have a **Required** column.
- **Batching plan per item** also has **MT Grade** (typed); Back to box = left over − MT Grade − GT Qty − Dump;
  each card = name + status on top, 8 equal columns under it.

### 23 Nov night: Return grading + MT stock (user-approved video/preview; OWNERS ONLY, trial)

- **Return grading** (`/return-grading`, Dispatch menu; `pages_src/dispatch.render_grading`, logic `core/regrade.py`,
  tests `tests/test_regrade.py`): pick the delivery date whose returns came back; one row per returned item (in pcs /
  kg / punnets = returned packs × per pack), Count (the counts taken out for it, else Any), yellow **MT / GT / Dump**;
  status Graded / n left / Not graded / Over (save blocked when more than returned). Tab `Return_Grading`.
- **MT stock pool** for Pre-production of day D = MT graded from the returns of D − 1 + Batching plan **MT Grade**
  of D − 1, by city + parent + variety (Apple only) + unit, **not by customer**. Not used on D → goes to GT (just not
  counted later). GT / Dump / Sample are only recorded for now.
- **Pre-production actual**: per SKU a yellow **Use from returns · n available** (available = pool − what other
  SKUs/customers used that day); From boxes = required − use; suggestion and status use it; saved with the take-out
  (tab `Return_Use`, last row per day + group + SKU). Never blocks: 0 available → take boxes as usual.
- **Batching plan**: returns used count as stock in hand (Used "incl. n returns"); per item now 9 columns with
  **Sample**; Back to box = left over − MT − GT − Dump − Sample; item rows also save parent_sku / variety (pool).
- **Returns**: **Customer sample** column (kept by the customer, not billed): Billed = dispatched − returned − sample.
- **Dispatch check**: new **Graded** dot; Batched on Dispatch includes returns used.

### 24 Nov: variety before Submit (user-approved)

- **Create indent / attach**: Submit and Update are off until every Apple line with a qty has a variety
  (`items.variety_missing`; red banner over the item list + "🔴 Choose the variety for n item(s) first").
- Variety order: name → **New Mapping Combination** "Customer Variety" when it names exactly one
  (`masters.combo_varieties`, `Masters.combo_variety_for`) → New tab → All Cux City → the user picks.
  Snacky / Daily / Everyday / Bulk apples list all 11 in Combination, so they are always asked.
- **Mandarin and Orange ask too** (secret `ask_variety_parents`, default Apple, Mandarin, Orange): their list
  is the New Mapping **Parent** tab (Mandarin: Xinyu, Wogan, Afourer, Honey Murcott, Nova, Nadorcott, RHM,
  Murcott, Tango; Orange: Valencia, Midknight Valencia, Navel; `masters.parent_varieties`). Avocado, Blueberry,
  Kiwi, Grapes are not asked. Production tables still show variety for `variety_parents` (Apple) only.
- **Estimate uses the indent's variety**: Combination 1 rows of the SKU are narrowed to that variety's grades
  (`mapping_sheet.options`; Snacky Apple + Gala → only Gala countries/counts); all rows if none match.
- IN-049 (Firstclub, 23 Nov) "FirstClub Special Apple - King Size" was saved with variety **Envy** by hand; no
  mapping says Envy, so its estimate showed Envy only.
- Aliases: "red del" → RD, honeycrisp, cripps pink → Pink Lady; Honey Crisp + Cosmic Crisp in the list.
- **Production sheet → "Estimate (consolidated)" tab (owners only, 24 Nov)**: every customer clubbed, no names;
  one table per city + fruit, one row per variety (grade) · country · box: Need, SKUs · customers, **Boxes at each
  count** ("90C · 6 | 100C · 5"), Total; tiles Boxes from primary / Fruits · rows / Variety not chosen
  (`preprod.consolidated`). A SKU uses its first country option; its pieces are shared **evenly** over its allowed
  counts; boxes rounded up per count after clubbing. Kg lines → kg ÷ box kg; Blueberry → punnets ÷ 12. Lines with no
  variety (Apple / Mandarin / Orange) stay in a "Variety not chosen" row. Both estimate tabs use
  `preprod.demand(by_variety=True)`: the same SKU with two varieties → two rows (pre-production pages unchanged).
- **Washington = USA (country), not a variety** (user 24 Nov): `mapping_sheet.name_country` (washington/usa → USA,
  shimla/kashmir/himachal → India) narrows a SKU's Combination 1 rows to that country when it has any; the
  variety is still asked. **Shimla** added to the Apple list. The 5 near-duplicate names are the same products
  (user 24 Nov); they are clubbed on the consolidated estimate; the sheet rows are left as they are.
- **Production / Batching sheet filters (24 Nov)**: Delivery date = buttons ("Today · Tue 24 Nov (2)", every date
  with indents, All dates), City = pills; the Batching sheet has no tiles; blank (not "None") PO qty / Difference.
- **Batching sheet (24 Nov)**: columns Delivery date, City, Customer, Delivery point, Parent SKU, Customer SKU
  Name, Variety, Lot, Lot Size, Spec, **Indent qty, PO qty, Difference (PO − indent), Status**; **no Indent
  column** (screen, PDF, Excel, CSV). Status + row colour: Match / **PO lower** and **Not on PO** = red (PO qty
  blank, never 0) / **PO higher** = yellow / **Not on indent** = orange (PO-only items, own rows) / No PO yet.
  Swiggy POs are summed, PO_Item_Map links used (`production_calc.with_po`, `STATUS_COLOURS`,
  `pages_src.production._po_quantities`); Excel rows carry the same colours (`reports.xlsx(row_fill=)`).
  The **Batching_Sheet** tab of the Google Sheet is a running table with the same columns + Updated at (newest
  date first), written automatically when the page shows one delivery date and the numbers changed (that date +
  those cities replaced, other days kept; `merge_sheet`). The old snapshot button is gone from this page.
- **Freeze instead of a PO** (24 Nov; secret `no_po_customers`, default **Amazon, Bigbasket, Reliance, Trent,
  More, Metro, Namdhari, Firstclub** (user 24 Nov 1:46 / 1:49 PM; the user will send more);
  matched on the customer's first word, `config.can_freeze`; **Amazon, Namdhari, Firstclub start on Upload PO**, Freeze still
  offered, secret `po_first_customers`): their PO dialog starts with a **PO** dropdown: **Freeze** (default; no file, quantities
  start from the indent, edited or not they are saved as the PO and the indent is frozen) or **Upload PO** (file
  needed, PDF or screenshot, as for other customers).
- **Items on a PO that are not on the indent** (24 Nov): Batching sheet row with **Indent qty 0**, the PO qty and
  Status "Not on indent" (orange). On save the item is named in our style and, when its fruit is known, added to
  All Cux City + New (`indent_actions._name_new_items`); the indent itself is not changed.
- Swiggy (multi-PO): a later PO may carry an item that is not on the indent ("Items on the PO that are not in
  this indent" / read from the PDF) → shown as Not on indent; after **End of POs** nothing more is added.
- **24 Nov 10 AM**: **Zepto like everyone** (D+1 section off: `config.next_day_customers()` returns {} unless
  secret `next_day_on = true`); today's Zepto orders under today, tomorrow's under tomorrow.
  **Estimate (consolidated)**: ≈ Boxes is a **range** (all at the biggest allowed count … all at the smallest),
  column Counts instead of per-count boxes; tile ≈ lo–hi. Both estimate tabs: **city is its own header**
  ("### PTP Bangalore"), then one table per fruit (consolidated) / per customer (new sheet), no city in the
  table titles.
- **24 Nov 10:20 AM (user)**: **only Apple asks for a variety** (`ask_variety_parents` default ["Apple"]; Mandarin /
  Orange no longer asked). **No spec in the New tab → the customer's spec from New Mapping Combination**
  ("Customer Spec", country ignored; `Masters.prod_info` falls back to `combo_spec`, built in the cached
  `_variety_maps`; '18, 20, 22' → '18C, 20C, 22C', Kiwi '33, 36' → '33mm, 36mm', '16mm+' → '16mm'). So Production
  (By spec size / Make-ready / By customer), Batching sheet and the "not mapped" warning use it.
- **PO as Excel / CSV (24 Nov 12:45)**: Upload PO takes .xlsx / .xls / .csv too (every customer); item + qty
  columns are read like an attached order (`order_reader._excel` / `sheet_lines`, incl. the Zepto format) and
  then matched / checked exactly like a PDF PO (`indent_actions.read_sheet`); unreadable → type qty by hand.
  The file is attached to the SO/PO mail with its own type (`mailer.file_mime`).
- **Earlier POs in the PO window (24 Nov 1 PM)**: when an indent already has a PO (Swiggy's several, or a Replace PO),
  an open box "Earlier POs · n uploaded · m item(s) still pending" lists each PO (number, time, by) and one row per
  item: Indent, qty on each earlier PO, This PO, Pending, Status (Done green / Pending red / Extra yellow / Not on
  indent orange) (`indent_actions._earlier_pos`, `indents.po_list`, `indents.po_progress`).
- **BLR dispatch sheet sync (24 Nov 4:41 PM, user-approved)** (`core/dispatch_sync.py`, tests
  `tests/test_dispatch_sync.py`): the ops sheet "BLR FF Ops - Tracker" (secret `dispatch_sheet_id`, default
  `12Zc6-C19dHKxrrdI1XsHn0Hl8zt-mbhxyssb9m5eVTk`), tab id `dispatch_sheet_gid` (default 339596934; renamed "Auto 03 - BLR_MTDispatch" on 24 Nov, name `dispatch_sheet_tab` is the fallback),
  cities `dispatch_sheet_cities` (default PTP Bangalore), days = today − `dispatch_sync_days_back` (2) … tomorrow,
  never before `dispatch_sync_from` (default 2026-11-24, user 24 Nov 4:50 PM).
  The app writes **only A–M** (Date … Diff in Indent and PO = PO − indent); **N onwards is typed by people, never
  touched**. Rows are matched by Date + Customer + Delivery point + SKU + Variety and only updated; new lines are
  written under the last row used in A–M; nothing is moved or deleted; an item that left the indent keeps its row
  with Indent Qty 0. Colours as the Batching sheet. Runs on the server after every save / PO / freeze (with
  `sheet_views.refresh_soon`), after a redeploy and on every `?hourly=run`. Needs the service account as **Editor**.
- **Pre-production actual = city level (24 Nov 6:45 PM, user-approved; owners, trial)** (`core/preprod_city.py`,
  `pages_src/preprod_city.py`, tests `tests/test_preprod_city.py`; replaces the per-customer page, whose code stays in
  `preprod_actual.py`): date + city (Bangalore first); every customer clubbed, one row per fruit + unit, **Apple per
  variety**, **every Blueberry = punnets** (12 a tray). Need = PO qty when the indent has a PO (not on PO = 0,
  PO-only items count), else indent qty, × pcs/kg per pack. "Asked" = need split by the customers' spec; notes for
  POs much lower than the indent. Option dropdown "Country · Grade · Count · Box kg" from the New Mapping **Parent**
  tab (Apple: grades of its variety); boxes typed per option (rows can be added); rounds add up in Preprod_Actual
  with group **"All customers"**; Freeze the city. **Look (25 Nov, user-approved preview)**: one calm card per row
  (title · need + status chip, info line with Suggested in blue, ✓ saved take-outs), entry lines = dropdown
  "Choose…" + same-size Boxes/Trays box (thin amber outline, `st-key-pcnum*`, `PC_CSS`) + "= n pcs", "＋ Add another
  count" / ✕, thin progress bar. Round 1 is always "First take-out" (no reason asked); from round 2 the reason
  dropdown (grading loss / short / other). **Freeze 🔒** only after the first take-out is saved, with an "are you
  sure" step. **25 Nov 10:25**: each card also shows **By customer** (need per customer when more than one) and
  purple **customer needs** notes: built-in "More · Avocado: green colour" + optional tab **Customer_Notes** (City,
  Customer, Parent SKU, Note; blank City = every city) the team can fill later (`preprod_city.customer_notes`).
  **Production sheet → "Pre-production actual" tab (was "Estimate actual"), Creator only**: need,
  estimate, taken, fruit in boxes, extra/short per city. Batching plan / Dispatch still expect per-customer freezes
  (next step: move them to the city freeze).
- **Same-fruit PO match with a check (25 Nov 10 AM, user)**: only **Swiggy Bangalore** (secret `fruit_match`
  {customer: [city word]}, default {Swiggy = ["Bangalore"]}): a PO line not matched by saved link / exact name to an
  indent item, whose name contains a fruit of the indent ("Bulk Semiripe Imported Avocado", "Unripe Avocado"), is
  put on that fruit's indent line (most shared words, then biggest qty; `indent_actions.same_fruit`), shown
  "🟡 same fruit · confirm" with a **Vs indent** column ("136 ≤ 186 ✓" / "⚠ 200 > 186") and a **Check** dropdown:
  **Confirm** (used, and the PO name is saved to PO_Item_Map so the same name matches by itself next time) or
  **Cancel** (kept as "not on indent"); the upload waits until every 🟡 line is checked. Any fruit of the indent
  (Avocado, Blueberry "Bulk PP Blueberry" → "1Box - Imported Blueberry", …). Other customers: names as before.
  **25 Nov 11:30**: the PO line may name only the variety ("Fuji 1 Pc") → the indent line of that variety; ties
  go to the same variety, then shared words, then the **qty closest to the PO qty** (`same_fruit(..., po_qty)`).
  Master 25 Nov: PTP Bangalore Swiggy "1Pc - Apple Fuji" (Fuji) and Trent "1Kg - Apple Red Delicious" (RD) added to
  All Cux City + New (filled, not yellow); IN-064 / IN-065 got Fuji 232 / 174 and IN-066 Apple RD 1000 kg (v2).
- **Batching plan + Actual dispatch = city level (25 Nov 11:30, user-approved preview; owners, trial)**
  (`core/batch_city.py`, `pages_src/batch_city.py`, tests `tests/test_batch_city.py`; the per-customer pages' code
  stays in `preprod_actual.render_plan` / `dispatch.render_dispatch`). **Batching plan** (`/batching-plan`): same date
  + city clubbing as Pre-production actual; per fruit row, one line per take-out option (boxes + fruit in them read
  only) with amber **MT / GT / Dump** boxes; Left = fruit − MT − GT − Dump; Save grading per row (blocked when Left
  < 0); editable any time, last row wins (tab **City_Grading**). Tiles + **End of day check** table (fruit taken =
  MT + GT + Dump + not graded; MT = dispatched + MT left; red when it doesn't balance or more was sent than MT).
  **Actual dispatch** (`/dispatch`, menu "Actual dispatch"): MT pool chips per fruit; pills per customer · delivery
  point · indent; one line per item: Asked (PO qty, else indent; not-on-PO left out, PO-only added), yellow
  Dispatch in the SKU's unit ("packs of 2 pcs", kg, punnets), = from MT, status Same / short / +extra. More than
  asked needs the **Send extra** tick, up to `dispatch_extra_pct` (default 10, number or {customer: pct,
  default}); at least +1 pack always allowed. More than the MT left is allowed but warned and red at day end.
  **Dispatch · lock** (are-you-sure popover) writes Dispatch_Lines (new cols club_key, per, from_mt, unit; Returns /
  invoice unchanged) and locks; **Unlock** (owner, reason) → tab **Dispatch_Locks**; the unlocked doc still counts
  until a new dispatch replaces it. Delivery Order PDF on the locked card. Returns from the day before
  (Return_Use) are not in the MT pool yet.
- SKU list check (24 Nov): All Cux City holds 470 names; every Combination 1 name is already in it
  (0 extra). 5 near-duplicate pairs (Zepto BLR avocado / kiwi ×2 / snacky apple; Swiggy Mumbai pink lady)
  wait for the user.

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
- `tests/`: pytest, **196 tests passing**. Run `python -m pytest -q` and `python -m pyflakes core pages_src app.py`.
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

- **24 Nov 9:50 AM (user: every click refreshed the whole page)**: the Create indent item area (attach, add form,
  item table, Submit / Update, dialogs) is ONE fragment `items._items_area`; adding an item reruns only it
  (`st.rerun(scope="fragment")`); it autosaves at its end. The New Mapping variety maps are cached
  (`masters._variety_maps`), not rebuilt from 4,862 Combination 1 rows on every rerun.

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
- On-screen labels stay short, with no explanations inside dropdowns (e.g. roles show as "Warehouse", "Sales", "Owner", "Creator").
- Keep the e-mail formats stable once agreed.
- Test before pushing: run pytest and pyflakes; check the live app after the redeploy.


### 27 Nov evening (TRIAL branch only): Option 2 end of day + balance cases

- Option 2 menu: Pre-Production Actual, Production Detail Process, **Production Summary** (tracker + Category
  efficiency), **Dispatch** (`/dispatch-2`) and **Returns** (`/returns-2`); `core/day_dispatch.py`,
  `pages_src/day_dispatch.py`, tabs `Day_Dispatch` / `Day_Returns` (create only, rounds add up). PO qty is final
  (indent qty until the PO); extra stock may be sent; billed never above the PO.
- The date picked on one Option 2 page is the date the next one opens on (`common.day_input`, session key
  `o2_day`). The Production tracker has an **Executive** column after Table #.
- **Balance cases from the 27 Nov end-to-end test** (user: "show me this list when I ask for the balance cases"):
  2. MT stock matched too loosely: every 1-piece avocado SKU shares one stock, every Gala 2PC SKU one stock
     (count / size ignored).
  3. (done 27 Nov night) gram packs are their own MT stock, in packs.
  4. Dispatch tile says "PO qty" even when the indent qty is used (no PO).
  5. A fully sent (locked) dispatch card hides what was sent (only inside "Send more" / Returns).
  7. Dispatch / Returns entry boxes are not amber as in the preview.
  8. A confirmed day does not stop dispatch or new lots; dispatch does not wait for the day to be confirmed.
  9. Returned stock is only recorded; it does not go back to MT / GT stock.
  Also open: test entries of 26 Nov Bangalore (Executive A / B, Brand A, IN-071 dispatch + returns) still on the
  trial sheet; no invoice PDF; box SKUs have no MT figure.

### 27 Nov night (TRIAL branch only; user voice note)

- **Blueberry**: goes by **brand name** (Brand name is required on Pre-Production Actual; country not needed); a
  tray is always **12 punnets = 1.5 kg** (`prod_actual.TRAY`; the master says "12 pcs tray"). Pcs/box shows 12.
- **Customer lots for fruit sold by weight** (no pieces per box, or Grapes / Blueberry / Litchi / Longan;
  `processed.lot_choices`, `GRAM_PACKS`): 100gm, 200gm, 250gm, 500gm, 750gm (+ 125gm punnet for Blueberry) and 1Kg;
  **no piece lots**. A gram pack is typed in **packs** (like the team's sheet: "0.250 kg" lot, D1 = packs);
  `pack_kg` unit 'Pack'; the label is "250gm" (old rows saved as "0.250 kg" still read). Dispatch: gram packs are
  their own MT stock in packs (`day_dispatch.pool_of`).
- **Pieces and packs are whole numbers** on Production Detail Process (MT packs, loose pcs of left-over / GT / dump).
- **Sum check limit is 102 %** (was 101 %; `processed.MAX_SUM`): up to 102 % saves, to be questioned later.
- **Lotting loss** on Production Summary → Category efficiency: kg and % of J, = J − (K + L + M) as the team's
  sheet column "Lotting gain vs loss" (+ loss, − gain); also a tile.
- Spec sizes are listed in count order (NZ Gala HG 110C was first in the list, not missing).
- **Orange** also has a **250gm** customer lot (with its piece lots; `processed.PIECE_GRAM`), typed in packs.
- **Box customer lot (27 Nov 10:20 PM, user)**: every item has a **1Box** customer lot = one box of that item's
  own box weight (dropdown shows "1Box · 9 kg"; `processed.pack_kg(..., box_kg)`, `is_box`), typed in **boxes**;
  for fruit graded and repacked as a box and sold as a box. GT / dump in pieces stay for piece fruit (not grapes).
  Dispatch: box SKUs ("1Box - …") draw from their own MT stock in boxes (`day_dispatch.pool_of`).
- **Submit rule (27 Nov 10:25 PM, user)** on Production Detail Process (`processed2.submit_block`): nothing below
  **95 %** of the kg used can be submitted; below **100 %** (even 98 %) a **comment** is required. Save (draft) is
  not held back. The day can't be confirmed while a saved item fails this. Items submitted before the rule stay.
