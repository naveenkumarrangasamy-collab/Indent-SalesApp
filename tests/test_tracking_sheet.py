import pandas as pd

from core import processed as pr
from core import tracking_sheet as ts


def _lots():
    return pd.DataFrame([
        {"entry_id": "L1", "production_date": "2026-11-25", "city": "B", "parent_sku": "Avocado", "origin": "Kenya",
         "variety": "Hass", "brand": "", "size": "18C", "box_kg": "4", "pcs_per_box": "18", "table_no": "3",
         "boxes_moved": "50", "stock_type": "Returns"},
        {"entry_id": "L2", "production_date": "2026-11-25", "city": "B", "parent_sku": "Apple", "origin": "Turkey",
         "variety": "Gala", "brand": "", "size": "120C", "box_kg": "17.5", "pcs_per_box": "120", "table_no": "1",
         "boxes_moved": "10", "stock_type": "MT Ready Leftover"}])


def test_build_like_g_sheet():
    lot = _lots().to_dict("records")[0]
    done = pd.DataFrame([pr.row(lot, "1PC", {"mt_packs": 700, "left_box": 2, "gt_box": 3, "dump_kg": 2},
                                "2026-11-25", "B")])
    rows = ts.build(_lots(), done)
    assert all(len(r) == len(ts.HEADERS) for r in rows)
    df = ts.frame(rows, "2026-11-25")
    avo = df[df["Parent SKU Name"] == "Avocado"].iloc[0]
    assert avo["Actual NW used for Production Kgs (J = H - I)"] == 192.0
    assert avo["Lotting gain vs loss (+ loss, - gain)"] == 22.44
    assert avo["Category Efficiency % (K / J)"] == "81%" and avo["Sum 0 Check"] == "88%"
    apple = df[df["Parent SKU Name"] == "Apple"].iloc[0]
    assert apple["Cux Lot"] == "" and apple["Table #"] == "1"       # not processed yet: second half blank
    assert ts.eff_rgb("81%")[0] > ts.eff_rgb("95%")[0]
