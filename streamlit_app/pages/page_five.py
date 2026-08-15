# pages/page_five.py
"""
文档问答页面：支持即时上传文档并基于文档回答
类似ChatGPT的文件上传功能，不经过向量库，即时解析
聊天格式，输入框右侧加号上传，自动解析，持续对话
"""
import _project_root  # noqa: F401

import streamlit as st
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import HumanMessage, AIMessage
from utils.instant_document_loader import parse_document_instant, combine_documents
from utils.api_config import get_current_config
from utils.conversation_storage import hydrate_doc_qa_session, save_doc_qa_messages
from services.llm_factory import build_chat_llm
from utils.styles import load_all_styles
from utils.token_tracker import track_token_usage

# 加载样式
load_all_styles()

# ------------------- 页面标题 -------------------
st.markdown("# 📄 文档问答")

# ------------------- 初始化会话状态 -------------------
hydrate_doc_qa_session(st.session_state)

if "uploaded_documents" not in st.session_state:
    st.session_state.uploaded_documents = []

if st.session_state.doc_qa_messages and not st.session_state.uploaded_documents:
    st.caption("💡 已恢复上次保存的对话文字；若需再次基于文件问答，请重新上传文档。")

if "parsed_file_names" not in st.session_state:
    st.session_state.parsed_file_names = set()

if "llm_temperature" not in st.session_state:
    st.session_state.llm_temperature = 0.0

# ------------------- 初始化LLM -------------------
def get_llm_instance():
    """获取LLM实例（每次调用都使用最新的温度设置）"""
    try:
        get_current_config()
    except Exception as e:
        st.error(f"LLM初始化失败: {str(e)}")
        st.info("请前往「模型设置」页面配置API")
    return build_chat_llm(st.session_state.llm_temperature)

# ------------------- 文件上传处理（自动解析） -------------------
# 使用popover创建上传按钮
with st.popover("➕ 上传文档", help="点击上传文档（最多5个），上传后自动解析"):
    st.markdown("### 📎 上传文档")
    st.caption("最多上传5个文件，上传后自动解析")
    
    uploaded_files = st.file_uploader(
        "选择文件",
        type=["pdf", "txt", "docx", "doc", "md", "xlsx", "xls"],
        accept_multiple_files=True,
        key="doc_qa_file_uploader",
        label_visibility="collapsed"
    )
    
    # 自动解析新上传的文件
    if uploaded_files:
        # 限制文件数量
        if len(uploaded_files) > 5:
            st.error(f"⚠️ 最多5个文件，已截取前5个")
            uploaded_files = uploaded_files[:5]
        
        # 检查是否有新文件需要解析
        new_files = [f for f in uploaded_files if f.name not in st.session_state.parsed_file_names]
        
        if new_files:
            with st.spinner(f"正在自动解析 {len(new_files)} 个文件..."):
                parsed_docs_list = list(st.session_state.uploaded_documents)
                success_count = 0
                failed_files = []
                
                for file in new_files:
                    try:
                        docs = parse_document_instant(file)
                        if docs:
                            parsed_docs_list.append(docs)
                            st.session_state.parsed_file_names.add(file.name)
                            success_count += 1
                        else:
                            failed_files.append((file.name, "解析失败或内容为空"))
                    except Exception as e:
                        failed_files.append((file.name, str(e)))
                
                if parsed_docs_list:
                    st.session_state.uploaded_documents = parsed_docs_list
                    if success_count > 0:
                        st.success(f"✅ 成功解析 {success_count} 个文件")
                        if failed_files:
                            st.warning(f"⚠️ {len(failed_files)} 个文件解析失败")
                            for file_name, error in failed_files:
                                st.caption(f"❌ {file_name}: {error}")
                        st.rerun()
                else:
                    st.error("❌ 没有成功解析任何文件")
                    for file_name, error in failed_files:
                        st.error(f"**{file_name}**: {error}")
        else:
            # 显示已解析的文件
            st.info("所有文件已解析")
            for file in uploaded_files:
                if file.name in st.session_state.parsed_file_names:
                    st.caption(f"✅ {file.name}")

# 使用CSS将popover按钮定位到输入框右侧
st.markdown("""
    <style>
    /* 将上传按钮定位到输入框右侧 */
    div[data-testid="stPopover"] {
        position: fixed !important;
        right: 2rem !important;
        bottom: 1.5rem !important;
        z-index: 1000 !important;
    }
    
    /* 调整popover按钮样式 */
    button[data-testid="baseButton-secondary"]:has-text("➕") {
        background: transparent !important;
        border: none !important;
        font-size: 24px !important;
        padding: 8px 12px !important;
    }
    </style>
""", unsafe_allow_html=True)

