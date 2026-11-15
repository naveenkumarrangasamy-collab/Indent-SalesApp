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
    names = [n for n in sys.modules if n.split(".")[0] in ("core", "pages_src")]
    now = time.time()
    stale = first and bool(names)
    for name in names:
        path = getattr(sys.modules[name], "__file__", "") or ""
        if name not in reg.times:    # imported later in a run (inside a function)
            reg.times[name] = now
            continue
        try:
            stale = stale or not path.startswith(root) or os.path.getmtime(path) > reg.times[name]
        except OSError:
            stale = True
    if stale:
        for name in names:
            del sys.modules[name]
        reg.times = {}


def _remember_modules() -> None:
    reg = sys.modules["_mt_loaded"]
    now = time.time()
    for name in sys.modules:
        if name.split(".")[0] in ("core", "pages_src"):
            reg.times.setdefault(name, now)


_drop_stale_modules()

st.set_page_config(page_title="MT Indent", page_icon="🧾", layout="wide")

from pages_src import access, common, home, indent, login, my_indents, po_upload, production, tracker  # noqa: E402

_remember_modules()

common.inject_css()
common.connection_banner()
user = common.current_user()
common.flush_cookie()

if user is None:
    common.restore_login_script()
    # every page address shows the sign-in form (no "Page not found" after a refresh),
    # and once signed in the user lands on the page they were on
    gate = [st.Page(login.render, title="Sign in", icon="🔐", url_path="signin", default=True)]
    for path in ("home", "indent", "upload-po", "tracker", "indents", "production", "batching",
                 "city-sku-report", "access"):
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
if user.is_owner:
    pages["access"] = st.Page(lambda: access.render(user), title="Access", icon="🔑", url_path="access")
common.PAGES.clear()
common.PAGES.update(pages)

# Sales: indents + PO.  Warehouse: production, batching, hourly tracker.  Owner: everything.
sections = {}
if makes_indents:
    sections["Indents"] = [pages["home"], pages["indent"], pages["my_indents"], pages["po"]]
if sees_production:   # owner and warehouse; sales do not get production or the hourly tracker
    sections["Production"] = [pages["production"], pages["batching"], pages["tracker"]]
if user.is_owner:
    sections["Admin"] = [pages["access"]]
nav = st.navigation(sections)
common.sidebar(user)
nav.run()
