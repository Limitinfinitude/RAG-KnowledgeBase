import streamlit as st

# ------------------- 页面配置 -------------------
st.set_page_config(
    page_title=" RAG知识库问答系统",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 加载自定义CSS
import utils.ui_utils
utils.ui_utils.load_custom_css()

# ------------------- 主标题 -------------------
st.markdown("# 🛡️ RAG知识库问答系统")

# ------------------- 导航 -------------------
pg = st.navigation(
    [
        st.Page("pages/page_one.py", title="智能问答", icon="💬"),
        st.Page("pages/page_two.py", title="知识库管理", icon="📂"),
    ],
    position="sidebar"
)

pg.run()
