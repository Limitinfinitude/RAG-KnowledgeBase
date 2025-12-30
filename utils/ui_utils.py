# ui_utils.py
import os
import shutil
import streamlit as st
from datetime import datetime
from config import DB_DIR
from utils.file_loader import ingest_file

def setup_page_config():
    """设置页面基础配置"""
    st.set_page_config(
        page_title="RAG知识库问答系统",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded"
    )


def load_custom_css():
    """加载自定义CSS样式 - 修复侧边栏按钮消失问题"""

    st.markdown("""
        <style>
        /* --- 基础布局修复 --- */

        /* 关键：不要隐藏整个 Header，否则展开按钮会消失 */
        [data-testid="stHeader"] {
            background-color: rgba(255, 255, 255, 0) !important; /* 透明背景 */
            color: #1a1a1a !important;
            height: 3rem !important;
        }

        /* 主内容区顶格，但预留按钮位 */
        .block-container {
            padding-top: 2rem !important;
            padding-bottom: 1rem !important;
            max-width: 95% !important;
        }

        /* 全局背景 */
        .stApp { 
            background-color: #ffffff;
        }

        /* --- 侧边栏样式 --- */
        .stSidebar {
            background-color: #ffffff !important;
            border-right: 1px solid #e5e7eb;
            z-index: 100;
        }

        /* --- 标题与文字 --- */
        h1, h2, h3 {
            color: #1a1a1a !important;
            font-weight: 600;
            margin-top: 0.5rem !important;
        }

        /* --- 按钮样式优化 --- */
        .stButton > button {
            background-color: white !important;
            color: #262730 !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 8px !important;
            padding: 8px 16px !important;
            font-weight: 500 !important;
            transition: all 0.2s ease !important;
            width: 100%;
            text-align: left;
        }

        /* 按钮悬停 */
        .stButton > button:hover {
            background-color: #f5f7fa !important;
            border-color: #cbd5e1 !important;
            box-shadow: 0 2px 6px rgba(0,0,0,0.08) !important;
        }

        /* 高亮按钮（如当前选中状态） */
        .stButton > button[kind="primary"] {
            background-color: #f0f4f8 !important;
            color: #2563eb !important;
            border-color: #2563eb !important;
            font-weight: 600 !important;
        }

        /* --- 聊天组件 --- */
        .stChatMessage {
            margin-bottom: 0.5rem !important;
            border-radius: 10px !important;
        }

        .stChatMessage[data-testid="stChatMessage/user"] {
            background-color: #f0f9ff !important;
        }

        .stChatMessage[data-testid="stChatMessage/assistant"] {
            background-color: #ffffff !important;
            border: 1px solid #e5e7eb !important;
        }

        /* --- 装饰性组件 --- */
        .stExpander {
            background-color: white !important;
            border: 1px solid #e5e7eb !important;
            border-radius: 10px !important;
        }

        .stFileUploader {
            background-color: #f8fafc !important;
            border: 2px dashed #cbd5e1 !important;
            border-radius: 10px !important;
        }

        /* 自定义提示框盒模型 */
        .info-box {
            padding: 15px;
            background-color: #f0f9ff;
            border-left: 4px solid #3b82f6;
            border-radius: 4px;
            margin: 10px 0;
        }

        .success-box {
            padding: 15px;
            background-color: #f0fdf4;
            border-left: 4px solid #22c55e;
            border-radius: 4px;
        }

        .debug-info {
            background-color: #f8fafc;
            color: #64748b;
            padding: 10px;
            border-radius: 8px;
            font-size: 0.85rem;
            font-family: monospace;
        }
        </style>
    """, unsafe_allow_html=True)


