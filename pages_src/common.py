"""Shared UI helpers: styling, flash messages, signed-in user, sidebar."""
from __future__ import annotations

import streamlit as st

from core import auth, config, indents, masters
from core.sheets import SheetError, get_backend
from core.schema import role_name

ACCENT = "#0b57d0"   # 27 Nov: Material look (was green #1c6b49)

# Filled in by app.py so pages can call st.switch_page(PAGES["indent"]).
PAGES: dict[str, object] = {}

_CSS = f"""
<style>
  /* Tabular numbers everywhere numbers line up */
  [data-testid="stMetricValue"], [data-testid="stDataFrame"], [data-testid="stTable"],
  .num {{ font-variant-numeric: tabular-nums; }}
  .block-container, [data-testid="stMainBlockContainer"] {{ padding-top: 3.6rem; padding-bottom: 3rem; }}
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
  .mt-num {{ color: rgba(49,51,63,.45); font-size:.72rem; margin-right:.45rem; font-variant-numeric: tabular-nums; }}

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

  .mt-id {{ font-size:.82rem; white-space:nowrap; font-variant-numeric: tabular-nums; }}
  /* Upload PO button on Home: blue, next to the green Create indent */
  .st-key-home_po_btn button {{ background:#0d2c4f !important; border-color:#2f81f7 !important; color:#fff !important; }}
  .st-key-home_po_btn button:hover {{ background:#164a80 !important; }}

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
  /* ---- Home: one compact row per customer ---- */
  .mt-crow {{ display:flex; align-items:center; gap:.8rem; flex-wrap:wrap; padding:.5rem .8rem;
             border:1px solid #e3e8e5; border-left:5px solid #e3b341; border-radius:10px; margin:.35rem 0;
             background:#fff; }}
  .mt-crow.done {{ border-left-color:#2da44e; }}
  .mt-crow .who {{ min-width:190px; }}
  .mt-crow .cnt {{ font-size:.85rem; color:#57606a; min-width:120px; }}
  .mt-crow .cnt .g {{ color:#1a7f37; font-weight:600; }} .mt-crow .cnt .y {{ color:#9a6700; font-weight:600; }}
  .mt-crow .chips {{ flex:1; }}
  .mt-legend {{ margin:.2rem 0 .1rem; }}

  /* ---- Home: one line per customer ---- */
  .mt-line {{ display:flex; align-items:center; gap:.6rem; padding:.45rem .7rem; margin:0 0 .35rem;
             border:1px solid #e3e8e5; border-left:5px solid #e3b341; border-radius:10px; background:#fff;
             white-space:nowrap; min-height:38px; }}
  .mt-line.done {{ border-left-color:#2da44e; }}
  .mt-line .nm {{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; }}
  .mt-line .ct {{ color:#6e7781; font-size:.85rem; }}
  .mt-line .cnt {{ color:#57606a; font-size:.82rem; font-variant-numeric:tabular-nums; }}
  .mt-line .st {{ border-radius:999px; padding:.15rem .6rem; font-size:.8rem; font-weight:600; }}
  .mt-line .st.done {{ background:#dafbe1; color:#116329; border:1px solid #4ac26b; }}
  .mt-line .st.open {{ background:#fff8c5; color:#7d4e00; border:1px solid #d4a72c; }}
  .mt-tiles.k3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom:.5rem; }}
  .mt-h {{ font-size:1.4rem; font-weight:700; line-height:1.15; white-space:nowrap; }}
  .mt-h span {{ display:block; font-size:.78rem; font-weight:400; color:#6e7781; margin-top:2px; }}
  .st-key-mtbar_home {{ margin-bottom:.35rem; }}
  .st-key-mtbar_home [data-testid="stButtonGroup"] {{ margin:0; }}
  .st-key-mtbar_home [role="radiogroup"]:has(> button[data-variant="segmented_control"]) {{ overflow:visible; }}
  .st-key-mtbar_home button[data-variant="segmented_control"] {{ white-space:nowrap; padding:.42rem .8rem !important; }}
  .st-key-mtbar_home .stButton button {{ min-height:2.6rem; }}
  .mt-bar {{ margin:.1rem 0 .7rem !important; }}

  /* ---- cards (Home "Indents to act on", Upload PO, items on phone) ---- */
  [class*="st-key-mtcard"] {{ border-radius:14px !important; }}
  .mt-card-head {{ font-size:1rem; line-height:1.4; margin-bottom:.15rem; }}
  .mt-card-head .mt-badge, .mt-card-head span[class*="badge"] {{ margin-left:.3rem; }}
  [class*="st-key-mtcard"] [data-testid="stHorizontalBlock"] {{ flex-wrap:nowrap !important; gap:.5rem; }}
  [class*="st-key-mtcard"] [data-testid="stColumn"] {{ min-width:0 !important; flex:1 1 0 !important; width:auto !important; }}
  [class*="st-key-mtmob"] {{ display:none !important; }}

  /* ---- phones ---- */
  @media (max-width: 640px) {{
    .block-container, [data-testid="stMainBlockContainer"] {{ padding:3.4rem .7rem 3rem !important; }}
    h3 {{ font-size:1.35rem !important; }}
    .mt-tiles {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap:8px; }}
    .mt-tile {{ padding:.6rem .75rem; border-radius:12px; }}
    .mt-tile .val {{ font-size:1.3rem; }}
    .mt-tile .sub {{ font-size:.72rem; }}
    .mt-tile:last-child:nth-child(odd) {{ grid-column: span 2; }}
    .mt-tiles.k3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); gap:6px; }}
    .mt-tiles.k3 .mt-tile {{ grid-column:auto; padding:.45rem .55rem; }}
    .mt-tiles.k3 .mt-tile .lbl {{ font-size:.72rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
    .mt-tiles.k3 .mt-tile .val {{ font-size:1.2rem; }}
    .mt-tiles.k3 .mt-tile .sub {{ display:none; }}
    /* Home title row: title on its own line, the two buttons side by side under it */
    .st-key-mtbar_home [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap !important; gap:.4rem !important; }}
    .st-key-mtbar_home [data-testid="stColumn"]:nth-child(-n+2) {{ flex:1 1 100% !important; min-width:100% !important; }}
    .st-key-mtbar_home [data-testid="stColumn"]:first-child {{ padding-bottom:.6rem; }}
    .st-key-mtbar_home {{ margin-bottom:0; }}
    .mt-h {{ font-size:1.3rem; display:block; margin-bottom:.15rem; }}
    .mt-h span {{ display:inline; margin-left:.35rem; }}
    .st-key-mtbar_home [data-testid="stColumn"]:nth-child(n+3) {{ flex:1 1 0 !important; min-width:0 !important; width:auto !important; }}
    .mt-line {{ padding:.4rem .55rem; gap:.4rem; }}
    .mt-line .cnt {{ display:none; }}
    button[data-variant="pills"] {{ padding:.35rem .8rem !important; min-height:2.1rem; font-size:.9rem; }}
    [role="radiogroup"]:has(> button[data-variant="segmented_control"]) {{ max-width:100%; overflow-x:auto; }}
    button[data-variant="segmented_control"] {{ padding:.4rem .75rem !important; white-space:nowrap; }}
    .mt-cust {{ padding:.6rem .7rem; }}
    .mt-chip {{ font-size:.78rem; }}
    [class*="st-key-mtdesk"] {{ display:none !important; }}
    [class*="st-key-mtmob"] {{ display:block !important; }}
    [data-testid="stTabs"] button[role="tab"] {{ padding:.4rem .5rem; font-size:.9rem; }}
  }}
</style>
"""


