import pandas as pd

from core import auth, importer
from core.schema import ACCESS, TABS
from core.sheets import LocalBackend, frame_from_values


def test_pin_hash_roundtrip():
    h = auth.hash_pin("4821", pepper="p")
    assert h.startswith("pbkdf2_sha256$") and "4821" not in h
    assert auth.verify_pin("4821", h, pepper="p")
    assert not auth.verify_pin("4822", h, pepper="p")
    assert not auth.verify_pin("4821", h, pepper="other")  # pepper matters
    assert not auth.verify_pin("4821", "garbage")
    assert auth.hash_pin("4821", pepper="p") != h  # salted


def test_pin_and_email_rules():
    assert auth.valid_pin("1234") and auth.valid_pin("123456")
    assert not auth.valid_pin("123") and not auth.valid_pin("1234567") and not auth.valid_pin("12a4")
    assert auth.valid_email(" Name@Ninjacart.com ")
    assert not auth.valid_email("name@")


def _access(rows):
    return pd.DataFrame(rows, columns=TABS[ACCESS])


def test_authenticate_blocks_unknown_revoked_and_wrong_pin(monkeypatch):
    monkeypatch.setattr(auth.config, "pin_pepper", lambda: "p")
    monkeypatch.setattr(auth.config, "owner_email", lambda: "owner@x.com")
    h = auth.hash_pin("1111", pepper="p")
    acc = _access([["sales@x.com", "S", "sales", "active", h, "", ""],
                   ["gone@x.com", "G", "sales", "revoked", h, "", ""]])
    ok = auth.authenticate(acc, "Sales@X.com", "1111")
    assert ok.user and ok.user.role == "sales" and not ok.user.is_owner
    assert "Access is not granted for nobody@x.com" in auth.authenticate(acc, "nobody@x.com", "1111").message
    assert auth.authenticate(acc, "gone@x.com", "1111").user is None
    assert auth.authenticate(acc, "sales@x.com", "2222").message == "Incorrect PIN."


def test_lockout_after_five_failures(monkeypatch):
    monkeypatch.setattr(auth.config, "pin_pepper", lambda: "p")
    acc = _access([["lock@x.com", "L", "sales", "active", auth.hash_pin("1111", pepper="p"), "", ""]])
    for _ in range(5):
        auth.authenticate(acc, "lock@x.com", "0000")
    res = auth.authenticate(acc, "lock@x.com", "1111")
    assert res.user is None and "Too many" in res.message


def test_owner_from_secrets_and_initial_pin(monkeypatch):
    monkeypatch.setattr(auth.config, "owner_email", lambda: "owner@x.com")
    monkeypatch.setattr(auth.config, "owner_initial_pin", lambda: "9999")
    res = auth.authenticate(_access([]), "owner@x.com", "9999")
    assert res.user.is_owner and res.used_initial_pin
    assert auth.authenticate(_access([]), "owner@x.com", "1234").user is None
    # owner cannot be locked out by a revoked row
    revoked = _access([["owner@x.com", "O", "sales", "revoked", "", "", ""]])
    assert auth.resolve_user(revoked, "owner@x.com").is_owner


def test_headers_matched_by_name_not_position():
    values = [["Customer SKU Name", "city", "Parent_SKU", "", "customer", "Spec - Origin", "Extra"],
              ["1PC - X", "Bangalore", "Avocado", "junk", "Zepto", "Peru", "e"],
              ["", "", "", "", "", "", ""]]
    df = frame_from_values("SKU_Map", values)
    assert len(df) == 1
    r = df.iloc[0]
    assert (r["City"], r["Customer"], r["Parent SKU"], r["Spec-Origin"]) == ("Bangalore", "Zepto", "Avocado", "Peru")
    assert r["Active"] == "" and r["_row"] == 2


def test_local_backend_append_respects_sheet_column_order(tmp_path):
    b = LocalBackend(tmp_path)
    (tmp_path / "Access.csv").write_text("Status,Email,Role\n")
    b.append_dicts("Access", [{"Email": "a@x.com", "Role": "sales", "Status": "active", "Name": "A"}])
    lines = (tmp_path / "Access.csv").read_text().splitlines()
    assert lines[0].startswith("Status,Email,Role,Name")  # missing columns appended to header
    assert lines[1].startswith("active,a@x.com,sales,A")
    df = b.read("Access")
    b.update_cells("Access", int(df.iloc[0]["_row"]), {"Status": "revoked"})
    assert b.read("Access").iloc[0]["Status"] == "revoked"


