"""MT Indent: entry point. Sign-in gate and sidebar navigation."""
import streamlit as st

st.set_page_config(page_title="MT Indent", page_icon="🧾", layout="wide")

from pages_src import access, common, indent, login, my_indents, production  # noqa: E402

common.inject_css()
user = common.current_user()

if user is None:
    st.navigation([st.Page(login.render, title="Sign in", icon="🔐", url_path="signin", default=True)],
                  position="hidden").run()
    st.stop()

pages = {
    "indent": st.Page(lambda: indent.render(user), title="Indent", icon="📝",
                      url_path="indent", default=True),
    "my_indents": st.Page(lambda: my_indents.render(user), title="All indents" if user.is_owner else "My indents",
                          icon="📋", url_path="indents"),
    "production": st.Page(lambda: production.render(user), title="Production sheet", icon="🏭",
                          url_path="production"),
}
if user.is_owner:
    pages["access"] = st.Page(lambda: access.render(user), title="Access", icon="🔑", url_path="access")
common.PAGES.clear()
common.PAGES.update(pages)

nav = st.navigation(list(pages.values()))
common.sidebar(user)
nav.run()
