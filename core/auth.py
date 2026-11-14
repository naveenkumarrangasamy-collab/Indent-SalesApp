"""Email + PIN sign-in, roles from the Access tab.

PINs are never stored in clear text. The Access tab holds
`pbkdf2_sha256$<iterations>$<salt>$<hash>`, computed with a secret pepper
from the app secrets, so a copy of the sheet alone cannot be used to guess
PINs offline.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass

import pandas as pd

from core import config
from core.schema import (ACCESS, ACCESS_ACTIVE, ACCESS_REVOKED, ROLE_OWNER,
                         ROLE_SALES)

PIN_RE = re.compile(r"^\d{4,6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ITERATIONS = 200_000
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


@dataclass
class User:
    email: str
    name: str
    role: str

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_OWNER

    @property
    def label(self) -> str:
        return self.name or self.email


def norm_email(email: str) -> str:
    return str(email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(norm_email(email)))


def valid_pin(pin: str) -> bool:
    return bool(PIN_RE.match(str(pin or "")))


# ---------------------------------------------------------------- hashing

def hash_pin(pin: str, pepper: str | None = None, salt: bytes | None = None,
             iterations: int = _ITERATIONS) -> str:
    pepper = config.pin_pepper() if pepper is None else pepper
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", (pepper + str(pin)).encode(), salt, iterations)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return f"pbkdf2_sha256${iterations}${b64(salt)}${b64(dk)}"


def verify_pin(pin: str, stored: str, pepper: str | None = None) -> bool:
    try:
        algo, iters, salt_s, hash_s = str(stored).split("$")
        if algo != "pbkdf2_sha256":
            return False
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        salt = base64.urlsafe_b64decode(pad(salt_s))
        expected = base64.urlsafe_b64decode(pad(hash_s))
    except (ValueError, TypeError):
        return False
    pepper = config.pin_pepper() if pepper is None else pepper
    dk = hashlib.pbkdf2_hmac("sha256", (pepper + str(pin)).encode(), salt, int(iters))
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------- lockout

class _Lockout:
    """Failed attempts per email, shared by every session on this server."""

    def __init__(self):
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def locked_for(self, email: str) -> int:
        with self._lock:
            now = time.time()
            fails = [t for t in self._fails.get(email, []) if now - t < LOCK_SECONDS]
            self._fails[email] = fails
            if len(fails) >= MAX_FAILURES:
                return int(LOCK_SECONDS - (now - fails[0])) + 1
            return 0

    def fail(self, email: str) -> None:
        with self._lock:
            self._fails.setdefault(email, []).append(time.time())

    def reset(self, email: str) -> None:
        with self._lock:
            self._fails.pop(email, None)


import streamlit as st  # noqa: E402


@st.cache_resource(show_spinner=False)
def _lockout() -> _Lockout:
    return _Lockout()


# ---------------------------------------------------------------- lookups

def access_row(access: pd.DataFrame, email: str) -> pd.Series | None:
    if access is None or access.empty:
        return None
    m = access[access["Email"].map(norm_email) == norm_email(email)]
    return None if m.empty else m.iloc[0]


def resolve_user(access: pd.DataFrame, email: str) -> User | None:
    """The active user for this email, or None. The owner email from the
    secrets is always an active owner (so the owner cannot lock themself out)."""
    email = norm_email(email)
    row = access_row(access, email)
    if email and email == config.owner_email():
        name = row.get("Name", "") if row is not None else ""
        return User(email=email, name=name, role=ROLE_OWNER)
    if row is None or str(row.get("Status", "")).strip().lower() != ACCESS_ACTIVE:
        return None
    role = str(row.get("Role", "")).strip().lower()
    role = ROLE_OWNER if role == ROLE_OWNER else ROLE_SALES
    return User(email=email, name=row.get("Name", ""), role=role)


@dataclass
class LoginResult:
    user: User | None
    message: str = ""
    used_initial_pin: bool = False


def authenticate(access: pd.DataFrame, email: str, pin: str) -> LoginResult:
    email = norm_email(email)
    if not valid_email(email):
        return LoginResult(None, "Enter a valid work email.")
    lock = _lockout()
    wait = lock.locked_for(email)
    if wait:
        return LoginResult(None, f"Too many wrong PINs. Try again in {max(1, wait // 60)} min.")
    user = resolve_user(access, email)
    if user is None:
        return LoginResult(None, f"Access is not granted for {email}. "
                                 "Ask the indent owner to add your email.")
    row = access_row(access, email)
    stored = str(row.get("PIN_Hash", "")).strip() if row is not None else ""
    ok, initial = False, False
    if stored:
        ok = verify_pin(pin, stored)
    elif email == config.owner_email() and config.owner_initial_pin():
        ok = hmac.compare_digest(str(pin), config.owner_initial_pin())
        initial = ok
    else:
        return LoginResult(None, "No PIN is set for this email yet. Ask the indent owner to set one.")
    if not ok:
        lock.fail(email)
        return LoginResult(None, "Incorrect PIN.")
    lock.reset(email)
    return LoginResult(user, used_initial_pin=initial)


# ---------------------------------------------------------------- writes

def upsert_access(email: str, *, by: str, name: str | None = None, role: str | None = None,
                  status: str | None = None, pin: str | None = None) -> None:
    """Add or update one row of the Access tab (reads it fresh first)."""
    from core.sheets import get_backend

    email = norm_email(email)
    backend = get_backend()
    access = backend.read(ACCESS)
    row = access_row(access, email)
    values: dict[str, object] = {"Updated_At": config.now_iso(), "Updated_By": by}
    if name is not None:
        values["Name"] = name.strip()
    if role is not None:
        values["Role"] = role
    if status is not None:
        values["Status"] = status
    if pin is not None:
        values["PIN_Hash"] = hash_pin(pin)
    if row is None:
        values.setdefault("Name", "")
        values.setdefault("Role", ROLE_SALES)
        values.setdefault("Status", ACCESS_ACTIVE)
        values["Email"] = email
        backend.append_dicts(ACCESS, [values])
    else:
        backend.update_cells(ACCESS, int(row["_row"]), values)


__all__ = ["User", "LoginResult", "authenticate", "resolve_user", "hash_pin", "verify_pin",
           "valid_pin", "valid_email", "norm_email", "upsert_access", "ACCESS_ACTIVE",
           "ACCESS_REVOKED"]