MW = [["City", "Customer", "Parent SKU", "Customer SKU Name", "Spec-Origin", "Spec-Size", "Box Kgs"],
      ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Tanzania", "20C", "4Kg"],
      ["Bangalore", "Zepto", "Avocado", "1PC - Hass Avocado Imported", "Kenya", "20C", ""],
      ["Bangalore", "Zepto", "Mandarin", "3PC - Baby Orange Imported", "China", "60", ""],
      ["Bangalore", "Zepto", "Mandarin", "3PC - Baby Orange Imported", "RSA", "2C", ""],
      ["Bangalore", "Zepto", "Apple", "2PC - Snacky Apple", "", "", ""],
      ["", "", "Apple", "2PC", "", "", ""]]
AC = [["City", "Customer", "Parent SKU", "Classification", "Customer SKU Name", "", "x"],
      ["Bangalore", "Zepto", "Avocado", "Avocado", "1PC - Hass Avocado Imported", "", ""],
      ["Bangalore", "Zepto", "Mandarin", "Mandarin", "3PC - Baby Orange Imported", "", ""],
      ["Bangalore", "Zepto", "Apple", "Gala", "2PC - Apple Royal Gala Imported", "", "Gala"],
      ["", "", "", "Fuji", "", "", "Fuji"],
      ["Bangalore", "Zepto", "Kiwi", "Kiwi", "2PC - Snacky Kiwi", "", ""],
      ["Bangalore", "Zepto", "Kiwi", "Kiwi", "2PC  - Snacky Kiwi", "", ""],
      ["", "", "", "", "", "", ""],
      ["", "", "", "Stray", "", "", ""]]


def test_names_come_from_all_cux_city_with_specs_from_mapping_whole():
    rows = importer.build_sku_map(MW, AC)
    by = {(r["Customer SKU Name"], r["Spec-Origin"]): r for r in rows}
    assert by[("1PC - Hass Avocado Imported", "Tanzania")]["Active"] == "Y"
    assert by[("1PC - Hass Avocado Imported", "Kenya")]["Active"] == "N"
    assert by[("3PC - Baby Orange Imported", "RSA")]["Active"] == "Y"
    assert by[("3PC - Baby Orange Imported", "China")]["Active"] == "N"
    assert by[("2PC - Apple Royal Gala Imported", "")]["Variety"] == "Gala"
    assert by[("2PC - Apple Royal Gala Imported", "")]["Active"] == "Y"
    assert sum(1 for r in rows if "Snacky Kiwi" in r["Customer SKU Name"]) == 1  # de-duplicated
    # Names only in Mapping Whole are not added (avoids near-duplicates)
    assert not any(r["Customer SKU Name"] == "2PC - Snacky Apple" for r in rows)
    assert not any(r["Customer SKU Name"] == "2PC" for r in rows)
    var = importer.build_varieties(AC)
    assert var == [{"Parent SKU": "Apple", "Variety": "Gala"}, {"Parent SKU": "Apple", "Variety": "Fuji"}]


def test_mapping_whole_used_when_all_cux_city_is_empty():
    rows = importer.build_sku_map(MW, [])
    assert {r["Customer SKU Name"] for r in rows} == {
        "1PC - Hass Avocado Imported", "3PC - Baby Orange Imported", "2PC - Snacky Apple"}


def test_optional_lot_and_active_columns():
    mw = [["City", "Customer", "Parent SKU", "Customer SKU Name", "Spec-Origin", "Spec-Size", "Active"],
          ["Bangalore", "Zepto", "Avocado", "Avocado Loose", "Kenya", "20C", "Y"],
          ["Bangalore", "Zepto", "Avocado", "Avocado Loose", "Tanzania", "20C", ""]]
    ac = [["City", "Customer", "Parent SKU", "Classification", "Customer SKU Name", "UOM"],
          ["Bangalore", "Zepto", "Avocado", "Avocado", "Avocado Loose", "kg"]]
    rows = importer.build_sku_map(mw, ac)
    assert {r["Spec-Origin"]: r["Active"] for r in rows} == {"Kenya": "Y", "Tanzania": "N"}
    assert {r["Lot"] for r in rows} == {"Kg"}


