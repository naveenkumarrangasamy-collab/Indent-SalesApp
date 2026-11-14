"""Shared UI helpers: styling, flash messages, signed-in user, sidebar."""
from __future__ import annotations

import streamlit as st

from core import auth, config, indents, masters
from core.sheets import SheetError, get_backend

ACCENT = "#1c6b49"

# Filled in by app.py so pages can call st.switch_page(PAGES["indent"]).
PAGES: dict[str, object] = {}

_CSS = f"""
<style>
  /* Tabular numbers everywhere numbers line up */
  [data-testid="stMetricValue"], [data-testid="stDataFrame"], [data-testid="stTable"],
  .num {{ font-variant-numeric: tabular-nums; }}
  .block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; }}
  .mt-strip {{ display:flex; flex-wrap:wrap; gap:.4rem 1.4rem; padding:.55rem .8rem;
      border:1px solid rgba(28,107,73,.25); border-radius:.5rem; background:rgba(28,107,73,.05);
      font-size:.92rem; }}
  .mt-strip b {{ color:{ACCENT}; font-weight:600; margin-right:.25rem; }}
  .mt-badge {{ display:inline-block; padding:.05rem .5rem; border-radius:1rem; font-size:.78rem;
      font-weight:600; border:1px solid currentColor; }}
  .mt-badge.sub {{ color:{ACCENT}; }}
  .mt-badge.frz {{ color:#8a5a00; }}
  .mt-muted {{ color: rgba(49,51,63,.6); font-size:.85rem; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def badge(status: str) -> str:
    cls = "frz" if status == "Frozen" else "sub"
    return f'<span class="mt-badge {cls}">{status}</span>'


# ---------------------------------------------------------------- flash

def flash(kind: str, text: str) -> None:
    """Queue a message shown at the top of the next page render."""
    st.session_state.setdefault("_flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in st.session_state.pop("_flash", []):
        getattr(st, kind, st.info)(text)


# ---------------------------------------------------------------- user

def current_user() -> auth.User | None:
    """The signed-in user, re-checked against the (cached) Access tab so a
    revoked user is signed out within a minute."""
    u = st.session_state.get("user")
    if not u:
        return None
    try:
        m = masters.load_masters()
    except SheetError:
        return auth.User(**u)  # sheet briefly unavailable: keep the session
    user = auth.resolve_user(m.access, u["email"])
    if user is None:
        sign_out(message=f"Access for {u['email']} has been removed.")
        return None
    return user


def sign_in(user: auth.User) -> None:
    st.session_state.user = {"email": user.email, "name": user.name, "role": user.role}


def sign_out(message: str | None = None) -> None:
    from pages_src import state

    try:
        state.autosave(force=True)
    except Exception:
        pass
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    if message:
        flash("warning", message)


def refresh_data() -> None:
    masters.clear_cache()
    indents.clear_cache()


def sheet_error(e: Exception, what: str = "") -> None:
    st.error((what + " " if what else "") + str(e))


# ---------------------------------------------------------------- sidebar

def sidebar(user: auth.User) -> None:
    with st.sidebar:
        st.markdown(f"**{user.label}**  \n<span class='mt-muted'>{user.email} · {user.role}</span>",
                    unsafe_allow_html=True)
        backend = get_backend()
        if backend.mode == "local":
            st.warning("Local mode: data is saved to CSV files in `data/`, not to Google Sheets. "
                       "Add the service account to the app secrets to go live.", icon="💾")
        if st.session_state.get("must_change_pin"):
            st.warning("You signed in with the initial PIN. Please set your own PIN below.")
        c1, c2 = st.columns(2)
        if c1.button("↻ Refresh data", width="stretch",
                     help="Reload SKU, store and indent data from the sheet now"):
            refresh_data()
            st.toast("Data refreshed from the sheet")
        if c2.button("Sign out", width="stretch"):
            sign_out()
            st.rerun()
        with st.expander("Change my PIN", expanded=bool(st.session_state.get("must_change_pin"))):
            with st.form("change_pin", clear_on_submit=True):
                cur = st.text_input("Current PIN", type="password", max_chars=6)
                new = st.text_input("New PIN (4–6 digits)", type="password", max_chars=6)
                new2 = st.text_input("Repeat new PIN", type="password", max_chars=6)
                if st.form_submit_button("Save PIN"):
                    _change_pin(user, cur, new, new2)
        saved = st.session_state.get("draft_saved_at")
        if saved:
            st.caption(f"Draft autosaved {saved[11:19]}")
        err = st.session_state.get("draft_error")
        if err:
            st.caption(f"⚠️ Draft not saved to the sheet yet: {err}")
        st.caption(f"Master data refreshes every {config.master_cache_seconds()} s")


def _change_pin(user: auth.User, cur: str, new: str, new2: str) -> None:
    m = masters.load_masters()
    res = auth.authenticate(m.access, user.email, cur)
    if res.user is None:
        st.error("Current PIN is not correct.")
        return
    if not auth.valid_pin(new):
        st.error("New PIN must be 4 to 6 digits.")
        return
    if new != new2:
        st.error("The new PINs do not match.")
        return
    try:
        auth.upsert_access(user.email, by=user.email, pin=new,
                           **({"role": user.role, "status": auth.ACCESS_ACTIVE, "name": user.name}
                              if auth.access_row(m.access, user.email) is None else {}))
    except SheetError as e:
        sheet_error(e, "PIN not saved.")
        return
    masters.clear_cache()
    st.session_state.pop("must_change_pin", None)
    st.success("PIN updated.")
