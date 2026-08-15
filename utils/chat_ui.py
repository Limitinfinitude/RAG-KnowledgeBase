# utils/chat_ui.py
"""
聊天界面组件模块：统一管理聊天相关的UI组件
"""
import streamlit as st
from datetime import datetime

from utils.ui_utils import safe_similarity_ratio


def render_chat_history():
    """渲染聊天历史 - 简约左右对话 + 头像"""
    chat_container = st.container()
    with chat_container:
        # 初始欢迎消息
        if len(st.session_state.messages) == 0:
            with st.chat_message("assistant"):
                st.markdown("您好，我是基于文档的智能问答助手。您可以直接提问，我会从知识库中检索相关信息来回答您。")

        # 显示历史消息 - 使用st.chat_message显示头像
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    # 用户消息：直接应用浅蓝色背景
                    st.markdown(f"""
                        <div style="background: #E3F2FD; color: #1976D2; padding: 10px 16px; border-radius: 12px; line-height: 1.5;">
                            {message["content"]}
                        </div>
                    """, unsafe_allow_html=True)
                else:
                    # AI消息：显示内容和溯源信息
                    st.markdown(message["content"])
                    
                    # 如果有证据级溯源信息，显示实际引用的来源
                    metadata = message.get("metadata", {})
                    if metadata.get("evidence_sources"):
                        with st.expander("📚 证据级溯源（实际引用来源）", expanded=False):
                            st.caption("显示回答中实际引用的文档片段")
                            for source in metadata["evidence_sources"]:
                                idx = source.get("index", 0)
                                score_float = safe_similarity_ratio(source.get("score", 0.0))
                                score_pct = int(score_float * 100)

                                # 分数颜色
                                if score_float > 0.7:
                                    score_color = "#34c759"
                                elif score_float > 0.5:
                                    score_color = "#ff9500"
                                else:
                                    score_color = "#8e8e93"
                                
                                chunk_level = source.get("chunk_level", "medium")
                                level_label = {"small": "精确", "medium": "段落", "large": "章节", "summary": "摘要"}.get(chunk_level, "")
                                
                                st.markdown(f"""
                                    <div style="padding: 12px 14px; margin: 8px 0; border-radius: 8px; background-color: #f0f9ff; border-left: 4px solid #3b82f6;">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                            <span style="font-size: 0.9rem; color: #1e40af; font-weight: 600;">[来源{idx}] {source.get('file', '未知')}</span>
                                            <span style="font-size: 0.75rem; color: {score_color}; font-weight: 500; background: white; padding: 2px 8px; border-radius: 12px;">{score_pct}%</span>
                                        </div>
                                        <div style="font-size: 0.85rem; color: #1e293b; line-height: 1.6; background: white; padding: 10px; border-radius: 6px; margin: 8px 0;">
                                            {source.get('content', '')}
                                        </div>
                                        <div style="font-size: 0.7rem; color: #64748b; margin-top: 6px;">
                                            {level_label} | 相似度：{score_pct}%
                                        </div>
                                    </div>
                                """, unsafe_allow_html=True)

    return chat_container


def render_chat_input():
    """渲染聊天输入框"""
    st.divider()
    user_input = st.chat_input(
        placeholder="💬 请输入您的问题...",
        key="chat_input"
    )

    return user_input


def render_header():
    """渲染页面头部"""
    from utils.api_config import get_current_config
    
    try:
        api_config = get_current_config()
        config_name = st.session_state.get("current_api_config", "DeepSeek")
        model_name = api_config.get("model", "未设置")
        has_key = bool(api_config.get("api_key"))
        model_status = "🟢 已配置" if has_key else "🟡 未配置"
    except:
        config_name = "未配置"
        model_name = "未设置"
        model_status = "🟡 未配置"
    
    col_header_left, col_header_right = st.columns([3, 1])
    with col_header_left:
        st.markdown(f"""
            <div class="info-box">
                <strong>当前时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 
                <strong>知识库状态：</strong>已加载 | 
                <strong>模型：</strong>{config_name} ({model_name})
            </div>
        """, unsafe_allow_html=True)

    with col_header_right:
        st.markdown(f"""
            <div style="text-align: right; margin-top: 2rem;">
                <span style="background-color: #e8f4f8; padding: 8px 16px; border-radius: 20px; font-weight: 600;">
                    {model_status}
                </span>
            </div>
        """, unsafe_allow_html=True)

