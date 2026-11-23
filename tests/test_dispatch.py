import pandas as pd

from core import dispatch as d


def test_check_labels():
    assert d.check(100, 100, 100, 10) == ("ok|Same", "ok|Matches")
    assert d.check(100, 120, 120, 10)[0] == "bad|+20 over limit"
    assert d.check(100, 105, 105, 10)[0] == "ok|+5 extra"
    assert d.check(38, 36, 36, 10)[0] == "warn|2 short"
    assert d.check(77, 82, 80, 10)[1] == "bad|+2 over batching"
    assert d.check(10, 10, None, 10)[1] == "neu|No batching"


def test_latest_doc_and_numbers():
    df = pd.DataFrame([
        {"indent_id": "IN-046", "doc_no": "DO-IN046-1", "customer_sku_name": "A", "dispatch_qty": "5", "saved_at": "t1"},
        {"indent_id": "IN-046", "doc_no": "DO-IN046-2", "customer_sku_name": "A", "dispatch_qty": "6", "saved_at": "t2"},
        {"indent_id": "IN-046", "doc_no": "DO-IN046-2", "customer_sku_name": "B", "dispatch_qty": "1", "saved_at": "t2"}])
    got = d.dispatched(df, "IN-046")
    assert got["doc_no"] == "DO-IN046-2" and set(got["items"]) == {"a", "b"} and got["items"]["a"]["dispatch_qty"] == "6"
    assert d.next_doc_no(df, "IN-046") == "DO-IN046-3"
    assert d.next_doc_no(df, "IN-047") == "DO-IN047-1"
    assert d.dispatched(df, "IN-047") == {}
    assert d.invoice_no("IN-046") == "INV-IN046"