# ------------------- 聊天界面 -------------------
# 显示对话历史
if len(st.session_state.doc_qa_messages) == 0:
    with st.chat_message("assistant"):
        if st.session_state.uploaded_documents:
            doc_names = []
            for doc_list in st.session_state.uploaded_documents:
                if doc_list:
                    doc_names.append(doc_list[0].metadata.get("source_file", "未知文件"))
            st.markdown(f"📚 **已加载 {len(doc_names)} 个文档，可以开始提问了！**")
            for name in doc_names:
                st.caption(f"  • {name}")
        else:
            st.markdown("您好！我可以帮您分析上传的文档。请点击输入框右侧的 ➕ 按钮上传文档（最多5个），上传后会自动解析。")

# 显示历史消息
for message in st.session_state.doc_qa_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        # 显示来源信息
        if message.get("metadata", {}).get("sources"):
            with st.expander("📚 参考文档", expanded=False):
                for source in message["metadata"]["sources"]:
                    st.caption(f"📄 {source}")

# 显示已上传的文档信息（如果有）
if st.session_state.uploaded_documents and len(st.session_state.doc_qa_messages) > 0:
    doc_names = []
    for doc_list in st.session_state.uploaded_documents:
        if doc_list:
            doc_names.append(doc_list[0].metadata.get("source_file", "未知文件"))
    
    if st.button("🗑️ 清除所有文档", key="clear_docs_btn"):
        st.session_state.uploaded_documents = []
        st.session_state.doc_qa_messages = []
        st.session_state.doc_qa_chat_history = []
        st.session_state.parsed_file_names = set()
        save_doc_qa_messages([])
        st.rerun()

# 用户输入框
user_input = st.chat_input(
    placeholder="💬 请输入您的问题...",
    key="doc_qa_chat_input"
)

# ------------------- 处理用户输入 -------------------
if user_input:
    # 检查是否有文档
    if not st.session_state.uploaded_documents:
        with st.chat_message("assistant"):
            st.warning("⚠️ 请先上传文档。点击输入框右侧的 ➕ 按钮上传文档，上传后会自动解析。")
    else:
        # 添加用户消息
        st.session_state.doc_qa_messages.append({
            "role": "user",
            "content": user_input
        })
        
        # 合并所有文档内容
        combined_text = combine_documents(st.session_state.uploaded_documents)
        
        # 构建提示词（支持持续对话）
        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一个基于文档的智能问答助手。

【任务】：
根据用户上传的文档内容，准确回答用户的问题。支持多轮对话，可以基于之前的对话上下文进行回答。

【规则】：
1. 只使用文档中提供的信息来回答问题
2. 如果文档中没有相关信息，明确告知用户
3. 回答要准确、简洁、有条理
4. 可以引用文档中的具体内容，但不要编造信息
5. 如果涉及多个文档，请综合所有文档的信息
6. 在后续对话中，可以引用之前提到的内容，保持对话连贯性

【文档内容】：
{context}"""),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}")
        ])
        
        # 生成回答
        with st.chat_message("assistant"):
            try:
                llm = get_llm_instance()
                # 直接调用LLM以获取token使用信息
                with st.spinner("🤔 正在思考..."):
                    messages = qa_prompt.format_messages(
                        context=combined_text,
                        chat_history=st.session_state.doc_qa_chat_history,
                        input=user_input
                    )
                    response = llm.invoke(messages)
                    # 提取并记录token使用
                    track_token_usage(response, call_type="doc_qa")
                    # 获取文本内容
                    answer = response.content if hasattr(response, 'content') else str(response)
                
                st.markdown(answer)
                
                # 保存AI回答
                doc_names = []
                for doc_list in st.session_state.uploaded_documents:
                    if doc_list:
                        doc_names.append(doc_list[0].metadata.get("source_file", "未知文件"))
                
                st.session_state.doc_qa_messages.append({
                    "role": "assistant",
                    "content": answer,
                    "metadata": {
                        "sources": doc_names
                    }
                })
                
                # 更新对话历史（用于持续对话）
                st.session_state.doc_qa_chat_history.extend([
                    HumanMessage(content=user_input),
                    AIMessage(content=answer)
                ])
                
            except Exception as e:
                error_msg = f"⚠️ 生成回答时出错：{str(e)}"
                st.error(error_msg)
                st.session_state.doc_qa_messages.append({
                    "role": "assistant",
                    "content": error_msg
                })
        save_doc_qa_messages(st.session_state.doc_qa_messages)
        st.rerun()

# 无 st.rerun() 的交互轮次也落盘（例如仅浏览页面）
save_doc_qa_messages(st.session_state.doc_qa_messages)