# 27 Nov (user): "G - Material, mail-style" look. Styling only: colours, shapes and type.
# It comes after _CSS and only overrides how things look; no rule here hides, moves or
# resizes anything, so taking this block out of inject_css() gives the old look back.
_THEME_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap');
  @import url('https://fonts.googleapis.com/css2?family=Google+Sans+Flex:wght@400..700&display=swap');
  @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap');
  /* "G - Material, mail-style" look, colours and shapes as in the mockup (user 27 Nov 11:16 PM). */
  :root { --g-bg:#f0f4f9; --g-on:#1f1f1f; --g-ov:#444746; --g-out:#747775; --g-olv:#c4c7c5; --g-p:#0b57d0;
      --g-pc:#d3e3fd; --g-opc:#041e49; --g-sc:#c2e7ff; --g-osc:#001d35; --g-sch:#e9eef6; --g-hov:#f2f6fc; }

  /* ---- page: grey-blue ground, the content on one white rounded sheet ---- */
  .stApp { background: var(--g-bg) !important; font-family: 'Google Sans', 'Google Sans Flex', 'Roboto', system-ui, sans-serif; }
  [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stMain"] { background: transparent !important; }
  .block-container, [data-testid="stMainBlockContainer"] { background: #ffffff; border-radius: 24px; }
  .stApp button, .stApp input, .stApp textarea, [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] li, [data-testid="stWidgetLabel"] p,
  .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .mt-h { font-family: 'Google Sans', 'Google Sans Flex', 'Roboto', system-ui, sans-serif; }
  .stApp h1, .stApp h2, .stApp h3, .mt-h { font-weight: 400 !important; }
  .mt-muted, .mt-h span, [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
      color: var(--g-ov) !important; opacity: 1 !important; }

  /* ---- side menu: on the ground colour, current page as a pale blue pill ---- */
  [data-testid="stSidebar"] { background: var(--g-bg) !important; border-right: 0; }
  [data-testid="stSidebar"] > div, [data-testid="stSidebarContent"] { background: transparent !important; }
  [data-testid="stSidebarNav"] a { border-radius: 999px; }
  [data-testid="stSidebarNav"] a[aria-current="page"] { background: var(--g-pc) !important; }
  [data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--g-opc) !important; font-weight: 700; }

  /* ---- buttons: pills; blue filled, pale blue tonal ---- */
  .stButton button, .stDownloadButton button, .stFormSubmitButton button, [data-testid="stLinkButton"] a {
      border-radius: 999px !important; font-weight: 500;
      transition: transform .4s cubic-bezier(.34,1.56,.64,1), box-shadow .2s ease; }
  .stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {
      box-shadow: 0 1px 2px rgba(0,0,0,.3), 0 1px 3px 1px rgba(0,0,0,.15); }
  .stButton button:active, .stDownloadButton button:active, .stFormSubmitButton button:active { transform: scale(.94); }
  [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"] {
      background: var(--g-sc) !important; border: 1px solid transparent !important; }
  [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondary"] *,
  [data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stBaseButton-secondaryFormSubmit"] * { color: var(--g-osc) !important; }
  .st-key-home_po_btn button { background: var(--g-sc) !important; border-color: transparent !important; }
  .st-key-home_po_btn button, .st-key-home_po_btn button * { color: var(--g-osc) !important; }
  .st-key-home_po_btn button:hover { background: #b3dcf7 !important; }

  /* ---- chips (customers, stores, cities): outlined, 8 px corners, pale blue when chosen ---- */
  button[data-variant="pills"] { background: transparent !important; color: var(--g-ov) !important;
      border: 1px solid var(--g-out) !important; border-radius: 8px !important; box-shadow: none !important;
      font-weight: 500 !important; min-height: 2rem; transition: transform .4s cubic-bezier(.34,1.56,.64,1), background .2s ease; }
  button[data-variant="pills"]:hover:not([aria-disabled="true"]):not(:disabled) {
      transform: none; box-shadow: none !important; background: var(--g-hov) !important; border-color: var(--g-out) !important; }
  button[data-variant="pills"]:active { transform: scale(.93); }
  button[data-variant="pills"][aria-checked="true"] { background: var(--g-sc) !important; color: var(--g-osc) !important;
      border: 1px solid var(--g-sc) !important; box-shadow: none !important; }

  /* ---- day switch: outlined pill, pale blue chosen half ---- */
  [role="radiogroup"]:has(> button[data-variant="segmented_control"]) { background: transparent;
      border: 1px solid var(--g-out); border-radius: 20px; box-shadow: none; padding: 0; overflow: hidden; }
  button[data-variant="segmented_control"] { border-radius: 999px !important; color: var(--g-ov) !important; font-weight: 500 !important; }
  button[data-variant="segmented_control"]:hover { background: var(--g-hov) !important; color: var(--g-on) !important; }
  button[data-variant="segmented_control"][aria-checked="true"] { background: var(--g-sc) !important; color: var(--g-osc) !important; }

  /* ---- tiles: flat tonal cards ---- */
  .mt-tile, .mt-tile.info, .mt-tile.good, .mt-tile.warn, .mt-tile.bad { background: var(--g-sch); color: var(--g-on);
      border: 0; border-radius: 16px; box-shadow: none; }
  .mt-tile .lbl, .mt-tile .sub { color: var(--g-ov); font-weight: 500; }
  .mt-tile .val, .mt-tile.good .val, .mt-tile.warn .val, .mt-tile.bad .val, .mt-tile.info .val {
      color: var(--g-on); font-weight: 400; font-family: 'Google Sans', 'Google Sans Flex', 'Roboto', system-ui, sans-serif; }

  /* ---- rows: list lines on the sheet, not cards ---- */
  .mt-line, .mt-crow { border: 0; border-bottom: 1px solid var(--g-sch); border-radius: 12px; background: transparent;
      box-shadow: none; transition: background .2s ease, box-shadow .2s ease; }
  .mt-line.done, .mt-crow.done { border-left-color: transparent; }
  .mt-line:hover, .mt-crow:hover { background: var(--g-hov); box-shadow: 0 1px 2px rgba(0,0,0,.3), 0 1px 3px 1px rgba(0,0,0,.15); }
  .mt-line .st, .mt-chip { border-radius: 8px; font-weight: 500; }
  .mt-line .st.done, .mt-chip.done { background: #c4eed0; color: #072711; border-color: transparent; }
  .mt-line .st.open, .mt-chip.open { background: #ffdf99; color: #3d2e00; border-color: transparent; }
  .mt-chip.none { background: var(--g-sch); color: var(--g-ov); border-color: transparent; }
  .mt-chip.cnl { background: #f9dedc; color: #601410; border-color: transparent; }
  .mt-line .ct, .mt-line .cnt, .mt-crow .cnt { color: var(--g-ov); }
  .mt-bar { background: var(--g-sch); }
  .mt-strip { border-color: var(--g-olv); background: var(--g-sch); border-radius: 16px; }
  .mt-strip b { color: var(--g-p); }
  .mt-cust, [class*="st-key-mtcard"], .st-key-mt_delivery_card { background: #ffffff;
      border-color: var(--g-olv) !important; border-radius: 16px !important; box-shadow: none; }

  /* ---- Streamlit's own boxes ---- */
  [data-testid="stExpander"] details { border-radius: 16px; background: #ffffff; border-color: var(--g-olv); }
  [data-testid="stDataFrame"], [data-testid="stTable"] { border-radius: 12px; overflow: hidden; }
  [data-testid="stAlert"] { border-radius: 16px; }
  [data-testid="stFileUploaderDropzone"] { border-radius: 16px; background: #ffffff; border: 1px dashed var(--g-out); }
  [data-testid="stDialog"] div[role="dialog"] { border-radius: 28px; }
  [data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
      border-radius: 4px !important; border-color: var(--g-out) !important; }
  [data-testid="stForm"] { background: #ffffff; border: 1px solid var(--g-olv) !important; border-radius: 28px; }
  [data-testid="stSidebar"] [data-testid="stForm"] { background: transparent; border: 0 !important; }

  /* ---- tables the app draws itself (hourly tracker, st.table): mail-list rows.
     Taller rows, faint lines, the whole row lights up under the pointer. ---- */
  .stApp table.tk, .stApp [data-testid="stTable"] table { font-family: 'Google Sans', 'Google Sans Flex', 'Roboto', system-ui, sans-serif;
      font-size: 14px; border-collapse: collapse; }
  .stApp table.tk th, .stApp [data-testid="stTable"] th { font-weight: 500; color: var(--g-ov); background: #ffffff;
      padding: 10px 10px; border: 0; border-bottom: 1px solid var(--g-sch); }
  .stApp table.tk td, .stApp [data-testid="stTable"] td { padding: 10px 10px; border: 0; border-bottom: 1px solid var(--g-sch);
      transition: background .15s ease; }
  .stApp table.tk tr:hover td, .stApp [data-testid="stTable"] tr:hover td { background: var(--g-hov);
      box-shadow: inset 0 1px 0 #dadce0, inset 0 -1px 0 #dadce0; }
  .stApp table.tk tr.c0 td { background: var(--g-hov); color: var(--g-on); font-weight: 700; font-size: 15px; }
  .stApp table.tk tr.c1 td { background: #ffffff; color: var(--g-on); font-weight: 700; }
  .stApp table.tk td.po { border-left: 1px solid var(--g-sch); }
  .stApp table.tk .m { color: var(--g-out); }
  .stApp table.tk .ok { background: #c4eed0; color: #072711; border-radius: 8px; padding: 2px 8px; }
  .stApp table.tk .bad { background: #f9dedc; color: #601410; border-radius: 8px; padding: 2px 8px; }

  @media (max-width: 640px) { .block-container, [data-testid="stMainBlockContainer"] { border-radius: 0; } }
  @media (prefers-reduced-motion: reduce) { .stButton button, button[data-variant="pills"] { transition: none !important; } }
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS + _THEME_CSS, unsafe_allow_html=True)


def numbered(df):
    """An item number (#) as the first column (core.production_calc.numbered)."""
    from core.production_calc import numbered as _n
    return _n(df)


def num_label(n: int, text: str) -> str:
    """Small muted item number before a name: '1  Apple'."""
    from html import escape
    return f"<span class='mt-num'>{n}</span>{escape(str(text))}"


def hide_nav_links(paths: list[str]) -> None:
    """Hide the sidebar entries of the redirect-only pages (old addresses, /signin)."""
    if not paths:
        return
    sel = ", ".join(f'[data-testid="stSidebarNav"] li:has(a[href$="/{p}"])' for p in paths)
    st.html(f"<style>{sel} {{display: none !important;}}</style>")


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
    cls = {"Frozen": "frz", "Locked": "frz", "Cancelled": "cnl"}.get(status, "sub")
    return f'<span class="mt-badge {cls}">{status}</span>'


# ---------------------------------------------------------------- flash

def flash(kind: str, text: str) -> None:
    """Queue a message shown at the top of the next page render."""
    st.session_state.setdefault("_flash", []).append((kind, text))


def day_input(box, key: str, label: str = "Date"):
    """Date picker of the Option 2 pages. 27 Nov (user): the date chosen on one page is the date the next
    page opens on (Pre-Production Actual -> Production Detail Process -> Summary -> Dispatch -> Returns),
    so back-dated entry does not fall back to today. A new sign-in starts on today."""
    from core import config
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get("o2_day") or config.now_ist().date()
    day = box.date_input(label, key=key, format="DD/MM/YYYY")
    st.session_state["o2_day"] = day
    return day


def show_flash() -> None:
    for kind, text in st.session_state.pop("_flash", []):
        getattr(st, kind, st.info)(text)


# ---------------------------------------------------------------- user

COOKIE = "mt_indent_session"


LS_KEY = "mt_indent_session"
QP = "s"   # one-time query parameter used to hand the stored sign-in to the server


def _set_cookie(value: str, max_age: int) -> None:
    """Remember (or forget, with max_age=0) the sign-in in this browser: a
    cookie, plus localStorage because some hosts (Streamlit Cloud) do not pass
    browser cookies through to the app."""
    import json
    st.html(
        "<script>(function(){"
        f"const v={json.dumps(value)}, age={int(max_age)};"
        f"document.cookie={json.dumps(COOKIE + '=')}+v+'; path=/; max-age='+age+'; SameSite=Lax'"
        "+(location.protocol==='https:'?'; Secure':'');"
        f"try{{ if(v && age>0) localStorage.setItem({json.dumps(LS_KEY)}, JSON.stringify({{t:v, exp:Date.now()+age*1000}}));"
        f" else localStorage.removeItem({json.dumps(LS_KEY)}); }}catch(e){{}}"
        "})();</script>",
        unsafe_allow_javascript=True, width=1)


def restore_login_script() -> None:
    """On the sign-in page: if this browser holds a stored sign-in, reload once
    with it in the URL so the server can sign the user back in."""
    if st.session_state.get("_cookie_rejected"):
        return
    import json
    st.html(
        "<script>(function(){try{"
        f"const raw=localStorage.getItem({json.dumps(LS_KEY)}); if(!raw) return;"
        "const o=JSON.parse(raw); if(!o.t || !o.exp || o.exp < Date.now()){"
        f"localStorage.removeItem({json.dumps(LS_KEY)}); return;}}"
        f"const u=new URL(window.location.href); if(u.searchParams.has({json.dumps(QP)})) return;"
        f"u.searchParams.set({json.dumps(QP)}, o.t); window.location.replace(u.toString());"
        "}catch(e){}})();</script>",
        unsafe_allow_javascript=True, width=1)


def remember_login(user: auth.User) -> None:
    """Called once after sign-in: keep the browser signed in."""
    st.session_state["_set_cookie"] = True


def flush_cookie() -> None:
    """Write / clear the stored sign-in on this run if asked (needs a rendered page)."""
    s = st.session_state
    if s.pop("_clear_cookie", False):
        _set_cookie("", 0)
    if s.pop("_set_cookie", False) and s.get("user"):
        try:
            token = auth.make_session_token(masters.load_masters().access, s["user"]["email"])
        except SheetError:
            return
        _set_cookie(token, max(1, auth.session_token_expiry(token) - int(__import__("time").time())))


def _query_token() -> str | None:
    try:
        tok = st.query_params.get(QP)
        if tok:
            del st.query_params[QP]   # never leave the token in the address bar
        return tok or None
    except Exception:
        return None


def _cookie_token() -> str | None:
    try:
        return st.context.cookies.get(COOKIE)
    except Exception:
        return None


def _from_cookie() -> auth.User | None:
    qtok = _query_token()
    token = qtok or _cookie_token()
    if not token or (st.session_state.get("_cookie_rejected") and not qtok):
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
    # the stored sign-in keeps its original expiry: the PIN is asked again after session_hours
    state.restore_from_sheet(user.email)   # the draft is back on Create indent; no banner
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
        st.markdown(f"**{user.label}**  \n<span class='mt-muted'>{user.email} · {role_name(user.role)}</span>",
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
