# utils/styles.py
"""
样式管理模块：统一管理所有CSS样式
"""
import streamlit as st


def load_chat_styles():
    """加载聊天界面样式"""
    st.markdown("""
        <style>
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
        
        /* 用户消息卡片：浅蓝色背景，深蓝色文字 - 使用多种选择器确保匹配 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"],
        div[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"],
        [data-testid="stChatMessage"][data-testid="stChatMessage/user"] [data-testid="stChatMessageContent"],
        .stChatMessage:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
            background: #E3F2FD !important;
            color: #1976D2 !important;
            padding: 10px 16px !important;
            border-radius: 12px !important;
            margin: 0 !important;
            word-wrap: break-word !important;
            line-height: 1.5 !important;
            border: none !important;
        }
        
        /* 确保所有子元素文字颜色正确 - 使用通配符 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] *,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] p,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] div,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] span,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] strong {
            color: #1976D2 !important;
        }
        
        /* 直接针对用户消息的markdown内容 */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) .stMarkdown,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) .stMarkdown p,
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) .stMarkdown div {
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
        </style>
    """, unsafe_allow_html=True)


def load_info_box_styles():
    """加载信息提示框样式"""
    st.markdown("""
        <style>
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
        </style>
    """, unsafe_allow_html=True)


def load_all_styles():
    """加载所有样式"""
    load_chat_styles()
    load_info_box_styles()

