# pages/page_one.py
import streamlit as st
import time
import requests
from datetime import datetime
from typing import Optional

# 导入模块化UI
import utils.ui_utils

# ------------------- 子页面加载自定义CSS（关键！） -------------------
utils.ui_utils.load_custom_css()  # ← 必须加这一行，让子页面也有样式

# ------------------- 导入核心模块 -------------------
from config import *
from utils.embedding import get_embeddings, get_reranker
from utils.db import get_vector_db
from langchain_openai import ChatOpenAI
from langchain_community.llms import Ollama
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

# ------------------- 会话状态初始化 -------------------
if "model_mode" not in st.session_state:
    st.session_state.model_mode = "API 调用 (OpenAI)"
    st.session_state.ollama_base_url = "http://localhost:11434"
    st.session_state.ollama_model = "qwen2.5:7b"

if "conversations" not in st.session_state:
    st.session_state.conversations = {
        "默认对话": {"messages": [], "chat_history": []}
    }
if "current_conversation" not in st.session_state:
    st.session_state.current_conversation = "默认对话"

# 当前对话快捷引用
current_conv = st.session_state.conversations[st.session_state.current_conversation]
st.session_state.messages = current_conv["messages"]
st.session_state.chat_history = current_conv["chat_history"]

# ------------------- 加载核心引擎 -------------------
@st.cache_resource
def load_engines():
    embeddings = get_embeddings()
    reranker = get_reranker()
    vector_db = get_vector_db(embeddings)
    return vector_db, reranker

vector_db, reranker = load_engines()

# ------------------- 侧边栏：对话管理（类 Grok 专业版） -------------------
with st.sidebar:
    st.markdown("### 对话管理")

    # 新建对话按钮
    if st.button("➕ 新建对话", use_container_width=True, key="new_conversation_btn", type="secondary"):
        new_name = f"新对话 {len(st.session_state.conversations) + 1}"
        st.session_state.conversations[new_name] = {"messages": [], "chat_history": []}
        st.session_state.current_conversation = new_name
        st.rerun()

    st.markdown("---")

    # 你的对话（可折叠）
    with st.expander("你的对话", expanded=True):
        if st.session_state.conversations:
            conv_names = list(st.session_state.conversations.keys())

            for conv_name in conv_names:
                col_left, col_right = st.columns([6, 1])

                with col_left:
                    is_active = st.session_state.current_conversation == conv_name
                    if st.button(
                        conv_name,
                        key=f"switch_{conv_name}",
                        use_container_width=True,
                        type="primary" if is_active else "secondary"
                    ):
                        if not is_active:
                            st.session_state.current_conversation = conv_name
                            current_conv = st.session_state.conversations[conv_name]
                            st.session_state.messages = current_conv["messages"]
                            st.session_state.chat_history = current_conv["chat_history"]
                            st.rerun()

                with col_right:
                    with st.popover("⋮", use_container_width=True):
                        st.markdown(f"**{conv_name}**")

                        new_name = st.text_input("重命名", value=conv_name, key=f"rename_{conv_name}")
                        if st.button("💾 保存", key=f"save_rename_{conv_name}"):
                            if new_name.strip() and new_name != conv_name:
                                if new_name not in st.session_state.conversations:
                                    st.session_state.conversations[new_name] = st.session_state.conversations.pop(conv_name)
                                    if st.session_state.current_conversation == conv_name:
                                        st.session_state.current_conversation = new_name
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
                                    st.session_state.messages = current_conv["messages"]
                                    st.session_state.chat_history = current_conv["chat_history"]
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
                                st.success("已置顶")
                                st.rerun()

                st.markdown("<hr style='margin: 10px 0; border: none; border-top: 1px solid #e2e8f0;'>", unsafe_allow_html=True)
        else:
            st.info("暂无对话，点击上方按钮创建")

# ------------------- 主页面内容 -------------------
utils.ui_utils.render_header()
chat_container = utils.ui_utils.render_chat_history()
user_input = utils.ui_utils.render_chat_input()

# ------------------- 初始化LLM -------------------
if st.session_state.model_mode == "本地调用 (Ollama)":
    llm = Ollama(
        model=st.session_state.ollama_model,
        base_url=st.session_state.ollama_base_url,
        temperature=0
    )
else:
    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=API_KEY,
        base_url=BASE_URL,
        temperature=0
    )

# ------------------- Chain 定义 -------------------
rephrase_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是一个智能助手。请严格按照以下规则处理用户输入：
1. 如果是闲聊/无关问题，直接回复'CHAT'并在下一行输出原问题。
2. 如果是知识查询/需要检索的问题，回复'RAG'并在下一行输出优化后的检索语句。
只输出两行：
第一行：意图（CHAT 或 RAG）
第二行：最终语句"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])

qa_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是一个基于文档的【总结与事实陈述】助手。
【核心任务】：
1. 根据【文档资料】内容，总结并回答用户的问题。
2. 如果资料中的描述与用户提问意思一致，请进行关联并给出事实总结。
3. 严禁提及资料中完全不存在的虚假事实。
4. 回答必须体现出是从资料中总结出来的。
【约束】：
- 如果资料里没有相关动作的描述，才回答"根据现有资料无法回答"。
- 不要使用任何外部常识。
【文档资料】：
{context}"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])

rephrase_chain = rephrase_prompt | llm | StrOutputParser()
qa_chain = qa_prompt | llm | StrOutputParser()

