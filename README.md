# MT Indent

Streamlit app for the MT Direct Sales team (Swiggy, Zomato, Zepto, Firstclub, Namdhari) to raise and correct sales-order indents. Every submitted indent and every correction is saved in Google Sheets, and a production sheet totals what has to be produced.

Built from `MT_INDENT_BUILD_SPEC.md`, with one change: users sign in with their **work email and a personal PIN** (4–6 digits) instead of Google/Microsoft sign-in.

## Screens

| Screen | Who | What |
|---|---|---|
| Sign in | everyone | Email + PIN. Users who are not in `Access` or are revoked are blocked. 5 wrong PINs lock the email for 15 min. |
| Home (opens first) | everyone | **Daily operations** for **Today or Tomorrow**: **Create indent** and **Upload PO** buttons at the top (Upload PO shows how many indents are waiting); tiles for stores placed, PO received, waiting for PO, not placed yet and qty; a progress bar; a **Status board** (one card per customer, a chip per store: grey not placed, amber placed and waiting for PO, green PO done, red deleted); a **City × Customer** table; and **Indents to act on** (cards with Edit / Delete / PO). Users see only their cities and stores. |
| Create indent | everyone | The delivery card is the heart of the page: delivery day, then **customer pills**, then **store pills** for that customer ("✓ placed" / "✓ PO done" on stores that already have an indent), then expected time. The items appear below once a store is chosen. Draft autosaves to the `Drafts` tab and is restored at the next sign-in. |
| Upload PO | everyone | Every indent the user can see, as cards: **waiting for PO first** (oldest delivery first, 🔴 when the delivery date has passed), then PO done with the PO file name, date and who uploaded it. Filter by Waiting / PO done / All, delivery date, city, customer, or search a store or indent number. **Items** shows the lines to check before uploading; **Upload PO** asks for the PDF, confirms customer and store, freezes the indent and e-mails the PDF. A PO can be uploaded after the 2 PM edit cutoff. |
| My indents (All indents for the owner) | everyone | List, open, correct (new version), last 10 versions with Load, change log, PO upload and freeze. |
| City / SKU report | everyone | Total qty per City → Customer → SKU with lot, lot size and Spec-Size; PDF and CSV. |
| Production sheet | everyone | **One row per city** where Parent SKU, Customer SKU name, Variety, Spec-Size, Lot and Lot size match, **clubbed across customers and stores** (Customers and Indents columns show what was added up); filter by delivery date, city, customer; PDF, CSV, and (owner) **Write to Google Sheet** which replaces the `Production_Sheet` tab. |
| Access | owner | Add users with an initial PIN, reset PINs, revoke/restore, change role, create missing tabs, SKU-mapping source and master-data checks. |

Every user can change their own PIN from the sidebar.

### Rules on the Indent screens

- **Phones**: every page works on a phone. Rows of items and indents turn into cards with full-width buttons, tiles go two per row, and the sidebar folds into the » menu.

- **Staying signed in**: after signing in, the browser keeps a signed cookie for 7 days (`session_days`), so a refresh or closing and reopening the tab returns to the same page without the PIN. **Sign out**, a PIN change/reset or revoking access ends it.
- **Google Sheet data** (SKUs, stores, varieties, access) is re-read every **5 minutes** (`master_refresh_minutes`), or at once with ↻ Refresh data.
- **Edit / Delete everywhere**: items on the Indent page, items in All indents, and whole indents (home screen and All indents). Deleting a whole indent marks it **Cancelled** (a new version): it leaves production, frees the store/date, and its history stays in the sheet.
- **Add item**: choosing a different parent SKU clears the SKU, variety, qty and price of that line; choosing a different SKU clears variety, qty and price.
- **PO e-mail**: on Confirm, the PO PDF is e-mailed to rakeshdhasa@gmail.com (`po_mail_to`, `po_mail_cc`) with the **customer name as the subject** and the indent details in the body. Needs `smtp_user` + `smtp_password` (a Gmail App password) in the secrets; without them the indent is still frozen and the app says the e-mail was not sent.
- **City and store access**: on the Access page each sales person can be given one or more **cities** and, optionally, specific **stores / facilities** (`Stores` column of the Access tab, separated by `;`). They see only those cities' customers and stores (only the listed stores when stores are given), place indents only there, and see, edit and delete every indent there, whoever created it. A sales person with neither sees only their own indents; owners see everything.
- **change_note** (Indent_Lines): every version's rows carry one note: *Created by …*, *Edited by … (same user / other user; created by …): what changed*, *Deleted by …*, *PO uploaded by …*.
- **Open indents first**: All indents, the home screen and "Indents included" list open (Submitted) indents on top, then PO-frozen, then deleted.
- **Upload PO** (home screen or All indents): PDF only, asks "Is this PO for customer X and store Y?", then freezes the indent. To keep the PDF itself, set `po_drive_folder_id` to a folder in a **Shared drive** shared with the service account as Content manager, and enable the Google Drive API; the link is saved in PO_Freeze. Without it only the file name is saved.

