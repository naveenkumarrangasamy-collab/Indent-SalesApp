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
  .mt-badge.cnl {{ color:#b42318; }}
  .mt-muted {{ color: rgba(49,51,63,.6); font-size:.85rem; }}

  /* ---- Pill buttons (customers, stores, cities): dark "hovering" boxes ----
     Streamlit marks them data-variant="pills"; the chosen one has aria-checked="true". */
  button[data-variant="pills"] {{
      border-radius: 999px !important; padding: .42rem 1.05rem !important; min-height: 2.3rem;
      font-weight: 600 !important; letter-spacing: .1px;
      background: #1f2328 !important; color: #f1f4f7 !important; border: 1px solid #343a42 !important;
      box-shadow: 0 2px 6px rgba(15,23,42,.18); transition: transform .12s ease, box-shadow .12s ease;
  }}
  button[data-variant="pills"]:hover:not([aria-disabled="true"]):not(:disabled) {{
      transform: translateY(-2px); box-shadow: 0 8px 18px rgba(15,23,42,.28); border-color: #2f81f7 !important; }}
  button[data-variant="pills"][aria-checked="true"] {{
      background: #0d2c4f !important; color: #6cb6ff !important; border: 1px solid #2f81f7 !important;
      box-shadow: 0 0 0 2px rgba(47,129,247,.25), 0 4px 12px rgba(15,23,42,.25); }}
  button[data-variant="pills"] p, button[data-variant="pills"] span {{ color: inherit !important; }}
  button[data-variant="pills"]:disabled, button[data-variant="pills"][aria-disabled="true"] {{ opacity: .45; }}
  [role="radiogroup"]:has(> button[data-variant="pills"]) {{ gap: .55rem !important; flex-wrap: wrap; }}

  /* ---- Segmented control (delivery day): dark bar, lighter chosen segment ---- */
  [role="radiogroup"]:has(> button[data-variant="segmented_control"]) {{
      background: #1f2328; border-radius: 12px; padding: 4px; display: inline-flex; gap: 2px;
      box-shadow: 0 2px 8px rgba(15,23,42,.2); width: fit-content; }}
  button[data-variant="segmented_control"] {{
      border: none !important; border-radius: 9px !important; padding: .45rem 1.1rem !important;
      font-weight: 600 !important; background: transparent !important; color: #d0d7de !important; }}
  button[data-variant="segmented_control"]:hover {{ background: #2d333b !important; color: #fff !important; }}
  button[data-variant="segmented_control"][aria-checked="true"] {{ background: #5b636e !important; color: #fff !important; }}
  button[data-variant="segmented_control"] p, button[data-variant="segmented_control"] span {{ color: inherit !important; }}

  /* delivery card */
  .st-key-mt_delivery_card {{ background: linear-gradient(180deg, rgba(28,107,73,.04), rgba(28,107,73,0));
      border-radius: 14px; }}

  /* ---- Home dashboard tiles ---- */
  .mt-tiles {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap:10px; margin:.4rem 0 1rem; }}
  .mt-tile {{ background:#1f2328; color:#f1f4f7; border-radius:14px; padding:.8rem 1rem;
      box-shadow:0 2px 8px rgba(15,23,42,.18); }}
  .mt-tile .lbl {{ font-size:.8rem; color:#c9d1d9; font-weight:600; }}
  .mt-tile .val {{ font-size:1.55rem; font-weight:700; font-variant-numeric: tabular-nums; line-height:1.2; }}
  .mt-tile .sub {{ font-size:.78rem; color:#9da7b1; }}
  .mt-tile.good .val {{ color:#3fb950; }} .mt-tile.warn .val {{ color:#e3b341; }}
  .mt-tile.bad .val {{ color:#f85149; }} .mt-tile.info .val {{ color:#6cb6ff; }}
  .mt-cust {{ border:1px solid #e3e8e5; border-radius:14px; padding:.7rem .9rem; margin-bottom:.8rem;
      background:#fff; box-shadow:0 1px 4px rgba(15,23,42,.06); }}
  .mt-cust h4 {{ margin:0 0 .35rem 0; font-size:1rem; }}
  .mt-chip {{ display:inline-block; border-radius:999px; padding:.2rem .65rem; margin:.15rem .25rem .15rem 0;
      font-size:.8rem; font-weight:600; border:1px solid transparent; }}
  .mt-chip.none {{ background:#f2f4f7; color:#57606a; border-color:#d0d7de; }}
  .mt-chip.open {{ background:#fff8c5; color:#7d4e00; border-color:#e3b341; }}
  .mt-chip.done {{ background:#dafbe1; color:#116329; border-color:#4ac26b; }}
  .mt-chip.cnl  {{ background:#ffebe9; color:#a40e26; border-color:#ff8182; text-decoration: line-through; }}
  .mt-bar {{ height:8px; border-radius:6px; background:#e9edf0; overflow:hidden; display:flex; }}
  .mt-bar span {{ display:block; height:100%; }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def connection_banner() -> None:
    """Loud warning on every page when the app is not using the Google Sheet."""
    if get_backend().mode == "gsheets":
        return
    from core.sheets import CONNECT_ERROR

    reason = CONNECT_ERROR["reason"] or config.google_status()[1]
    names = config.secret_names()
    found = ("Secrets the app can see: " + ", ".join(f"`{n}`" for n in names) + "."
             if names else "The app sees **no secrets at all** (the Secrets box is empty or not saved).")
    st.error("**Not connected to the Google Sheet.** The app is showing built-in test data and "
             "nothing is saved to your sheet. " + (reason or "")
             + " Fix it in Streamlit Cloud → Manage app → Settings → Secrets, then Reboot app.\n\n"
             + found, icon="⚠️")


def badge(status: str) -> str:
    cls = {"Frozen": "frz", "Cancelled": "cnl"}.get(status, "sub")
    return f'<span class="mt-badge {cls}">{status}</span>'


# ---------------------------------------------------------------- flash

def flash(kind: str, text: str) -> None:
    """Queue a message shown at the top of the next page render."""
    st.session_state.setdefault("_flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in st.session_state.pop("_flash", []):
        getattr(st, kind, st.info)(text)


# ---------------------------------------------------------------- user

COOKIE = "mt_indent_session"


def _set_cookie(value: str, max_age: int) -> None:
    """Set (or clear, with max_age=0) the sign-in cookie in this browser."""
    import json
    st.html(f"<script>document.cookie = {json.dumps(COOKIE + '=' + value)} + "
            f"'; path=/; max-age={int(max_age)}; SameSite=Lax' + "
            "(location.protocol === 'https:' ? '; Secure' : '');</script>",
            unsafe_allow_javascript=True, width=1)


def remember_login(user: auth.User) -> None:
    """Called once after sign-in: keep the browser signed in."""
    st.session_state["_set_cookie"] = True


def flush_cookie() -> None:
    """Write / clear the cookie on this run if asked (needs a rendered page)."""
    s = st.session_state
    if s.pop("_clear_cookie", False):
        _set_cookie("", 0)
    if s.pop("_set_cookie", False) and s.get("user"):
        try:
            token = auth.make_session_token(masters.load_masters().access, s["user"]["email"])
        except SheetError:
            return
        _set_cookie(token, 86400 * config.session_days())


def _cookie_token() -> str | None:
    try:
        return st.context.cookies.get(COOKIE)
    except Exception:
        return None


def _from_cookie() -> auth.User | None:
    token = _cookie_token()
    if not token or st.session_state.get("_cookie_rejected"):
        return None
    try:
        user = auth.user_from_session_token(masters.load_masters().access, token)
    except SheetError:
        return None
    if user is None:
        st.session_state["_cookie_rejected"] = True
        st.session_state["_clear_cookie"] = True
        return None
    from pages_src import state
    sign_in(user)
    st.session_state["_set_cookie"] = True  # slide the expiry forward
    if state.restore_from_sheet(user.email):
        flash("info", "Welcome back. Your unsaved indent draft was restored.")
    return user


def current_user() -> auth.User | None:
    """The signed-in user, re-checked against the (cached) Access tab so a
    revoked user is signed out within a few minutes. After a refresh or a
    closed tab the browser's sign-in cookie signs the user back in."""
    u = st.session_state.get("user")
    if not u:
        restored = _from_cookie()
        if restored is None:
            return None
        u = st.session_state["user"]
    try:
        m = masters.load_masters()
    except SheetError:
        return auth.User.from_dict(u)  # sheet briefly unavailable: keep the session
    user = auth.resolve_user(m.access, u["email"])
    if user is None:
        sign_out(message=f"Access for {u['email']} has been removed.")
        return None
    return user


def sign_in(user: auth.User) -> None:
    st.session_state.user = user.to_dict()


def sign_out(message: str | None = None) -> None:
    from pages_src import state

    try:
        state.autosave(force=True)
    except Exception:
        pass
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state["_clear_cookie"] = True       # forget this browser
    st.session_state["_cookie_rejected"] = True    # don't sign straight back in
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
        if backend.mode == "gsheets" and user.is_owner:
            st.link_button("📄 Open Google Sheet", backend.sheet_url(), width="stretch",
                           help="Indent_Lines = every version of every indent; "
                                "Change_Log = edit history per indent")
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
        st.caption(f"Google Sheet data refreshes every {config.master_cache_seconds() // 60} min "
                   "(or now with ↻ Refresh data)")


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
    st.session_state["_set_cookie"] = True  # old sign-in tokens end with the old PIN
    st.success("PIN updated.")
