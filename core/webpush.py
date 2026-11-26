"""Browser push notifications (26 Nov): no extra app, no account.

The person taps **Allow alerts on this device** in the app; the browser asks once ("Show notifications?"),
a small service worker (pages_src/push/sw.js, served by the app itself) subscribes the device, and the
subscription is stored against the **login e-mail** in the tab `Push_Subs`. Alerts are then sent from the
server straight to the browser's push service (Web Push, RFC 8030 / 8291 / 8292), even when the app is closed.

Keys (VAPID): secret `vapid_private_key` (PEM) when set, else generated once and kept in the tab `Push_Keys`.
Works in Chrome / Edge / Firefox (Android + laptop). iPhone: only after "Add to Home Screen" (Apple's rule).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

from core import config
from core.schema import PUSH_KEYS, PUSH_SUBS


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    s = str(s).strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ------------------------------------------------------------------ keys

def new_private_pem() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


def _load(pem: str):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem.encode(), password=None)


def public_key_b64(pem: str) -> str:
    """The applicationServerKey for the browser (uncompressed P-256 point, base64url)."""
    from cryptography.hazmat.primitives import serialization
    pub = _load(pem).public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
    return b64u(pub)


_KEY_CACHE: dict = {}


def private_pem() -> str:
    """Secret `vapid_private_key`, else the one kept in the Push_Keys tab (made on first use)."""
    pem = str(config.get("vapid_private_key", "") or "").strip()
    if pem:
        return pem
    if _KEY_CACHE.get("pem"):
        return _KEY_CACHE["pem"]
    from core.sheets import get_backend
    b = get_backend()
    df = b.read(PUSH_KEYS) if PUSH_KEYS in b.list_tabs() else None
    rows = [] if df is None or df.empty else [r for r in df.to_dict("records") if str(r.get("Value", "")).strip()]
    if not rows:
        b.append_dicts(PUSH_KEYS, [{"Key": "vapid_private_key", "Value": _to_cell(new_private_pem()),
                                    "Created_At": config.now_iso()}])
        df = b.read(PUSH_KEYS)            # the first row wins if two people made one at the same moment
        rows = [r for r in df.to_dict("records") if str(r.get("Value", "")).strip()]
    _KEY_CACHE["pem"] = _from_cell(str(rows[0]["Value"]).strip())
    return _KEY_CACHE["pem"]


def _to_cell(pem: str) -> str:
    """One line of base64 DER (starts with 'M'), so the sheet never reads it as a formula."""
    body = "".join(ln for ln in pem.strip().splitlines() if "-----" not in ln)
    return body


def _from_cell(v: str) -> str:
    if "BEGIN" in v:
        return v
    lines = [v[i:i + 64] for i in range(0, len(v), 64)]
    return "-----BEGIN PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END PRIVATE KEY-----\n"


# ------------------------------------------------------------------ VAPID + encryption

def vapid_header(endpoint: str, pem: str, subject: str, now: int | None = None) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    u = urllib.parse.urlsplit(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int(now or time.time()) + 12 * 3600, "sub": subject}
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps(claims, separators=(",", ":")).encode())
    signing = f"{head}.{body}".encode()
    r, s = decode_dss_signature(_load(pem).sign(signing, ec.ECDSA(hashes.SHA256())))
    jwt = f"{head}.{body}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={public_key_b64(pem)}"


def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk: bytes, info: bytes, n: int) -> bytes:
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]   # n <= 32: one block is enough


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None,
            server_key=None) -> bytes:
    """RFC 8291 aes128gcm body for one subscription."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_pub_bytes = b64u_dec(p256dh)
    auth_secret = b64u_dec(auth)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_bytes)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_pub = as_key.public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint)
    shared = as_key.exchange(ec.ECDH(), ua_pub)
    prk_key = _hkdf_extract(auth_secret, shared)
    ikm = _hkdf_expand(prk_key, b"WebPush: info\x00" + ua_pub_bytes + as_pub, 32)
    salt = salt or os.urandom(16)
    prk = _hkdf_extract(salt, ikm)
    cek = _hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    cipher = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">I", 4096) + bytes([len(as_pub)]) + as_pub + cipher


