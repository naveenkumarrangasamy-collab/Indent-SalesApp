"""26 Nov: the 'Allow alerts on this device' button (a tiny component in pages_src/push) and the sign-in
prompt for Warehouse / Owner / Creator. Browser push only: no extra app or account (core/webpush.py)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from core import auth, webpush

_push = components.declare_component("mt_push", path=str(Path(__file__).parent / "push"))

ALERT_WHY = (
    "From today the **warehouse and owners** get an alert on their phone or laptop the moment a PO is "
    "uploaded and:\n"
    "- a quantity differs from the indent (**20 units or 10 %** or more),\n"
    "- the PO has a **SKU that is not on the indent**, or\n"
    "- an item on the PO has **no spec mapped**.\n\n"
    "Each alert shows only the SKU name and the difference, so you can act before batching.")
ALERT_HOW = ("Tap **Allow alerts on this device**, then **Allow** when the browser asks. That's all; do it once "
             "on each phone / laptop you use. iPhone: first Share → **Add to Home Screen** and open the app "
             "from there.")


def for_alerts(user: auth.User) -> bool:
    return user.is_owner or user.is_warehouse


def _key() -> str:
    return webpush.public_key_b64(webpush.private_pem())


def _store(user: auth.User, res) -> None:
    """Save this device's subscription once per browser session."""
    if not isinstance(res, dict) or res.get("state") != "on" or not res.get("sub"):
        return
    ep = res["sub"].get("endpoint", "")
    if st.session_state.get("push_saved") == ep:
        return
    try:
        webpush.save_subscription(user.email, res["sub"], res.get("ua", ""))
        st.session_state["push_saved"] = ep
    except Exception:  # noqa: BLE001
        pass


def button(user: auth.User, key: str, label: str = "Allow alerts on this device") -> dict | None:
    try:
        vapid = _key()
    except Exception as e:  # noqa: BLE001
        st.caption(f"Alerts are not available right now: {e}")
        return None
    res = _push(mode="button", vapid=vapid, label=label, key=key, default=None)
    _store(user, res)
    return res


def check(user: auth.User) -> None:
    """Invisible: tells the app whether this device already has alerts on (session_state['push_state'])."""
    try:
        vapid = _key()
    except Exception:  # noqa: BLE001
        return
    res = _push(mode="check", vapid=vapid, key="push_check", default=None)
    if isinstance(res, dict):
        st.session_state["push_state"] = res.get("state")
        _store(user, res)


def prompt(user: auth.User) -> None:
    """Once per sign-in: when this device does not have alerts yet, ask with the reason."""
    if not for_alerts(user) or st.session_state.get("alert_prompted"):
        return
    if st.session_state.get("push_state") != "off":     # unknown yet, already on, blocked or not supported
        return
    st.session_state["alert_prompted"] = True
    _dialog(user)


@st.dialog("🔔 Allow PO alerts on this device", width="large")
def _dialog(user: auth.User) -> None:
    st.markdown(ALERT_WHY)
    st.markdown(ALERT_HOW)
    res = button(user, key="push_dlg")
    on = isinstance(res, dict) and res.get("state") == "on"
    c = st.columns(2)
    if on and c[0].button("Send test alert", width="stretch", key="push_dlg_test"):
        from core import alerts
        ok, msg = alerts.send_test(user.email)
        (st.success if ok else st.error)(msg)
    if c[1].button("Close" if on else "Later", width="stretch", key="push_dlg_close"):
        st.rerun()
    st.caption("You can do this any time from the sidebar: 🔔 PO alerts on this device.")


def sidebar_box(user: auth.User) -> None:
    with st.expander("🔔 PO alerts on this device"):
        st.caption("An alert when a PO comes in with a difference, a new SKU or no spec mapped.")
        res = button(user, key="push_side")
        if isinstance(res, dict) and res.get("state") == "on":
            if st.button("Send test alert", width="stretch", key="push_side_test"):
                from core import alerts
                ok, msg = alerts.send_test(user.email)
                (st.success if ok else st.error)(msg)
