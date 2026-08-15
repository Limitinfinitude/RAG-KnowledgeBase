# utils/sidebar_ui.py
"""
侧边栏UI组件模块：统一管理侧边栏相关组件
"""
import streamlit as st
from utils.conversation_storage import save_conversations
from utils.metadata_manager import get_categories


def render_knowledge_base_selector():
    """渲染知识库选择器"""
    st.markdown("### 知识库选择")
    
    # 获取所有知识库
    try:
        knowledge_bases = get_categories()
    except Exception:
        knowledge_bases = ["默认知识库"]
    
    # 初始化session_state
    if "selected_kb" not in st.session_state:
        st.session_state.selected_kb = "全部知识库"
    
    # 知识库选择下拉框
    selected_kb = st.selectbox(
        "选择知识库",
        ["全部知识库"] + knowledge_bases,
        index=0 if st.session_state.selected_kb == "全部知识库" 
              else (knowledge_bases.index(st.session_state.selected_kb) + 1 
                    if st.session_state.selected_kb in knowledge_bases else 0),
        key="kb_selector_sidebar",
        label_visibility="visible"
    )
    
    # 更新session_state
    st.session_state.selected_kb = selected_kb
    
    # 显示当前选择
    st.caption(f"当前：**{selected_kb}**")
    
    return selected_kb


def render_conversation_management():
    """渲染对话管理侧边栏"""
    st.markdown("### 对话管理")
    
    # 新建对话
    if st.button("新建对话", use_container_width=True, type="primary"):
        new_name = f"对话 {len(st.session_state.conversations) + 1}"
        st.session_state.conversations[new_name] = {"messages": [], "chat_history": [], "metadata": {}}
        st.session_state.current_conversation = new_name
        st.session_state.messages = []
        st.session_state.chat_history = []
        # 保存到文件
        save_conversations(st.session_state.conversations)
        st.rerun()
    
    st.markdown("---")
    
    # 对话列表
    conv_names = list(st.session_state.conversations.keys())
    if conv_names:
        for conv_name in conv_names:
            is_active = conv_name == st.session_state.current_conversation
            
            col_left, col_right = st.columns([4, 1])
            with col_left:
                if st.button(
                    conv_name,
                    key=f"switch_{conv_name}",
                    width="stretch",
                    type="primary" if is_active else "secondary"
                ):
                        if not is_active:
                            # 先保存当前对话
                            st.session_state.conversations[st.session_state.current_conversation] = {
                                "messages": st.session_state.messages,
                                "chat_history": st.session_state.chat_history,
                                "metadata": st.session_state.conversations[st.session_state.current_conversation].get("metadata", {})
                            }
                            save_conversations(st.session_state.conversations)
                            
                            # 切换到新对话
                            st.session_state.current_conversation = conv_name
                            current_conv = st.session_state.conversations[conv_name]
                            st.session_state.messages = current_conv.get("messages", [])
                            st.session_state.chat_history = current_conv.get("chat_history", [])
                            st.rerun()

            with col_right:
                with st.popover("⋮", width="stretch"):
                    st.markdown(f"**{conv_name}**")

                    new_name = st.text_input("重命名", value=conv_name, key=f"rename_{conv_name}")
                    if st.button("💾 保存", key=f"save_rename_{conv_name}"):
                        if new_name.strip() and new_name != conv_name:
                            if new_name not in st.session_state.conversations:
                                st.session_state.conversations[new_name] = st.session_state.conversations.pop(conv_name)
                                if st.session_state.current_conversation == conv_name:
                                    st.session_state.current_conversation = new_name
                                # 保存到文件
                                save_conversations(st.session_state.conversations)
                                st.success("重命名成功")
                                st.rerun()
                            else:
                                st.error("名称已存在")
                        else:
                            st.warning("名称未改变或为空")

                    if st.button("🗑️ 删除", type="secondary", key=f"delete_{conv_name}"):
                        if len(st.session_state.conversations) > 1:
                            del st.session_state.conversations[conv_name]
                            if st.session_state.current_conversation == conv_name:
                                new_current = next(iter(st.session_state.conversations))
                                st.session_state.current_conversation = new_current
                                current_conv = st.session_state.conversations[new_current]
                                st.session_state.messages = current_conv.get("messages", [])
                                st.session_state.chat_history = current_conv.get("chat_history", [])
                            # 保存到文件
                            save_conversations(st.session_state.conversations)
                            st.success("已删除")
                            st.rerun()
                        else:
                            st.error("不能删除最后一个对话")

                    if st.button("📌 置顶", key=f"pin_{conv_name}"):
                        if conv_name != conv_names[0]:
                            items = list(st.session_state.conversations.items())
                            pinned = [(conv_name, st.session_state.conversations[conv_name])]
                            others = [i for i in items if i[0] != conv_name]
                            st.session_state.conversations = dict(pinned + others)
                            # 保存到文件
                            save_conversations(st.session_state.conversations)
                            st.success("已置顶")
                            st.rerun()

            st.markdown("<hr style='margin: 10px 0; border: none; border-top: 1px solid #e2e8f0;'>", unsafe_allow_html=True)
    else:
        st.info("暂无对话，点击上方按钮创建")


