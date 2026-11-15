"""MT Indent: entry point. Sign-in gate and sidebar navigation."""
import streamlit as st

st.set_page_config(page_title="MT Indent", page_icon="🧾", layout="wide")

from pages_src import access, common, home, indent, login, my_indents, po_upload, production  # noqa: E402

common.inject_css()
common.connection_banner()
user = common.current_user()
common.flush_cookie()

if user is None:
    st.navigation([st.Page(login.render, title="Sign in", icon="🔐", url_path="signin", default=True)],
                  position="hidden").run()
    st.stop()

pages = {
    "home": st.Page(lambda: home.render(user), title="Home", icon="🏠", url_path="home", default=True),
    "indent": st.Page(lambda: indent.render(user), title="Create indent", icon="📝", url_path="indent"),
    "po": st.Page(lambda: po_upload.render(user), title="Upload PO", icon="📤", url_path="upload-po"),
    "my_indents": st.Page(lambda: my_indents.render(user), title="All indents" if user.is_owner else "My indents",
                          icon="📋", url_path="indents"),
    "production": st.Page(lambda: production.render(user), title="Production sheet", icon="🏭",
                          url_path="production"),
    "city_sku": st.Page(lambda: production.render_city_sku(user), title="City / SKU report", icon="📊",
                        url_path="city-sku-report"),
}
if user.is_owner:
    pages["access"] = st.Page(lambda: access.render(user), title="Access", icon="🔑", url_path="access")
common.PAGES.clear()
common.PAGES.update(pages)

sections = {"Indents": [pages["home"], pages["indent"], pages["po"], pages["my_indents"]],
            "Production": [pages["production"], pages["city_sku"]]}
if user.is_owner:
    sections["Admin"] = [pages["access"]]
nav = st.navigation(sections)
common.sidebar(user)
nav.run()