# ------------------- 检索函数 -------------------
def manual_retrieve(query: str, selected_doc: str, k: int = 15):
    start_time = time.perf_counter()
    search_kwargs = {"k": k}
    if selected_doc != "全部文档":
        search_kwargs["filter"] = {"source_file": selected_doc}

    initial_docs = vector_db.similarity_search(query, **search_kwargs)
    if not initial_docs:
        st.caption(f"⏱️ 检索耗时: {time.perf_counter() - start_time:.2f} 秒（未命中）")
        return [], ""

    pairs = [[query, doc.page_content] for doc in initial_docs]
    scores = reranker.predict(pairs)
    scored_docs = sorted(zip(initial_docs, scores), key=lambda x: x[1], reverse=True)

    st.session_state.last_search_results = scored_docs[:5]
    context = "\n\n".join([d[0].page_content for d in scored_docs[:3]])
    st.caption(f"⏱️ 检索耗时: {time.perf_counter() - start_time:.2f} 秒")
    return scored_docs, context

# ------------------- 固定左下角检索范围（定义 selected_doc 在全局） -------------------
st.markdown("""
    <style>
    .fixed-filter {
        position: fixed;
        bottom: 80px;
        left: 20px;
        background: white;
        padding: 12px 16px;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        border: 1px solid #e2e8f0;
        z-index: 1000;
        max-width: 280px;
        font-size: 0.9rem;
    }
    </style>
""", unsafe_allow_html=True)

try:
    docs = vector_db.similarity_search("", k=10000)
    all_sources = list(set(
        d.metadata.get("source_file", "未知")
        for d in docs
        if d.metadata.get("source_file") not in ["system"]
    ))
except Exception:
    all_sources = []

with st.container():
    st.markdown('<div class="fixed-filter">', unsafe_allow_html=True)
    st.markdown("**🎯 检索范围**")
    selected_doc = st.selectbox(
        "选择知识库",
        ["全部文档"] + sorted(all_sources),
        index=0,
        key="global_doc_filter",
        label_visibility="collapsed"
    )
    st.markdown(f"<small>当前：<strong>{selected_doc}</strong></small>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ------------------- 用户输入处理 -------------------
if user_input:
    llm_call_count = 0
    total_start_time = time.perf_counter()

    st.session_state.messages.append({"role": "user", "content": user_input})
    with chat_container:
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            llm_call_count += 1
            with st.spinner("🤖 分析问题意图..."):
                response = rephrase_chain.invoke({
                    "input": user_input,
                    "chat_history": st.session_state.chat_history
                })
            lines = response.strip().split("\n", 1)
            intent = lines[0].strip().upper() if lines else "CHAT"
            standalone_q = lines[1].strip() if len(lines) > 1 else user_input

            if intent == "CHAT":
                st.markdown("""<div class="info-box"><strong>💬 对话模式：</strong>直接回答（无需检索）</div>""", unsafe_allow_html=True)
                llm_call_count += 1
                answer = st.write_stream(llm.stream(user_input))
            else:
                st.markdown(f"""
                    <div class="info-box">
                        <strong>🔍 检索模式：</strong>基于知识库回答<br>
                        <strong>检索关键词：</strong>{standalone_q}
                    </div>
                """, unsafe_allow_html=True)

                with st.spinner("📚 深度检索与分析文档..."):
                    top_docs, context_text = manual_retrieve(standalone_q, selected_doc)  # 使用左下角的 selected_doc

                    if not context_text:
                        answer = "🤷 抱歉，未在文档库中找到相关依据。"
                        st.markdown(f"<div class='warning-box'><strong>提示：</strong>{answer}</div>", unsafe_allow_html=True)
                    else:
                        llm_call_count += 1
                        st.markdown("🎯 正在生成基于文档的回答...")
                        answer = st.write_stream(qa_chain.stream({
                            "context": context_text,
                            "chat_history": st.session_state.chat_history,
                            "input": standalone_q
                        }))

                if st.session_state.get("last_search_results"):
                    with st.expander("🔍 检索结果溯源 (Top 5)", expanded=False):
                        for idx, (doc, score) in enumerate(st.session_state.last_search_results, 1):
                            score_float = round(float(score), 3)
                            color = "green" if score_float > 0.5 else "orange" if score_float > 0 else "gray"
                            st.markdown(f"""
                                <div style="padding: 8px; margin: 4px 0; border-radius: 6px; background-color: #f8fafc;">
                                    <strong>第 {idx} 条匹配结果：</strong><br>
                                    <strong>文件：</strong>{doc.metadata.get('source_file', '未知')}<br>
                                    <strong>语义关联度：</strong><span style="color:{color};">[{score_float}]</span><br>
                                    <div style="margin-top: 4px; font-size: 0.9rem; color: #475569;">
                                        {doc.page_content[:200]}...
                                    </div>
                                </div>
                            """, unsafe_allow_html=True)

            # 更新历史
            st.session_state.chat_history.extend([HumanMessage(content=user_input), AIMessage(content=answer)])
            st.session_state.messages.append({"role": "assistant", "content": answer})

            total_time = time.perf_counter() - total_start_time
            st.markdown(f"""
                <div class="debug-info">
                    📊 调试信息 | LLM 调用 {llm_call_count} 次 | 总耗时 {total_time:.2f} 秒
                </div>
            """, unsafe_allow_html=True)

    # 保存当前对话
    st.session_state.conversations[st.session_state.current_conversation] = {
        "messages": st.session_state.messages,
        "chat_history": st.session_state.chat_history
    }