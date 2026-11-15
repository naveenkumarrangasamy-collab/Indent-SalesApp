"""Recipients, report files, hourly e-mail and SO e-mail (local back end, fake SMTP)."""
from datetime import timedelta

import pandas as pd
import pytest

from core import config, hourly, indents, mailer, recipients, reports
from core.models import IndentHeader, IndentLine
from core.recipients import Recipient
from core.sheets import LocalBackend

TODAY = config.now_ist().date().isoformat()
HASS = IndentLine("Avocado", "1PC - Hass Avocado Imported", "", "Pcs", 30, 120)
KIWI = IndentLine("Kiwi", "2PC - Green Kiwi", "", "Pcs", 5, 50)


@pytest.fixture
def env(tmp_path, monkeypatch):
    b = LocalBackend(tmp_path)
    b.ensure_tabs()
    for mod in (indents, recipients):
        monkeypatch.setattr(mod, "get_backend", lambda: b)
    sent = []
    monkeypatch.setattr(mailer, "deliver", lambda msg: (sent.append(msg) or (True, "ok")))
    monkeypatch.setattr(indents, "date_allowed", lambda *a, **k: True)
    monkeypatch.setattr(indents, "can_edit", lambda *a, **k: True)
    from tests.test_indents_flow import _masters
    monkeypatch.setattr(hourly.masters, "load_masters", _masters)
    return b, sent


def _hdr(store, customer="Zepto", city="Bangalore"):
    return IndentHeader(TODAY, city, customer, store, "10:30")


def test_two_lists_city_only_and_po_list_gets_everything(env):
    recipients.upsert(Recipient("G@x.com", "Ground A", "Ground", hourly=True, cities=["Bangalore"],
                                customers=["Zepto"]), by="o")
    recipients.upsert(Recipient("c@x.com", "Central", "Central", so=True, customers=["Zepto"]), by="o")
    recipients.upsert(Recipient("g@x.com", "Ground A2", "Ground", hourly=True, cities=["Bangalore"]), by="o")
    recipients.upsert(Recipient("g@x.com", "Same person", "Central", so=True), by="o")   # in both lists
    assert [r.email for r in recipients.ground()] == ["g@x.com"]                # same address+team updated
    g = recipients.ground()[0]
    assert g.name == "Ground A2" and g.cities == ["Bangalore"] and g.customers == []
    assert g.sees("bangalore", "Swiggy", "x") and not g.sees("Chennai", "Zepto", "x")
    # PO e-mails: every address gets every PO, whatever city / customer
    assert [r.email for r in recipients.so_list("Chennai", "Swiggy", "S")] == ["c@x.com", "g@x.com"]
    assert recipients.remove("g@x.com", "Central")
    assert [r.email for r in recipients.central()] == ["c@x.com"] and recipients.ground()


def test_hourly_production_mail_per_scope_pdf_excel_and_no_repeat(env):
    b, sent = env
    indents.submit_new(_hdr("Store A"), [HASS, KIWI], "s@x.com")
    indents.submit_new(_hdr("Store S", "Swiggy"), [HASS], "s@x.com")
    indents.submit_new(_hdr("Store C", city="Chennai"), [HASS], "s@x.com")
    recipients.upsert(Recipient("z@x.com", "Bangalore team", hourly=True, cities=["Bangalore"]), by="o")
    recipients.upsert(Recipient("all@x.com", "Everyone", hourly=True), by="o")
    at9 = config.now_ist().replace(hour=9, minute=2)
    res = hourly.run(now=at9)
    assert [r["status"] for r in res] == ["sent", "sent"]
    by_to = {m["To"]: m for m in sent}
    z = by_to["z@x.com"]
    names = sorted(p.get_filename() for p in z.iter_attachments())
    assert len(names) == 2 and names[0].startswith("Production_") and names[0].endswith(".pdf") \
        and names[1].endswith(".xlsx")
    body = z.get_body(("html",)).get_content()
    assert "Production sheet" in body and "Customer-level" not in body and "Chennai" not in body
    assert z["Subject"].startswith("Production ") and "2 indent" in z["Subject"]      # Bangalore only
    assert "3 indent" in by_to["all@x.com"]["Subject"] and "Chennai" in by_to["all@x.com"].get_body(("html",)).get_content()
    # same hour again: nothing new; outside the window: skipped
    assert {r["status"] for r in hourly.run(now=at9.replace(minute=40))} == {"skipped"}
    assert hourly.run(now=at9.replace(hour=19))[0]["status"] == "skipped"
    assert len(sent) == 2
    log = recipients.read_log()
    assert set(log["kind"]) == {"hourly"} and set(log["status"]) == {"sent"}
    ok, msg = hourly.send_sample("me@x.com")
    assert ok and sent[-1]["To"] == "me@x.com" and sent[-1]["Subject"].startswith("[SAMPLE] Production")


