"""Draft autosave to the Drafts tab (spec 5.5).

One draft row per user (draft_id = the user's email). The row is updated in
place and cleared (not deleted) after a submit, so row numbers stay stable
and the app can remember them without re-reading the tab before each save.
Please do not sort or delete rows in the Drafts tab while people are working.
"""
from __future__ import annotations

import json

from core import config
from core.schema import DRAFTS
from core.sheets import get_backend


def _find(email: str) -> tuple[int | None, dict | None, str]:
    df = get_backend().read(DRAFTS)
    m = df[df["draft_id"].str.lower() == email.lower()]
    if m.empty:
        return None, None, ""
    r = m.iloc[-1]
    payload = None
    if str(r["payload_json"]).strip():
        try:
            payload = json.loads(r["payload_json"])
        except json.JSONDecodeError:
            payload = None
    return int(r["_row"]), payload, r["updated_at"]


def load(email: str) -> tuple[int | None, dict | None, str]:
    """(row, payload or None, updated_at) for this user's draft."""
    return _find(email)


def save(email: str, payload: dict, row: int | None) -> tuple[int, str]:
    """Write the draft. Returns (row, updated_at)."""
    backend = get_backend()
    stamp = config.now_iso()
    values = {"draft_id": email, "user_email": email, "updated_at": stamp,
              "payload_json": json.dumps(payload, separators=(",", ":"), default=str)}
    if row is None:
        row, _, _ = _find(email)
    if row is None:
        row, _ = backend.append_dicts(DRAFTS, [values])
    else:
        backend.update_cells(DRAFTS, row, values)
    return row, stamp


def clear(email: str, row: int | None) -> None:
    if row is None:
        row, _, _ = _find(email)
    if row is not None:
        get_backend().update_cells(DRAFTS, row, {"draft_id": email, "user_email": email,
                                                 "updated_at": config.now_iso(), "payload_json": ""})
