"""Streamlit 本地个人部署入口（知识库在 data/streamlit/，与线上 Web 用户隔离）。"""
import _project_root  # noqa: F401 — 必须在首屏 import utils/config 之前

import streamlit as st
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent

st.set_page_config(
    page_title=" RAG知识库问答系统",
    layout="wide",
    initial_sidebar_state="expanded",
)

from utils.conversation_storage import init_conversations_if_needed

init_conversations_if_needed(st.session_state)

import utils.ui_utils
import utils.styles

utils.ui_utils.load_custom_css()
utils.styles.load_all_styles()

st.markdown("# RAG知识库问答系统")

pg = st.navigation(
    [
        st.Page(str(_APP_DIR / "pages" / "page_one.py"), title="知识库问答"),
        st.Page(str(_APP_DIR / "pages" / "page_five.py"), title="文档问答"),
        st.Page(str(_APP_DIR / "pages" / "page_two.py"), title="知识库管理"),
        st.Page(str(_APP_DIR / "pages" / "page_three.py"), title="监控台"),
        st.Page(str(_APP_DIR / "pages" / "page_four.py"), title="模型设置"),
    ],
    position="sidebar",
)

pg.run()