def test_hourly_slot_window():
    now = config.now_ist().replace(minute=5)
    assert hourly.slot_for(now.replace(hour=8)).hour == 8
    assert hourly.slot_for(now.replace(hour=14)).hour == 14
    assert hourly.slot_for(now.replace(hour=15, minute=20)).hour == 14   # late scheduled run
    assert hourly.slot_for(now.replace(hour=7)) is None
    assert hourly.slot_for(now.replace(hour=16)) is None


def test_reports_overall_clubs_customers_and_customer_level_keeps_stores(env):
    indents.submit_new(_hdr("Store A"), [HASS], "s@x.com")
    indents.submit_new(_hdr("Store S", "Swiggy"), [HASS, KIWI], "s@x.com")
    rows = reports.day_rows(indents.read_lines(fresh=True), TODAY)
    from tests.test_indents_flow import _masters
    o = reports.overall_df(rows, _masters())
    assert "Customer SKU Name" not in o.columns and "Customers" not in o.columns
    assert o[o["Parent SKU"] == "Avocado"]["Total Qty"].sum() == 60   # (split only where the spec differs)
    c = reports.customer_df(rows)
    assert list(c["Customer"].unique()) == ["Swiggy", "Zepto"] and set(c["Status"]) == {"Waiting for PO"}
    files = reports.production_mail_files(rows, _masters(), [], TODAY, "9:00 AM")
    assert [d[:4] for _, d, _ in files] == [b"%PDF", b"PK\x03\x04"]


def test_state_at_shows_each_hour(env):
    iid = indents.submit_new(_hdr("Store A"), [HASS], "s@x.com")
    df = indents.read_lines(fresh=True)
    t1 = pd.Timestamp(df["submitted_at"].iloc[0]).to_pydatetime()
    indents.submit_update(iid, 1, _hdr("Store A"), [IndentLine(**{**HASS.to_dict(), "qty": 45})], "s@x.com")
    df = indents.read_lines(fresh=True)
    assert reports.state_at(df, t1 - timedelta(seconds=1)).empty            # not created yet
    assert reports.state_at(df, t1 + timedelta(microseconds=1))["qty"].sum() in (30, 45)
    assert reports.state_at(df, config.now_ist() + timedelta(seconds=1))["qty"].sum() == 45


def test_so_mail_goes_to_central_team_in_scope(env):
    b, sent = env
    iid = indents.submit_new(_hdr("Store A"), [HASS], "s@x.com")
    recipients.upsert(Recipient("c@x.com", team="Central", so=True), by="o")
    recipients.upsert(Recipient("other@x.com", team="Central", so=True, cities=["Chennai"]), by="o")
    v = indents.freeze(iid, 1, "po.pdf", "s@x.com", po_qty={HASS.customer_sku_name: 30}, po_number="77")
    cur = indents.snapshot(indents.read_lines(fresh=True), iid)
    assert cur.version == v
    ok, msg = mailer.send_so_mail(cur, "po.pdf", b"%PDF-1.4 test", "s@x.com", po_number="77")
    assert ok and "c@x.com" in msg and "other@x.com" in msg          # every PO to everyone on the list
    m = sent[-1]
    assert m["Subject"].startswith("Zepto - SO placed - Store A") and "PO 77" in m["Subject"]
    assert sorted(p.get_filename() for p in m.iter_attachments()) == sorted(
        ["po.pdf", f"SO_{iid}.pdf", f"SO_{iid}.xlsx"])
    ok, _ = mailer.send_so_mail(cur, "", b"", "s@x.com", po_number="SAMPLE", to_override=["me@x.com"], sample=True)
    assert ok and sent[-1]["To"] == "me@x.com" and sent[-1]["Subject"].startswith("[SAMPLE] Zepto")
