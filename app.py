"""MT Indent: entry point. Sign-in gate and sidebar navigation."""
import os
import sys
import time
import types

import streamlit as st


def _drop_stale_modules() -> None:
    """After a redeploy, Streamlit Cloud re-runs this file but may keep older
    copies of core/* and pages_src/* in memory (e.g. an old User class).
    If any app module's file changed since it was loaded, forget them all so
    they are imported fresh, together, on this run."""
    root = os.path.dirname(os.path.abspath(__file__))
    reg = sys.modules.get("_mt_loaded")
    first = reg is None              # first run of this version of app.py in this process
    if first:
        reg = types.ModuleType("_mt_loaded")
        reg.times = {}
        sys.modules["_mt_loaded"] = reg
    # list(...) copies the keys: other sessions may import modules at the same moment
    names = [n for n in list(sys.modules) if n.split(".")[0] in ("core", "pages_src")]
    now = time.time()
    stale = first and bool(names)
    for name in names:
        path = getattr(sys.modules.get(name), "__file__", "") or ""
        if name not in reg.times:    # imported later in a run (inside a function)
            reg.times[name] = now
            continue
        try:
            stale = stale or not path.startswith(root) or os.path.getmtime(path) > reg.times[name]
        except OSError:
            stale = True
    if stale:
        for name in names:
            sys.modules.pop(name, None)
        reg.times = {}


def _remember_modules() -> None:
    reg = sys.modules["_mt_loaded"]
    now = time.time()
    for name in list(sys.modules):
        if name.split(".")[0] in ("core", "pages_src"):
            reg.times.setdefault(name, now)


_drop_stale_modules()

st.set_page_config(page_title="MT Indent", page_icon="🧾", layout="wide")

from core import config as _config  # noqa: E402
if _config.trial_copy():
    if _config.sheet_id() == _config.LIVE_SHEET_ID:
        st.error("Trial copy is pointing at the LIVE Google Sheet. Change sheet_id in the secrets "
                 "to the trial sheet. Nothing runs until then.")
        st.stop()
    st.markdown("<div style='background:#FFF4D6;border:1px solid #E8C25A;border-radius:6px;"
                "padding:4px 10px;font-size:0.85rem'>🧪 <b>TRIAL COPY</b> · separate sheet · "
                "no e-mails · no dispatch-sheet sync</div>", unsafe_allow_html=True)

from pages_src import access, common, home, indent, login, my_indents, po_upload, production, tracker  # noqa: E402
from pages_src import delivery_times  # noqa: E402   (Bulk indents page removed 21 Nov)

_remember_modules()

# Hourly e-mail trigger: GitHub Actions opens the app with ?hourly=run every hour
# 8 AM-2 PM. This only sends what the schedule would send anyway (never forced:
# outside the window it does nothing, and each hour goes out once - Mail_Log).
if st.query_params.get("hourly") == "run":
    from core import hourly as _hourly
    try:
        _res = _hourly.run()
        _txt = "; ".join(f"{r['status']} {r['to']} {r.get('detail', '')}".strip() for r in _res)
    except Exception as _e:  # noqa: BLE001 - reported back to the workflow log
        _txt = f"error {type(_e).__name__}: {_e}"
    from core import dispatch_sync as _ds
    _txt = (_txt or "nothing to do") + f" | dispatch sheet: {_ds.sync()}"
    st.text(f"HOURLY-RESULT: {_txt}")
    st.stop()

common.inject_css()
common.connection_banner()


@st.cache_resource(show_spinner=False)
def _views_once() -> bool:
    """After a redeploy: rebuild the Indent_vs_PO / Indent_Changes tabs once (background)."""
    from core import sheet_views
    sheet_views.refresh_soon()
    return True


_views_once()
# every address the app has ever had: signed out they show the sign-in form, signed in an
# address this user has no page for goes to his first page (no "Page not found", 21 Nov)
GATE_PATHS = ("home", "indent", "bulk-indents", "delivery-times", "upload-po", "tracker", "indents", "production",
              "batching", "city-sku-report", "access", "preprod-actual", "batching-plan",
              "dispatch", "returns", "dispatch-check", "return-grading")
user = common.current_user()
common.flush_cookie()

if user is None:
    common.restore_login_script()
    # every page address shows the sign-in form (no "Page not found" after a refresh),
    # and once signed in the user lands on the page they were on
    gate = [st.Page(login.render, title="Sign in", icon="🔐", url_path="login", default=True)]
    for path in ("signin",) + GATE_PATHS:   # the default page only answers "/", so /signin needs its own
        gate.append(st.Page(lambda: login.render(), title="Sign in", icon="🔐", url_path=path))
    st.navigation(gate, position="hidden").run()
    st.stop()

# from the plain role text, so the menu never depends on newer User properties
_role = str(getattr(user, "role", "") or "").lower()
makes_indents = _role != "warehouse"
sees_production = _role in ("owner", "owner_full", "warehouse")

pages = {
    "home": st.Page(lambda: home.render(user), title="Home", icon="🏠", url_path="home",
                    default=makes_indents),
    "indent": st.Page(lambda: indent.render(user), title="Create indent", icon="📝", url_path="indent"),
    "my_indents": st.Page(lambda: my_indents.render(user), title="All indents" if user.is_owner else "My indents",
                          icon="📋", url_path="indents"),
    "po": st.Page(lambda: po_upload.render(user), title="Upload PO", icon="📤", url_path="upload-po"),
    "tracker": st.Page(lambda: tracker.render(user), title="Hourly tracker", icon="⏱️", url_path="tracker"),
    "production": st.Page(lambda: production.render(user), title="Production sheet", icon="🏭",
                          url_path="production", default=not makes_indents),
    "batching": st.Page(lambda: production.render_batching(user), title="Batching sheet", icon="📦",
                        url_path="batching"),
}
if user.opens_access:
    pages["access"] = st.Page(lambda: access.render(user), title="Access", icon="🔑", url_path="access")
if user.is_owner:
    pages["times"] = st.Page(lambda: delivery_times.render(user), title="Delivery times", icon="🕒",
                             url_path="delivery-times")
common.PAGES.clear()
common.PAGES.update(pages)

# Sales: indents + PO.  Warehouse: production, batching, hourly tracker.  Owner: everything.
sections = {}
if makes_indents:
    sections["Indents"] = [pages["home"], pages["indent"], pages["my_indents"], pages["po"]]
if sees_production:   # owner and warehouse; sales do not get production or the hourly tracker
    sections["Production"] = [pages["production"], pages["batching"], pages["tracker"]]
if user.is_owner:
    sections["Admin"] = ([pages["access"]] if "access" in pages else []) + [pages["times"]]
landing = pages["home"] if makes_indents else pages["production"]
URLS = {"home": "home", "indent": "indent", "my_indents": "indents", "po": "upload-po",
        "tracker": "tracker", "production": "production", "batching": "batching", "access": "access",
        "times": "delivery-times"}
in_menu = [pg for group in sections.values() for pg in group]
shown = {URLS[k] for k, pg in pages.items() if any(pg is q for q in in_menu)}   # addresses the menu already uses
_away = [x for x in ("signin", "login") + GATE_PATHS if x not in shown]
last = list(sections)[-1]
sections[last] = sections[last] + [st.Page(lambda: st.switch_page(landing), title=f"go {x}", url_path=x)
                                   for x in _away]
common.hide_nav_links(_away)
nav = st.navigation(sections, expanded=True)
common.sidebar(user)
nav.run()
