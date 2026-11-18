from core import fill_new

NEW = [["City", "Customer", "Parent SKU", "Customer SKU Name", "variety", "Spec-Repacking", "Spec-Size", "Spec-Origin"],
       ["PTP Bangalore", "Zepto", "Avocado", "1Pc - Avocado Hass Imported", "", "Punnet", "20C, 22C", "Tanzania"],
       ["PTP Hyderabad", "Zomato", "Avocado", "1PC - BH-Avocado Hass - Tanzania (150 - 200 gm)", "", "", "", ""],
       ["PTP Hyderabad", "Zomato", "Kiwi", "3PC - BH - Green Kiwi", "", "", "", ""]]
MW = [["City", "Customer", "Parent SKU", "Customer SKU Name", "Spec-Origin", "Spec-Size", "Active"],
      ["PTP Bangalore", "Zepto", "Avocado", "1Pc - Avocado Hass Imported", "Kenya", "18C", ""],
      ["PTP Bangalore", "Zepto", "Avocado", "1Pc - Avocado Hass Imported", "Tanzania", "20C, 22C", "Y"],
      ["PTP Bangalore", "Zepto", "Kiwi", "3Pc - Kiwi Green", "Iran", "33, 36", ""]]


def test_plan_takes_closest_and_active_first():
    p = {r["Customer SKU Name"]: r for r in fill_new.plan(NEW, MW)}
    av = p["1PC - BH-Avocado Hass - Tanzania (150 - 200 gm)"]
    assert av["Row"] == 3 and av["Reference (Mapping Whole)"] == "1Pc - Avocado Hass Imported"
    assert (av["Spec-Origin"], av["Spec-Size"], av["Spec-Repacking"]) == ("Tanzania", "20C, 22C", "Punnet")
    assert av["Other origins"] == "Kenya 18C"
    assert p["3PC - BH - Green Kiwi"]["Spec-Origin"] == "Iran"


def test_default_active_origin_when_no_active_column():
    new = [NEW[0], ["PTP Hyderabad", "Swiggy", "Mandarin", "3PC - Mandarin Orange", "", "", "", ""]]
    mw = [["City", "Customer", "Parent SKU", "Customer SKU Name", "Spec-Origin", "Spec-Size"],
          ["X", "Swiggy", "Mandarin", "3PC - Baby Orange (Mandarin)", "China", ""],
          ["X", "Swiggy", "Mandarin", "3PC - Baby Orange (Mandarin)", "RSA", ""]]
    p = fill_new.plan(new, mw)[0]
    assert p["Spec-Origin"] == "RSA" and p["Other origins"] == "China"
