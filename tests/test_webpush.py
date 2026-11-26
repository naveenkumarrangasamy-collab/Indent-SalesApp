"""26 Nov: browser push (core/webpush.py): encryption decrypts like a browser, VAPID token verifies."""
import json
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core import webpush as w


def _browser():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    return key, pub, auth


def _decrypt(body: bytes, ua_key, ua_pub: bytes, auth: bytes) -> bytes:
    """What the browser does (RFC 8291 / 8188, one record)."""
    salt, rs, idlen = body[:16], struct.unpack(">I", body[16:20])[0], body[20]
    as_pub = body[21:21 + idlen]
    cipher = body[21 + idlen:]
    assert rs == 4096 and idlen == 65
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = w._hkdf_expand(w._hkdf_extract(auth, shared), b"WebPush: info\x00" + ua_pub + as_pub, 32)
    prk = w._hkdf_extract(salt, ikm)
    cek = w._hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = w._hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(cek).decrypt(nonce, cipher, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_decrypts_like_a_browser():
    key, pub, auth = _browser()
    data = {"title": "PO difference · Swiggy · Swiggy WH2", "body": "1Pc - Imported Avocado  -50"}
    body = w.encrypt(json.dumps(data).encode(), w.b64u(pub), w.b64u(auth))
    assert json.loads(_decrypt(body, key, pub, auth)) == data


def test_vapid_token_verifies_with_the_public_key():
    pem = w.new_private_pem()
    h = w.vapid_header("https://fcm.googleapis.com/fcm/send/abc", pem, "mailto:o@x.com", now=1_800_000_000)
    t = h.split("t=")[1].split(",")[0]
    k = h.split("k=")[1]
    head, claims, sig = t.split(".")
    assert json.loads(w.b64u_dec(claims)) == {"aud": "https://fcm.googleapis.com", "exp": 1_800_043_200,
                                             "sub": "mailto:o@x.com"}
    raw = w.b64u_dec(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), w.b64u_dec(k))
    pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))   # raises if wrong
    assert k == w.public_key_b64(pem) and len(w.b64u_dec(k)) == 65


def test_key_cell_round_trip_and_device_names():
    pem = w.new_private_pem()
    cell = w._to_cell(pem)
    assert cell.startswith("M") and "\n" not in cell and w.public_key_b64(w._from_cell(cell)) == w.public_key_b64(pem)
    assert w._device("Mozilla/5.0 (Linux; Android 14) Chrome/131 Mobile") == "Android Chrome"
    assert w._device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1") == "iPhone Safari"


def test_matches_rfc8291_example():
    """The worked example of RFC 8291 (Appendix A), byte for byte."""
    k = ec.derive_private_key(int.from_bytes(w.b64u_dec("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
                              ec.SECP256R1())
    body = w.encrypt(b"When I grow up, I want to be a watermelon",
                     "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
                     "BTBZMqHH6r4Tts7J_aSIgg", salt=w.b64u_dec("DGv6ra1nlYgDCS1FRnbzlw"), server_key=k)
    assert w.b64u(body) == ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLoc"
                            "InmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexS"
                            "gSxsj_Qulcy4a-fN")
