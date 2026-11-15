"""MT Indent: entry point. Sign-in gate and sidebar navigation."""
import streamlit as st

st.set_page_config(page_title="MT Indent", page_icon="🧾", layout="wide")

from pages_src import access, common, home, indent, login, my_indents, po_upload, production, tracker  # noqa: E402

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

pages = {
    "home": st.Page(lambda: home.render(user), title="Home", icon="🏠", url_path="home",
                    default=user.makes_indents),
    "indent": st.Page(lambda: indent.render(user), title="Create indent", icon="📝", url_path="indent"),
    "my_indents": st.Page(lambda: my_indents.render(user), title="All indents" if user.is_owner else "My indents",
                          icon="📋", url_path="indents"),
    "po": st.Page(lambda: po_upload.render(user), title="Upload PO", icon="📤", url_path="upload-po"),
    "tracker": st.Page(lambda: tracker.render(user), title="Hourly tracker", icon="⏱️", url_path="tracker"),
    "production": st.Page(lambda: production.render(user), title="Production sheet", icon="🏭",
                          url_path="production", default=not user.makes_indents),
    "batching": st.Page(lambda: production.render_batching(user), title="Batching sheet", icon="📦",
                        url_path="batching"),
    "city_sku": st.Page(lambda: production.render_city_sku(user), title="City / SKU report", icon="📊",
                        url_path="city-sku-report"),
}
if user.is_owner:
    pages["access"] = st.Page(lambda: access.render(user), title="Access", icon="🔑", url_path="access")
common.PAGES.clear()
common.PAGES.update(pages)

# Sales: indents + PO.  Warehouse: production + batching.  Owner: everything.
sections = {}
if user.makes_indents:
    sections["Indents"] = [pages["home"], pages["indent"], pages["my_indents"], pages["po"], pages["tracker"]]
if user.sees_production:
    sections["Production"] = [pages["production"], pages["batching"], pages["city_sku"]]
    if not user.makes_indents:
        sections["Production"].append(pages["tracker"])
if user.is_owner:
    sections["Admin"] = [pages["access"]]
nav = st.navigation(sections)
common.sidebar(user)
nav.run()
