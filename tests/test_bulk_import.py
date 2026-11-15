"""Owner import: many indents from one Excel sheet."""
import io
from datetime import timedelta

import openpyxl
import pytest

from core import bulk_import, config, importer, indents
from core.masters import frames_from_values, masters_from_frames
from core.sheets import LocalBackend

DAY = config.now_ist().date() + timedelta(days=1)
HEAD = ["Delivery date", "City", "Customer", "Store / delivery point", "Parent SKU",
        "Item (pack size - name)", "Item code / EAN", "Pack size / UOM", "Lot", "Qty",
        "Rate (Rs per lot)", "Amount (Rs)"]


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "All indents"
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    ws.append([None, None, None, None, None, None, None, None, "Total", "=SUM(J2:J9)"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [
    [DAY, "PTP Bangalore", "Zepto", "Zepto - Yalachanayakanapura", "Avocado", "1Pc - Hass Avocado Imported",
     "1", "1 Piece", "Pcs", 109, None, None],
    [DAY, "PTP Bangalore", "Zepto", "Zepto - Yalachanayakanapura", "Grapes", "250gm - Grapes Red Globe",
     "2", "250 Gram", "Pack", 53, None, None],
    [DAY, "Bangalore", "Namdhari", "Namdhari (store not given)", "Mandarin", "1Tray - Mandarin 80 count",
     None, "Tray", "Tray", 100, 2100, None],
    [DAY, "Bangalore", "Namdhari", "Namdhari (store not given)", "Apple", "1Box - Green apple",
     None, "Box", "Box", 10, 4700, None],
    [DAY, "PTP Bangalore", "Swiggy", "swiggy wh1", "Kiwi", "1Pc - Green Kiwi", None, "", "Pcs", 0, None, None],
]

RAW = {
    "All Cux City": [["City", "Customer", "Parent SKU", "Classification", "Customer SKU Name"],
                     ["PTP Bangalore", "Zepto", "Avocado", "Avocado", "1PC - Hass Avocado Imported"]],
    "Customer List": [["Customer List", "Store names"],
                      ["Zepto", "Zepto - Yalachanayakanapura"], ["Swiggy", "Swiggy WH1"]],
}


@pytest.fixture
def backend(tmp_path, monkeypatch):
    b = LocalBackend(tmp_path)
    b.ensure_tabs()
    for tab, values in RAW.items():
        b._create_tab(tab, values[0])
        b._append_raw(tab, values[1:])
    monkeypatch.setattr(indents, "get_backend", lambda: b)
    return b


def _masters(b):
    return masters_from_frames(*frames_from_values(b.read_values_many(
        ["SKU_Map", "Store_Map", "Varieties", "Access", "All Cux City", "Customer List"])))


def test_read_rows_skips_totals_and_maps_headers():
    rows = bulk_import.read_rows(_xlsx(ROWS))
    assert len(rows) == 5
    assert rows.iloc[0]["item"] == "1Pc - Hass Avocado Imported" and rows.iloc[0]["qty"] == 109
    assert rows.iloc[2]["price"] == 2100 and rows.iloc[0]["delivery_date"] == DAY.isoformat()


def test_bad_file_says_which_columns():
    with pytest.raises(bulk_import.ImportFileError, match="Could not read"):
        bulk_import.read_rows(b"not an excel file")
    wb = openpyxl.Workbook()
    wb.active.append(["Customer", "Qty"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(bulk_import.ImportFileError, match="Store"):
        bulk_import.read_rows(buf.getvalue())


def test_plan_groups_price_and_master_gaps(backend):
    m = _masters(backend)
    groups = bulk_import.plan(bulk_import.read_rows(_xlsx(ROWS)), m, city="PTP Bangalore", price=1)
    assert [(g.header.customer, g.header.store, len(g.lines)) for g in groups] == [
        ("Zepto", "Zepto - Yalachanayakanapura", 2), ("Namdhari", "Namdhari (store not given)", 2),
        ("Swiggy", "Swiggy WH1", 0)]
    zepto, namdhari, swiggy = groups
    assert zepto.lines[0].customer_sku_name == "1PC - Hass Avocado Imported"   # master spelling
    assert [x.lot for x in namdhari.lines] == ["Tray", "Box"]
    assert all(x.price == 1 for g in groups for x in g.lines)
    assert not zepto.new_store and namdhari.new_store and swiggy.errors        # qty 0 only
    skus, stores = bulk_import.master_additions(groups)
    assert [s["Customer SKU Name"] for s in skus] == ["250gm - Grapes Red Globe", "1Tray - Mandarin 80 count",
                                                      "1Box - Green apple"]
    assert stores == [{"City": "PTP Bangalore", "Customer": "Namdhari", "Store Name": "Namdhari (store not given)"}]
    file_price = bulk_import.plan(bulk_import.read_rows(_xlsx(ROWS)), m, city="PTP Bangalore", price=None)
    assert file_price[0].errors and file_price[1].lines[0].price == 2100     # Zepto has no price in the file


def test_add_to_master_then_create(backend):
    rows = bulk_import.read_rows(_xlsx(ROWS))
    groups = bulk_import.plan(rows, _masters(backend), city="PTP Bangalore", price=1)
    notes = bulk_import.add_to_master(backend, *bulk_import.master_additions(groups))
    assert notes == ["3 SKU names added to 'All Cux City'", "1 stores added to 'Customer List'"]
    assert backend.read_values(importer.CUSTOMER_LIST)[-1] == ["Namdhari", "Namdhari (store not given)"]
    m = _masters(backend)
    assert m.stores_for("PTP Bangalore", "Namdhari") == ["Namdhari (store not given)"]
    assert m.lot_for("PTP Bangalore", "Namdhari", "1Tray - Mandarin 80 count") == "Tray"
    groups = bulk_import.plan(rows, m, city="PTP Bangalore", price=1)
    assert bulk_import.master_additions(groups) == ([], [])
    ids = [indents.submit_new(g.header, g.lines, "o@x.com") for g in groups if not g.errors]
    assert ids == ["IN-001", "IN-002"]
    df = indents.read_lines(fresh=True)
    assert indents.find_duplicate(df, groups[0].header) == "IN-001"