- **One indent per store per delivery date.** Choosing a store and date that already have an indent shows it, blocks Continue and offers **Edit IND-…** instead; a correction cannot be moved onto another indent's store and date either.
- **Delivery date** is **today (T) or tomorrow (T+1)** (`delivery_days_ahead`), and only days still open for edits are offered (after 2 PM today only tomorrow is shown); a correction may keep its saved date.
- **Expected delivery time**: 10:00 AM to 8:00 PM. Pick a 30-minute slot, or type a time in that range (6:45 PM, 18:45) and press Enter. Change with `delivery_from` / `delivery_to` in the secrets.
- **Qty** is a whole number only. **Lot** (Kg, Pcs, Pack for gm packs, Box, Tray) and **Lot size** (e.g. "2 Pcs", "200 gm", "17.5 Kg Box") come from the customer SKU name and cannot be edited; Lot size is also saved in Indent_Lines.
- **Variety** is asked only for **Apple** (`variety_parents` in the secrets). When the customer SKU name contains a variety it is **taken from the name and locked** (Royal Gala → Gala, Granny Smith, Queen, Red Delicious → RD, BH-Fuji → Fuji). Names without one (Apple Snacky, Daily Apple, Washington) keep the variety box editable. The list comes from the *Apple Varity* tab; while that tab is empty, the standard list is used (Gala, Granny Smith, Queen, RD, Pink Lady, Crispy Pink, Braeburn, Sonya, Fuji, Jazz).
- **All indents**: each item has **Edit** (qty, price, variety) and **Delete** buttons, both with a confirmation; each saves a new version and a Change_Log entry (within the edit window).
- **Submit / Update** opens a review box with everything entered (and, for corrections, the list of changes); nothing is saved until **Confirm**.
- **Removing an item, clearing the form or discarding changes** asks for confirmation first.
- **Edit window**: an indent can be corrected or deleted until **2:00 PM IST on its delivery date** (delivery 16 Nov → editable until 16 Nov 2:00 PM), whenever it was created. After that, Edit/Delete/Update are disabled and the save is refused. Change with `edit_cutoff_hour` (and `edit_cutoff_days`, days after the delivery date, default 0) in the secrets.
- **Spec-Size** (from *Mapping Whole*, the active origin's size) is a column on both production reports. Origin itself stays hidden. Set `show_spec = true` in the secrets to bring it back.
- If the app is **not connected to the Google Sheet** (secrets missing or wrong), every page shows a red banner with the exact reason.

### Where to see all indents and their edit history

In the Google Sheet (the owner also gets an **📄 Open Google Sheet** button in the sidebar):
- **Indent_Lines**: every submitted version of every indent, one row per item. Filter `indent_id`; the highest `version` is current.
- **Change_Log**: one row per change (who, when, from/to version, field, old → new). Filter `indent_id` for an indent's edit history.
- **PO_Freeze**: which PO froze which indent.
These tabs are created on the first submit (or with **Access → Create missing tabs**).

## Deploy on Streamlit Community Cloud

1. **Google service account** (one time)
   1. In [Google Cloud Console](https://console.cloud.google.com/), create a project (or use an existing one) and enable the **Google Sheets API**.
   2. Under *IAM & Admin → Service accounts*, create a service account, then *Keys → Add key → JSON*. Download the JSON file.
   3. Open the Google Sheet and **Share** it with the service account's `client_email` as **Editor**.
2. **Deploy**: on [share.streamlit.io](https://share.streamlit.io) choose *Create app → from GitHub*, pick this repo, branch `main`, main file `app.py`.
3. **Secrets**: in the app's *Settings → Secrets*, paste the contents of `.streamlit/secrets.toml.example`, then fill in:
   - `sheet_id`: already set to the team sheet.
   - `owner_email`: the indent owner's email. This email is always an active owner.
   - `owner_initial_pin`: a temporary PIN for the owner's first sign-in. The app then asks the owner to choose their own PIN.
   - `pin_pepper`: a long random string. Set it once and keep it; changing it makes every PIN invalid.
   - `gcp_service_account_json`: open the downloaded JSON key file in Notepad, copy everything from the first `{` to the last `}`, and paste it between the `'''` triple quotes. (A `[gcp_service_account]` section with one line per field also works.)
   - Keep the simple `name = value` lines at the top, before any `[section]` line.
4. **First sign-in as owner** → **Access → Sheet setup & checks**:
   1. **Create missing tabs**: adds `Store_Map`, `Varieties`, `Access`, `Indent_Lines`, `Change_Log`, `PO_Freeze`, `Drafts` (and `SKU_Map`) with header rows. Existing tabs are not touched.
   2. Check **SKU mapping** on the same page: it should say *live from 'All Cux City' + 'Mapping Whole'*.
   3. Stores come from the **Customer List** tab; add a row there for every new store.
   4. Add the sales users under **Users & PINs**, and share each PIN privately.

## Google Sheet tabs

The app reads columns **by header name**, ignoring case, spaces, `-` and `_`. Column order does not matter, and extra columns are ignored.

### SKU mapping (read live from the team's own tabs)

- **All Cux City** is the list of SKU names: City, Customer, Parent SKU, Classification, Customer SKU Name.
- **Apple varieties**: a tab named **Apple Variety** (or *Apple Varity* / *Apple Varieties*; any `<Parent> Variety` name) with one variety per row in its first column, or a column headed **Apple Variety** in All Cux City. A parent with varieties makes Variety required on page 3. If *Classification* holds a variety (different from the parent), it is pre-selected for that SKU.
- **Mapping Whole** gives origin and size per SKU name (Spec-Origin, Spec-Size). Its rows are matched to All Cux City by City + Customer + SKU name. SKU names that appear only in Mapping Whole are not offered, which avoids near-duplicate names.
- **Active origin**: by default Tanzania (Avocado), Peru (Blueberry) and RSA (Mandarin); a SKU with one origin row is active. To choose explicitly, add an **Active** column to Mapping Whole with `Y` on the origin being sourced.
- **Lot is fixed per SKU** and cannot be edited in the app. It comes from an optional **Lot** (or **UOM**) column in either tab, or else from the unit in the name (`1PC/2PC/3PC` → Pcs, `200gm` → gms, `1Kg` → Kg, `Box`, `Tray`). A SKU with neither cannot be added; the Access page lists any such SKUs.
- Rows need City, Customer, Parent SKU and Customer SKU Name to be used. The *Swiggy* tab has no City column, so it is not read; put Swiggy SKUs into All Cux City with their city.
- Edits in these tabs show in the app within a minute, or at once with **↻ Refresh data**.
- If the sheet has no *All Cux City* tab, the app uses an **SKU_Map** tab instead (City, Customer, Parent SKU, Customer SKU Name, Spec-Origin, Spec-Size, Active, Variety, Lot).

### Stores (read live from the team's own tab)

- **Customer List**: *City*, *Customer List* (the customer) and *Store names*. Page 2 offers the cities and customers found in the sheet (Customer List first, then All Cux City), in sheet order, and the stores of the chosen customer. The tab has no City column, so each store is offered for its customer in every city; add a **City** column if stores should be limited to a city.
- A **Store_Map** tab (City, Customer, Store Name), if present, is added to that list.

### Other tabs

- **Varieties**: Parent SKU, Variety. Optional extra varieties; a parent with varieties (today: Apple) makes variety required.
- **Access**: Email, Name, Role (`owner`/`sales`), Status (`active`/`revoked`), PIN_Hash, Updated_At, Updated_By, City, Stores. Manage it from the Access page. PINs are stored only as salted, peppered PBKDF2 hashes.
- **Indent_Lines, Change_Log, PO_Freeze**: append-only output, as in the spec. The current version of an indent is its highest `version`. Freezing appends one more version with `status = Frozen`.
- **Production_Sheet**: written by the owner from the Production page (Write to Google Sheet); replaced each time.
- **Drafts**: one row per user, updated in place. Please don't sort or delete rows in this tab while people are working.

## Live data and Google quotas

- Master tabs are re-read every 60 s (`master_cache_seconds` in secrets), or immediately with **↻ Refresh data** in the sidebar.
- Indent tabs are re-read every 15 s and right after each save.
- All users share the service account's quota (about 60 requests per minute per user; see Google's current limits). The app batches master reads into one call, writes each submit in one append, and saves qty/price edits at most every 15 s. If Google answers "busy", it retries with back-off, then shows a clear message. The draft is kept, and nothing is ever reported as submitted unless the write succeeded.
- Two people saving the same indent at the same moment: the second save is detected after writing, its rows are removed, and the user is asked to reopen the indent and re-apply their change.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Without `[gcp_service_account]` in `.streamlit/secrets.toml`, the app runs in **local mode**: data lives in CSV files under `data/`, seeded from `data/seed/` (a copy of the team's *All Cux City* and *Mapping Whole* tabs plus two demo stores per customer). To sign in locally, create `.streamlit/secrets.toml` with at least `owner_email` and `owner_initial_pin`.

Tests: `python -m pytest`.

## Decisions taken on the spec's open questions

| # | Question | What the app does now |
|---|---|---|
| 1 | Lot when the name has no unit word | Lot is fixed per SKU (Lot/UOM column or the unit in the name); a SKU with neither cannot be added. |
| 2 | Active origin | Optional `Active` column in Mapping Whole; defaults Tanzania / Peru / RSA. |
| 3 | Production sheet scope | Sales see the indents they created; the owner sees all. |
| 4 | Apple | Varieties and default variety read live from *All Cux City*. |
| 5 | Other cities/customers | The app shows "mapping pending" until SKU_Map/Store_Map have rows. |
| 6 | PO file storage | File name only, stored in PO_Freeze. |
| 7 | Hosting / sign-in | Streamlit Community Cloud; email + PIN. |
