# utils/ui_utils.py
"""
基础UI工具模块：管理基础布局和通用样式
"""
import streamlit as st


def safe_similarity_ratio(score) -> float:
    """将相似度/score 规范为 0~1 的 float；JSON 中的字符串或异常值不会触发 str*int 重复。"""
    try:
        if score is None:
            return 0.0
        x = float(score)
        if x != x:
            return 0.0
        return max(0.0, min(1.0, x))
    except (TypeError, ValueError):
        return 0.0


def setup_page_config():
    """设置页面基础配置"""
    st.set_page_config(
        page_title="RAG知识库问答系统",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded"
    )


def load_custom_css():
    """加载基础CSS样式"""
    # 加载基础布局样式
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

        /* --- 聊天组件：简约左右对话 + 头像 --- */
        
        /* 聊天消息基础样式 */
        .stChatMessage {
            margin-bottom: 0.75rem !important;
            padding: 0 !important;
            background: transparent !important;
        }
        
        /* 用户消息容器：强制右对齐 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            display: flex !important;
            justify-content: flex-end !important;
            align-items: flex-start !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        
        /* 用户消息内部容器：头像在右侧 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) > div {
            display: flex !important;
            flex-direction: row-reverse !important;
            align-items: flex-start !important;
            gap: 10px !important;
            max-width: 75% !important;
            margin-left: auto !important;
            margin-right: 0 !important;
        }
        
        /* 用户消息卡片：浅蓝色背景，深蓝色文字 - 使用更具体的选择器 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
            background: #E3F2FD !important;
            color: #1976D2 !important;
            padding: 10px 16px !important;
            border-radius: 12px !important;
            margin: 0 !important;
            word-wrap: break-word !important;
            line-height: 1.5 !important;
            border: none !important;
        }
        
        /* 确保所有子元素文字颜色正确 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] p,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] div,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] span {
            color: #1976D2 !important;
        }
        
        /* 用户头像样式 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="chatAvatarIcon-user"] {
            width: 36px !important;
            height: 36px !important;
            flex-shrink: 0 !important;
            margin: 0 !important;
        }
        
        /* 助手消息：左对齐，头像在左侧 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            display: flex !important;
            flex-direction: row !important;
            align-items: flex-start !important;
        }
        
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) > div {
            display: flex !important;
            flex-direction: row !important;
            align-items: flex-start !important;
            gap: 10px !important;
            max-width: 80% !important;
        }
        
        /* 助手消息卡片：简约灰色 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] {
            background: #f5f5f5 !important;
            color: #1d1d1f !important;
            padding: 12px 16px !important;
            border-radius: 12px !important;
            margin: 0 !important;
            word-wrap: break-word !important;
            line-height: 1.6 !important;
            border: none !important;
        }
        
        /* 助手头像样式 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="chatAvatarIcon-assistant"] {
            width: 36px !important;
            height: 36px !important;
            flex-shrink: 0 !important;
            margin: 0 !important;
        }
        
        /* 自定义消息卡片（用于历史记录） */
        .user-message-card {
            background: #E3F2FD;
            color: #1976D2;
            padding: 10px 16px;
            border-radius: 12px;
            margin-left: auto;
            margin-right: 0;
            max-width: 70%;
            margin-bottom: 8px;
            word-wrap: break-word;
            line-height: 1.5;
        }
        
        .assistant-message-card {
            background: #f5f5f5;
            color: #1d1d1f;
            padding: 12px 16px;
            border-radius: 12px;
            max-width: 75%;
            margin-bottom: 8px;
            word-wrap: break-word;
            line-height: 1.6;
        }

        /* --- 装饰性组件：简约 --- */
        .stExpander {
            background-color: #fafafa !important;
            border: 1px solid #e5e5e5 !important;
            border-radius: 8px !important;
            margin: 8px 0 !important;
        }
        
        .stExpander summary {
            font-size: 0.9rem !important;
            color: #666 !important;
            padding: 10px 12px !important;
        }

        .stFileUploader {
            background-color: #f8fafc !important;
            border: 2px dashed #cbd5e1 !important;
            border-radius: 10px !important;
        }

        /* 自定义提示框：简约风格 */
        .info-box {
            padding: 10px 14px;
            background: #f5f5f5;
            border-radius: 8px;
            margin: 8px 0;
            font-size: 0.85rem;
            color: #666;
            border: none;
        }

        .success-box {
            padding: 10px 14px;
            background: #f0f9f4;
            border-radius: 8px;
            margin: 8px 0;
            font-size: 0.85rem;
            color: #2d8659;
        }
        
        .warning-box {
            padding: 10px 14px;
            background: #fff8e6;
            border-radius: 8px;
            margin: 8px 0;
            font-size: 0.85rem;
            color: #b8860b;
        }

        .debug-info {
            background-color: #fafafa;
            color: #666;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-family: 'SF Mono', Monaco, monospace;
            border: 1px solid #e5e5e5;
            margin: 6px 0;
        }
        
        /* 检索状态标签：简约 */
        .status-tag {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 500;
        }
        
        .status-tag.rag {
            background: #e8f0fe;
            color: #1a73e8;
        }
        
        .status-tag.chat {
            background: #f3e5f5;
            color: #7b1fa2;
        }
        </style>
    """, unsafe_allow_html=True)