def send_one(sub: dict, data: dict, pem: str | None = None, ttl: int = 6 * 3600,
             timeout: float = 10.0) -> tuple[int, str]:
    """POST one push. Returns (HTTP status, text); 404 / 410 = the subscription is gone."""
    pem = pem or private_pem()
    body = encrypt(json.dumps(data).encode("utf-8"), sub["p256dh"], sub["auth"])
    subject = "mailto:" + (config.owner_email() or "mt-indent@example.com")
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(ttl),
        "Urgency": "high", "Authorization": vapid_header(sub["endpoint"], pem, subject)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, "sent"
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")[:200].decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"[:200]


# ------------------------------------------------------------------ subscriptions

def _norm(e: str) -> str:
    return str(e or "").strip().casefold()


def subscriptions(email: str | None = None) -> list[dict]:
    from core.sheets import get_backend
    b = get_backend()
    if PUSH_SUBS not in b.list_tabs():
        return []
    df = b.read(PUSH_SUBS)
    if df is None or df.empty:
        return []
    out = {}
    for r in df.to_dict("records"):          # last row per endpoint wins (Status on / off)
        ep = str(r.get("Endpoint", "")).strip()
        if ep:
            out[ep] = {"email": _norm(r.get("Email")), "endpoint": ep, "p256dh": str(r.get("P256dh", "")).strip(),
                       "auth": str(r.get("Auth", "")).strip(), "status": str(r.get("Status", "on")).strip().lower(),
                       "device": str(r.get("Device", ""))}
    subs = [s for s in out.values() if s["status"] != "off" and s["p256dh"] and s["auth"]]
    return [s for s in subs if email is None or s["email"] == _norm(email)]


def save_subscription(email: str, sub: dict, device: str = "") -> bool:
    """Store this device's subscription for the login e-mail (once per endpoint + e-mail)."""
    ep = str((sub or {}).get("endpoint", "")).strip()
    keys = (sub or {}).get("keys") or {}
    if not ep or not keys.get("p256dh") or not keys.get("auth"):
        return False
    if any(s["endpoint"] == ep and s["email"] == _norm(email) for s in subscriptions()):
        return True
    from core.sheets import get_backend
    get_backend().append_dicts(PUSH_SUBS, [{"Email": _norm(email), "Endpoint": ep, "P256dh": keys["p256dh"],
                                            "Auth": keys["auth"], "Device": _device(device), "Status": "on",
                                            "Updated_At": config.now_iso()}])
    return True


def _drop(sub: dict) -> None:
    try:
        from core.sheets import get_backend
        get_backend().append_dicts(PUSH_SUBS, [{"Email": sub["email"], "Endpoint": sub["endpoint"],
                                                "P256dh": sub["p256dh"], "Auth": sub["auth"],
                                                "Device": sub.get("device", ""), "Status": "off",
                                                "Updated_At": config.now_iso()}])
    except Exception:  # noqa: BLE001
        pass


def _device(ua: str) -> str:
    ua = str(ua or "")
    kind = "iPhone" if "iPhone" in ua else "Android" if "Android" in ua else "Mac" if "Mac OS" in ua \
        else "Windows" if "Windows" in ua else "Device"
    app = "Edge" if "Edg/" in ua else "Chrome" if "Chrome" in ua else "Firefox" if "Firefox" in ua \
        else "Safari" if "Safari" in ua else ""
    return f"{kind} {app}".strip()


def send_to(email: str, title: str, lines: list[str], tag: str = "") -> tuple[bool, str]:
    """Every device of this person. (any delivered, short reason)."""
    subs = subscriptions(email)
    if not subs:
        return False, "alerts not turned on on any device"
    pem = private_pem()
    data = {"title": title, "body": "\n".join(lines) or title, "tag": tag,
            "url": "https://indent-salesapp.streamlit.app/"}
    ok, notes = 0, []
    for s in subs:
        code, why = send_one(s, data, pem)
        if 200 <= code < 300:
            ok += 1
        elif code in (404, 410):
            _drop(s)
            notes.append(f"{s['device'] or 'a device'} unsubscribed")
        else:
            notes.append(f"{s['device'] or 'device'}: {code} {why}")
    return ok > 0, f"{ok}/{len(subs)} device(s)" + (f" · {'; '.join(notes)}" if notes else "")
