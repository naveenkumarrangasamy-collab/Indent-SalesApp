"""Read an order picture / screenshot with Gemini (19 Nov, user's choice).

The picture goes to the Gemini API with a fixed instruction; Gemini returns JSON:
the customer / store name it sees, every order line (item name as written, pack,
qty, how sure it is) and the total if one is written. Nothing is guessed by us:
the lines then go through the same matching and checks as an Excel or PDF
(exact names, "Same as?", customer check, total vs read total, Saved vs File).

Secrets: `gemini_api_key` (needed; without it pictures fall back to / stay off),
`gemini_model` (default gemini-3.8-flash; gemini-2.5-flash is tried if that is refused).
"""
from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field

from core import config
from core.po_reader import POLine

DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite")


class Busy(Exception):
    """The model is overloaded or out of free quota right now (429 / 5xx): try the next one."""
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """You read purchase orders / indents for a fruit supplier (Ninjacart) from a photo or a
screenshot (often a WhatsApp message or a phone photo of a printed or handwritten list; it may be
tilted, slightly blurred or shaken).

Return every order line you can see, in order, top to bottom:
- name: the item exactly as written (keep brand words like Bloom / Snacky / BH, variety, origin),
  without the quantity;
- pack: the pack or size written for it, e.g. "2 pcs", "250 g", "1 kg", "1 box" ("" if none);
- qty: the ordered quantity as a number (units / packs ordered, NOT the pack size, NOT a price);
- sure: false when any part of the line is hard to read or you had to guess.
Also return: customer = the customer / company name written on it ("" if none), store = the
store / warehouse / location written ("" if none), total = the total quantity if a total is
written (else null), notes = anything unclear (short).
Never invent lines. Skip headers, prices, amounts, dates and phone numbers. If a line has no
quantity, give qty 0 and sure false."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "customer": {"type": "STRING"},
        "store": {"type": "STRING"},
        "total": {"type": "NUMBER", "nullable": True},
        "notes": {"type": "STRING"},
        "lines": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}, "pack": {"type": "STRING"},
                           "qty": {"type": "NUMBER"}, "sure": {"type": "BOOLEAN"}},
            "required": ["name", "qty", "sure"]}},
    },
    "required": ["lines"],
}


class AIReadError(Exception):
    pass


@dataclass
class AIRead:
    lines: list[POLine] = field(default_factory=list)
    customer: str = ""
    store: str = ""
    total: float | None = None
    notes: str = ""
    model: str = ""

    @property
    def text(self) -> str:
        return " ".join([self.customer, self.store] + [x.name for x in self.lines])


def api_key() -> str:
    return str(config.get("gemini_api_key", "") or "").strip()


def available() -> bool:
    return bool(api_key())


def _shrink(data: bytes, mime: str) -> tuple[bytes, str]:
    """Big phone photos -> at most ~2,400 px, JPEG (enough to read; faster upload)."""
    if len(data) < 3_500_000:
        return data, mime
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((2400, 2400))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=90)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 - send as is
        return data, mime


def parse(payload: dict) -> AIRead:
    """Gemini's JSON -> AIRead (lines with qty > 0; unsure lines kept and flagged)."""
    out = AIRead(customer=str(payload.get("customer") or "").strip(),
                 store=str(payload.get("store") or "").strip(),
                 notes=str(payload.get("notes") or "").strip())
    try:
        t = payload.get("total")
        out.total = float(t) if t not in (None, "") else None
    except (TypeError, ValueError):
        out.total = None
    for ln in payload.get("lines") or []:
        name = " ".join(str(ln.get("name") or "").split())
        try:
            qty = float(ln.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if not name or qty <= 0:
            continue
        pack = " ".join(str(ln.get("pack") or "").split())
        full = f"{name} - {pack}" if pack and pack.casefold() not in name.casefold() else name
        out.lines.append(POLine(name=full, qty=qty, unsure=not bool(ln.get("sure", True))))
    return out


def _call(model: str, img: bytes, mime: str, key: str, prompt: str | None = None,
          schema: dict | None = None) -> dict:
    import requests
    body = {"contents": [{"parts": [{"text": prompt or PROMPT},
                                    {"inline_data": {"mime_type": mime,
                                                     "data": base64.b64encode(img).decode()}}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "responseSchema": schema or SCHEMA}}
    import time
    last = ""
    for attempt in range(2):
        if attempt:
            time.sleep(2)
        try:
            r = requests.post(URL.format(model=model), params={"key": key}, json=body, timeout=90)
        except requests.RequestException as e:
            last = f"could not reach Gemini ({type(e).__name__})"
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"busy ({r.status_code})"
            continue
        if r.status_code == 404:
            raise LookupError(model)
        if r.status_code >= 400:
            msg = ""
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                pass
            if r.status_code in (400, 401, 403) and "key" in msg.casefold():
                raise AIReadError("The Gemini key was refused: check gemini_api_key in Secrets.")
            raise AIReadError(f"Gemini refused the picture ({r.status_code}). {msg[:200]}")
        try:
            j = r.json()
            text = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
            return json.loads(text)
        except (ValueError, KeyError, IndexError, TypeError):
            last = "no readable answer"
    raise Busy(last or "no answer")


def read(data: bytes, mime: str = "image/jpeg") -> AIRead:
    key = api_key()
    if not key:
        raise AIReadError("Picture reading needs gemini_api_key in Secrets.")
    img, mime = _shrink(data, mime)
    first = str(config.get("gemini_model", DEFAULT_MODEL) or DEFAULT_MODEL)
    tried = []
    for model in dict.fromkeys((first,) + FALLBACK_MODELS):
        try:
            payload = _call(model, img, mime, key)
        except (LookupError, Busy) as e:        # not offered / overloaded: the next model
            tried.append(f"{model}: {'not available' if isinstance(e, LookupError) else e}")
            continue
        res = parse(payload)
        res.model = model
        return res
    raise AIReadError("Gemini is busy right now (" + "; ".join(tried) + "). Press Read again in a minute.")


def mime_of(name: str) -> str:
    ext = str(name or "").rsplit(".", 1)[-1].casefold()
    return {"png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