def render_search_mode_settings():
    """渲染检索模式设置"""
    st.markdown("---")
    st.markdown("### 检索模式")
    
    # 初始化检索模式
    if "search_mode" not in st.session_state:
        st.session_state.search_mode = "vector"  # 默认向量检索
    
    search_mode = st.radio(
        "选择检索模式",
        options=["vector", "hybrid"],
        format_func=lambda x: {
            "vector": "🔍 向量检索（快速）",
            "hybrid": "🔀 混合检索（BM25+向量，更准确）"
        }[x],
        index=0 if st.session_state.search_mode == "vector" else 1,
        key="search_mode_radio"
    )
    st.session_state.search_mode = search_mode
    
    if search_mode == "hybrid":
        st.info("""
        **混合检索（Hybrid Search）**：
        - 结合BM25关键词检索和向量语义检索
        - 使用RRF算法融合结果
        - 适合专有名词、产品型号等场景
        - 首次使用需要构建BM25索引
        """)
        
        # 检查BM25索引是否存在
        import os
        from utils.path_context import get_kb_dir

        bm25_index_file = os.path.join(get_kb_dir(), "bm25_index.pkl")
        if not os.path.exists(bm25_index_file):
            st.warning("⚠️ BM25索引不存在，首次检索时会自动构建（可能需要一些时间）")
    else:
        st.caption("使用纯向量检索，速度快，适合语义理解")


def render_reranker_settings():
    """渲染重排序设置"""
    st.markdown("---")
    st.markdown("### 重排序设置")
    enable_reranker = st.checkbox(
        "启用模型重排序",
        value=st.session_state.get("enable_reranker", False),
        key="enable_reranker_checkbox"
    )
    st.session_state.enable_reranker = enable_reranker
    
    if enable_reranker:
        st.info("""
        **本地 CrossEncoder 重排序**：
        - 模型：BAAI/bge-reranker-base
        - 位置：`models/bge-reranker-base_local/`
        - 在主进程中直接加载，速度快
        """)
    else:
        st.caption("关闭后，直接使用向量检索结果，不进行重排序")


def render_web_search_settings():
    """联网检索（供应商由 Web 管理端 `system_settings` 或本机 config / 环境变量决定）。"""
    st.markdown("---")
    st.markdown("### 联网检索")
    if "enable_web_search" not in st.session_state:
        st.session_state.enable_web_search = False
    en = st.checkbox(
        "开启联网（网页摘要）",
        value=st.session_state.enable_web_search,
        key="enable_web_search_checkbox",
        help="在知识库检索后追加公开网页摘要；与本地文档冲突时以知识库为准。",
    )
    st.session_state.enable_web_search = en
    provider = "bocha"
    try:
        from utils.web_system_settings import get_web_search_provider

        provider = get_web_search_provider()
    except Exception:
        pass
    try:
        from utils.web_system_settings import (
            get_bocha_api_key_resolved,
            get_brave_api_key_resolved,
            get_qianfan_api_key_resolved,
        )

        if provider == "bocha":
            has_key = bool(get_bocha_api_key_resolved())
        elif provider == "baidu":
            has_key = bool(get_qianfan_api_key_resolved())
        else:
            has_key = bool(get_brave_api_key_resolved())
    except Exception:
        has_key = False
    st.caption(
        f"当前供应商：**{provider}**（bocha / baidu / brave；Web 端在管理后台「高级参数」修改）"
    )
    if en and not has_key:
        st.warning(
            f"已开启联网，但未配置 **{provider}** 对应密钥："
            "Web 部署请在管理端「高级参数」填写；Streamlit 本地可用环境变量 "
            "**BOCHA_API_KEY** / **QIANFAN_API_KEY** / **BRAVE_SEARCH_API_KEY** 或 `config.py` 中对应项。"
        )
    elif en:
        st.caption("密钥勿提交 Git；推荐用环境变量或管理端保存。")


def render_model_settings_link():
    """渲染模型设置快捷入口"""
    st.markdown("---")
    st.markdown("### 模型设置")
    
    # 显示当前配置
    from utils.api_config import get_current_config
    try:
        current_config = get_current_config()
        config_name = st.session_state.get("current_api_config", "DeepSeek")
        st.caption(f"当前：**{config_name}**")
        st.caption(f"模型：{current_config.get('model', '未设置')}")
        
        if not current_config.get("api_key"):
            st.warning("⚠️ API Key未设置")
    except:
        st.caption("当前：未配置")
    
    # 快捷跳转按钮
    if st.button("⚙️ 前往模型设置", use_container_width=True, type="secondary"):
        st.switch_page("pages/page_four.py")


def render_temperature_settings():
    """渲染温度设置"""
    st.markdown("---")
    st.markdown("### 模型温度")
    
    # 初始化温度设置
    if "llm_temperature" not in st.session_state:
        st.session_state.llm_temperature = 0.0
    
    # 温度滑块
    temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=2.0,
        value=st.session_state.llm_temperature,
        step=0.1,
        help="控制输出的随机性。0.0=确定性输出，2.0=高度随机",
        key="temperature_slider"
    )
    
    st.session_state.llm_temperature = temperature
    
    # 温度说明
    if temperature == 0.0:
        st.caption("🔒 确定性模式（最适合事实性问答）")
    elif temperature < 0.5:
        st.caption("📊 低随机性（适合技术文档）")
    elif temperature < 1.0:
        st.caption("💡 中等随机性（平衡准确性和创造性）")
    else:
        st.caption("🎨 高随机性（适合创意内容）")

