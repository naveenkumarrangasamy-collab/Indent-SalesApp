"""E-mail recipients (Mail_Recipients tab) and the e-mail log (Mail_Log tab).

Each recipient has a team (Ground / Central), which e-mails they get
(hourly indent e-mail, SO / PO e-mail) and a scope: the cities, customers and
stores they look after. An empty scope field means "all". A recipient only
ever sees indents inside their scope.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from core import config
from core.schema import MAIL_LOG, MAIL_RECIPIENTS
from core.sheets import get_backend

TEAMS = ["Ground", "Central"]


def _split(v) -> list[str]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    return [x.strip() for x in str(v).replace("\n", ";").split(";") if x.strip()]


def _yes(v) -> bool:
    return str(v or "").strip().lower() in ("y", "yes", "true", "1", "on")


def _norm(v: str) -> str:
    return " ".join(str(v or "").split()).casefold()


@dataclass
class Recipient:
    email: str
    name: str = ""
    team: str = "Ground"
    hourly: bool = False
    so: bool = False
    cities: list[str] = field(default_factory=list)
    customers: list[str] = field(default_factory=list)
    stores: list[str] = field(default_factory=list)
    active: bool = True

    def sees(self, city: str, customer: str, store: str) -> bool:
        """Inside this recipient's scope (empty field = everything)."""
        def ok(values, v):
            return not values or _norm(v) in {_norm(x) for x in values}
        return ok(self.cities, city) and ok(self.customers, customer) and ok(self.stores, store)

    def filter(self, rows: pd.DataFrame) -> pd.DataFrame:
        if rows is None or rows.empty:
            return rows
        keep = [self.sees(r.city, r.customer, r.store) for r in rows.itertuples()]
        return rows[keep]

    def scope_text(self) -> str:
        parts = [("cities", self.cities), ("customers", self.customers), ("stores", self.stores)]
        txt = "; ".join(f"{k}: {', '.join(v)}" for k, v in parts if v)
        return txt or "everything"


def read_all() -> list[Recipient]:
    df = get_backend().read(MAIL_RECIPIENTS)
    out = []
    for r in df.to_dict("records"):
        email = str(r.get("Email", "") or "").strip().lower()
        if not email:
            continue
        out.append(Recipient(
            email=email, name=str(r.get("Name", "") or "").strip(),
            team=str(r.get("Team", "") or "Ground").strip().title() or "Ground",
            hourly=_yes(r.get("Hourly_Indent")), so=_yes(r.get("SO_PO")),
            cities=_split(r.get("Cities")), customers=_split(r.get("Customers")),
            stores=_split(r.get("Stores")),
            active=str(r.get("Active", "Y") or "Y").strip().lower() not in ("n", "no", "false", "0")))
    return out


def hourly_list() -> list[Recipient]:
    return [r for r in read_all() if r.active and r.hourly]


def so_list(city: str, customer: str, store: str) -> list[Recipient]:
    return [r for r in read_all() if r.active and r.so and r.sees(city, customer, store)]


def upsert(rec: Recipient, by: str) -> None:
    backend = get_backend()
    df = backend.read(MAIL_RECIPIENTS)
    values = {"Email": rec.email.strip().lower(), "Name": rec.name, "Team": rec.team,
              "Hourly_Indent": "Y" if rec.hourly else "N", "SO_PO": "Y" if rec.so else "N",
              "Cities": "; ".join(rec.cities), "Customers": "; ".join(rec.customers),
              "Stores": "; ".join(rec.stores), "Active": "Y" if rec.active else "N",
              "Updated_At": config.now_iso(), "Updated_By": by}
    if not df.empty and "Email" in df.columns:
        hit = df.index[df["Email"].astype(str).str.strip().str.lower() == values["Email"]]
        if len(hit):
            backend.update_cells(MAIL_RECIPIENTS, int(df.loc[hit[0], "_row"]), values)
            return
    backend.append_dicts(MAIL_RECIPIENTS, [values])


def remove(email: str) -> bool:
    backend = get_backend()
    df = backend.read(MAIL_RECIPIENTS)
    if df.empty or "Email" not in df.columns:
        return False
    hit = df.index[df["Email"].astype(str).str.strip().str.lower() == email.strip().lower()]
    if not len(hit):
        return False
    row = int(df.loc[hit[0], "_row"])
    backend.delete_rows(MAIL_RECIPIENTS, row, row)
    return True


# ------------------------------------------------------------------ log

def log(kind: str, slot: str, to: list[str] | str, ok: bool, detail: str) -> None:
    try:
        get_backend().append_dicts(MAIL_LOG, [{
            "sent_at": config.now_iso(), "kind": kind, "slot": slot,
            "to": to if isinstance(to, str) else ", ".join(to),
            "status": "sent" if ok else "failed", "detail": str(detail)[:400]}])
    except Exception:
        pass   # the e-mail itself matters more than its log line


def read_log() -> pd.DataFrame:
    return get_backend().read(MAIL_LOG)


def already_sent(kind: str, slot: str, to: str) -> bool:
    df = read_log()
    if df.empty:
        return False
    hit = df[(df["kind"] == kind) & (df["slot"] == slot) & (df["status"] == "sent")
             & (df["to"].astype(str).str.lower() == to.lower())]
    return not hit.empty