def test_masters_built_live_and_lot_is_fixed():
    from core.masters import frames_from_values, masters_from_frames

    raw = {"All Cux City": AC + [["Bangalore", "Zepto", "Litchi", "Litchi", "200gm - Litchi Imported (Longan)"],
                                 ["Bangalore", "Zepto", "Apple", "Gala", "Apple Royal Gala - PTP STD Lot"]],
           "Mapping Whole": MW}
    frames, source = frames_from_values(raw)
    m = masters_from_frames(frames, source)
    assert source.startswith("live")
    assert m.parents("Bangalore", "Zepto") == ["Apple", "Avocado", "Kiwi", "Litchi", "Mandarin"]
    assert m.spec("Bangalore", "Zepto", "1PC - Hass Avocado Imported") == ("Tanzania", "20C")
    assert m.lot_for("Bangalore", "Zepto", "200gm - Litchi Imported (Longan)") == "gms"
    assert m.lot_for("Bangalore", "Zepto", "1PC - Hass Avocado Imported") == "Pcs"
    assert m.lot_for("Bangalore", "Zepto", "Apple Royal Gala - PTP STD Lot") == ""  # no unit, no Lot column
    assert m.varieties_for("Apple") == ["Gala", "Fuji"]


def test_sku_map_tab_used_without_legacy_tabs():
    from core.masters import frames_from_values

    raw = {"SKU_Map": [["City", "Customer", "Parent SKU", "Customer SKU Name", "Lot"],
                       ["Pune", "Zepto", "Onion", "Onion loose", "Kg"]]}
    frames, source = frames_from_values(raw)
    assert source == "SKU_Map tab" and frames["SKU_Map"].iloc[0]["Lot"] == "Kg"


CL = [["Customer List", "Store names"],
      ["Zepto", "Zepto - Yalachanayakanapura"], ["Zepto", "Zepto - Cholappanahalli"],
      ["Swiggy", "Swiggy WH1"], ["Zomato", "ZOMATO HYPERPURE PVT Ltd"], ["", ""],
      ["Firstclub", "FIRST CLUB PTP BLR"], ["Zepto", "Zepto - Cholappanahalli"]]


def test_stores_from_customer_list_any_city():
    from core.masters import frames_from_values, masters_from_frames

    assert len(importer.build_store_map(CL)) == 5
    raw = {"All Cux City": AC, "Mapping Whole": MW, "Customer List": CL,
           "Store_Map": [["City", "Customer", "Store Name"], ["Pune", "Zepto", "Zepto - Pune DS"]]}
    m = masters_from_frames(*frames_from_values(raw))
    assert m.stores_for("Bangalore", "Zepto") == ["Zepto - Yalachanayakanapura", "Zepto - Cholappanahalli"]
    assert m.stores_for("Pune", "zepto") == ["Zepto - Yalachanayakanapura", "Zepto - Cholappanahalli",
                                             "Zepto - Pune DS"]
    assert m.stores_for("Bangalore", "Namdhari") == []
    assert m.stores_for("Bangalore", "Firstclub") == ["FIRST CLUB PTP BLR"]


def test_customer_list_with_city_column():
    rows = importer.build_store_map([["City", "Customer List", "Store names"], ["Chennai", "Zepto", "Zepto - Chennai"]])
    assert rows == [{"City": "Chennai", "Customer": "Zepto", "Store Name": "Zepto - Chennai"}]


def test_variety_column_with_parent_header():
    ac = [["City", "Customer", "Parent SKU", "Classification", "Customer SKU Name", "", "Apple Variety"],
          ["PTP Bangalore", "Zepto", "Kiwi", "Kiwi", "2PC - Green Kiwi", "", "Gala"],
          ["PTP Bangalore", "Zepto", "Apple", "Apple", "2PC - Apple Queen Imported", "", "Gala"],
          ["", "", "", "", "", "", "Queen"],
          ["", "", "", "", "", "", "Fuji"]]
    assert importer.build_varieties(ac) == [{"Parent SKU": "Apple", "Variety": v} for v in ("Gala", "Queen", "Fuji")]
    rows = importer.build_sku_map([], ac)
    assert all(r["Variety"] == "" for r in rows)  # Classification == parent: user picks the variety
    headerless = [r[:6] + [""] for r in [ac[0][:6]] + ac[1:]]
    assert importer.build_varieties(headerless) == []
