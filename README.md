# MT Indent

Streamlit app for the MT Direct Sales team (Swiggy, Zomato, Zepto, Firstclub, Namdhari) to raise and correct sales-order indents. Every submitted indent and every correction is saved in Google Sheets, and a production sheet totals what has to be produced.

Built from `MT_INDENT_BUILD_SPEC.md`, with one change: users sign in with their **work email and a personal PIN** (4–6 digits) instead of Google/Microsoft sign-in.

## Screens

| Screen | Who | What |
|---|---|---|
| Sign in | everyone | Email + PIN. Users who are not in `Access` or are revoked are blocked. 5 wrong PINs lock the email for 15 min. |
| Indent | everyone | Step 1 delivery details, step 2 items. Draft autosaves to the `Drafts` tab and is restored at the next sign-in. |
| My indents (All indents for the owner) | everyone | List, open, correct (new version), last 10 versions with Load, change log, PO upload and freeze. |
| Production sheet | everyone | Totals by Parent SKU → Variety → Spec (active origin, size) → Lot for a delivery date and city, with CSV download. Sales see their own indents; the owner sees all. |
| Access | owner | Add users with an initial PIN, reset PINs, revoke/restore, change role, create missing tabs, SKU-mapping source and master-data checks. |

Every user can change their own PIN from the sidebar.

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
   - `[gcp_service_account]`: the fields from the JSON key. Keep the `\n` line breaks inside `private_key`.
4. **First sign-in as owner** → **Access → Sheet setup & checks**:
   1. **Create missing tabs**: adds `Store_Map`, `Varieties`, `Access`, `Indent_Lines`, `Change_Log`, `PO_Freeze`, `Drafts` (and `SKU_Map`) with header rows. Existing tabs are not touched.
   2. Check **SKU mapping** on the same page: it should say *live from 'All Cux City' + 'Mapping Whole'*.
   3. Stores come from the **Customer List** tab; add a row there for every new store.
   4. Add the sales users under **Users & PINs**, and share each PIN privately.

## Google Sheet tabs

The app reads columns **by header name**, ignoring case, spaces, `-` and `_`. Column order does not matter, and extra columns are ignored.

### SKU mapping (read live from the team's own tabs)

- **All Cux City** is the list of SKU names: City, Customer, Parent SKU, Classification, Customer SKU Name.
- **Apple varieties**: a column headed **Apple Variety** (any `<Parent> Variety` header works) lists the varieties the user chooses from, one per cell, anywhere down the column. A parent with varieties makes Variety required on page 3. If *Classification* holds a variety (different from the parent), it is pre-selected for that SKU.
- **Mapping Whole** gives origin and size per SKU name (Spec-Origin, Spec-Size). Its rows are matched to All Cux City by City + Customer + SKU name. SKU names that appear only in Mapping Whole are not offered, which avoids near-duplicate names.
- **Active origin**: by default Tanzania (Avocado), Peru (Blueberry) and RSA (Mandarin); a SKU with one origin row is active. To choose explicitly, add an **Active** column to Mapping Whole with `Y` on the origin being sourced.
- **Lot is fixed per SKU** and cannot be edited in the app. It comes from an optional **Lot** (or **UOM**) column in either tab, or else from the unit in the name (`1PC/2PC/3PC` → Pcs, `200gm` → gms, `1Kg` → Kg, `Box`, `Tray`). A SKU with neither cannot be added; the Access page lists any such SKUs.
- Rows need City, Customer, Parent SKU and Customer SKU Name to be used. The *Swiggy* tab has no City column, so it is not read; put Swiggy SKUs into All Cux City with their city.
- Edits in these tabs show in the app within a minute, or at once with **↻ Refresh data**.
- If the sheet has no *All Cux City* tab, the app uses an **SKU_Map** tab instead (City, Customer, Parent SKU, Customer SKU Name, Spec-Origin, Spec-Size, Active, Variety, Lot).

### Stores (read live from the team's own tab)

- **Customer List**: *Customer List* (the customer) and *Store names*. Page 2 lists the stores of the chosen customer, in sheet order. The tab has no City column, so each store is offered for its customer in every city; add a **City** column if stores should be limited to a city.
- A **Store_Map** tab (City, Customer, Store Name), if present, is added to that list.

### Other tabs

- **Varieties**: Parent SKU, Variety. Optional extra varieties; a parent with varieties (today: Apple) makes variety required.
- **Access**: Email, Name, Role (`owner`/`sales`), Status (`active`/`revoked`), PIN_Hash, Updated_At, Updated_By. Manage it from the Access page. PINs are stored only as salted, peppered PBKDF2 hashes.
- **Indent_Lines, Change_Log, PO_Freeze**: append-only output, as in the spec. The current version of an indent is its highest `version`. Freezing appends one more version with `status = Frozen`.
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