def render_header():
    """渲染页面头部"""
    col_header_left, col_header_right = st.columns([3, 1])
    with col_header_left:
        st.markdown(f"""
            <div class="info-box">
                <strong>当前时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 
                <strong>知识库状态：</strong>已加载 | 
                <strong>模型模式：</strong>{st.session_state.get('model_mode', 'API 调用 (OpenAI)')}
            </div>
        """, unsafe_allow_html=True)

    with col_header_right:
        # 模型状态指示器
        model_status = "🟢 已连接" if st.session_state.get('model_mode') else "🟡 未配置"
        st.markdown(f"""
            <div style="text-align: right; margin-top: 2rem;">
                <span style="background-color: #e8f4f8; padding: 8px 16px; border-radius: 20px; font-weight: 600;">
                    {model_status}
                </span>
            </div>
        """, unsafe_allow_html=True)


def render_chat_input():
    st.divider()
    col1, col2 = st.columns([1, 12])

    with col1:
        if st.button("⚙️", key="settings_btn", type="secondary"):
            model_settings_dialog()  # 直接调用，会自动弹窗！

    with col2:
        user_input = st.chat_input(
            placeholder="💬 请输入您的问题...",
            key="chat_input"
        )

    return user_input
def render_chat_history():
    """渲染聊天历史"""
    chat_container = st.container()
    with chat_container:
        # 初始欢迎消息
        if len(st.session_state.messages) == 0:
            with st.chat_message("assistant"):
                st.markdown("""
                    👋 您好！ RAG 知识库问答助手。
                    - 您可以上传文档到知识库，我会基于文档内容回答问题
                """)

        # 显示历史消息
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    return chat_container

@st.dialog("模型设置", width="large")
def model_settings_dialog():
    """模型设置弹窗（使用 @st.dialog，实现真正独立的弹窗）"""
    import streamlit as st
    import requests

    st.markdown("<h2 style='text-align: center;'>🧠 模型调用配置</h2>", unsafe_allow_html=True)
    st.markdown("---")

    # 主模式选择
    mode = st.radio(
        "选择调用模式",
        ["API 调用 (OpenAI)", "本地调用 (Ollama)"],
        index=0 if st.session_state.model_mode == "API 调用 (OpenAI)" else 1,
        horizontal=True
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        st.markdown("**当前选择：**")
    with col2:
        st.markdown(f"<strong style='color:#2563eb; font-size:1.2rem;'>{mode}</strong>", unsafe_allow_html=True)

    st.markdown("---")

    base_url = st.session_state.get('ollama_base_url', "http://localhost:11434")
    model_name = st.session_state.get('ollama_model', "qwen2.5:7b")

    if mode == "本地调用 (Ollama)":
        with st.container(border=True):
            st.subheader("🔧 Ollama 服务配置")

            base_url = st.text_input(
                "服务地址",
                value=base_url,
                placeholder="http://localhost:11434",
                help="确保 Ollama 已启动"
            )

            models = ["qwen2.5:7b"]
            if st.button("🔄 刷新可用模型", type="secondary"):
                with st.spinner("连接中..."):
                    try:
                        url = base_url.rstrip('/') + '/api/tags'
                        resp = requests.get(url, timeout=8)
                        if resp.status_code == 200:
                            data = resp.json()
                            models = [m['name'] for m in data.get('models', [])]
                            st.success(f"检测到 {len(models)} 个模型")
                        else:
                            st.error("连接失败")
                    except:
                        st.error("无法连接 Ollama，请检查地址和网络")

            if len(models) > 1:
                model_name = st.selectbox("选择模型", models)
            else:
                model_name = st.text_input("模型名称", value=model_name)

    else:
        st.info("当前为 OpenAI API 模式，无需本地配置")
        st.caption("模型、密钥、地址请在 config.py 中设置")

    st.markdown("---")

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 保存并应用", type="primary", width="stretch"):
            st.session_state.model_mode = mode
            st.session_state.ollama_base_url = base_url
            st.session_state.ollama_model = model_name
            st.success("✅ 配置保存成功！")
            st.rerun()
    with col_cancel:
        if st.button("❌ 取消", width="stretch"):
            st.rerun()

    # 配置预览
    with st.expander("📋 当前配置预览"):
        st.json({
            "调用模式": st.session_state.model_mode,
            "Ollama地址": st.session_state.get('ollama_base_url', '未设置'),
            "Ollama模型": st.session_state.get('ollama_model', '未设置')
        })