# app.py
import streamlit as st
import time

from langchain_core.messages import HumanMessage, AIMessage

from config import *
from utils.embedding import get_embeddings, get_reranker
from utils.db import get_vector_db
from chains.intent_rephrase import rephrase_chain
from chains.qa_chain import qa_chain, llm
from components.sidebar import render_sidebar

# ------------------- Streamlit 页面配置 -------------------
st.set_page_config(page_title="企业级 RAG 排查助手", layout="wide")
st.title("🛡️ 严格约束型 RAG 助手")

# ------------------- 缓存加载核心引擎 -------------------
@st.cache_resource
def load_engines():
    embeddings = get_embeddings()
    reranker = get_reranker()
    vector_db = get_vector_db(embeddings)
    return vector_db, reranker

vector_db, reranker = load_engines()

# ------------------- 侧边栏 -------------------
selected_doc = render_sidebar(vector_db)

# ------------------- 会话状态初始化 -------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ------------------- 显示历史消息 -------------------
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ------------------- 检索函数（带计时） -------------------
def manual_retrieve(query: str, selected_doc: str, k: int = 15):
    start_time = time.perf_counter()

    search_kwargs = {"k": k}
    if selected_doc != "全部文档":
        search_kwargs["filter"] = {"source_file": selected_doc}

    initial_docs = vector_db.similarity_search(query, **search_kwargs)
    if not initial_docs:
        retrieve_time = time.perf_counter() - start_time
        st.caption(f"检索耗时: {retrieve_time:.2f} 秒（未命中）")
        return [], ""

    pairs = [[query, doc.page_content] for doc in initial_docs]
    scores = reranker.predict(pairs)
    scored_docs = sorted(zip(initial_docs, scores), key=lambda x: x[1], reverse=True)

    # 保存本次检索结果，用于溯源展示
    st.session_state.last_search_results = scored_docs[:5]
    context = "\n\n".join([d[0].page_content for d in scored_docs[:3]])

    retrieve_time = time.perf_counter() - start_time
    st.caption(f"检索耗时: {retrieve_time:.2f} 秒")
    return scored_docs, context

# ------------------- 用户输入处理 -------------------
if user_input := st.chat_input("请输入您的问题..."):
    # 本次对话 LLM 调用计数与总计时
    llm_call_count = 0
    total_start_time = time.perf_counter()

    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        # 1. 意图识别 + 查询改写（第1次 LLM 调用）
        llm_call_count += 1
        response = rephrase_chain.invoke({
            "input": user_input,
            "chat_history": st.session_state.chat_history
        })
        lines = response.strip().split("\n")
        intent = lines[0].strip().upper() if len(lines) >= 1 else "CHAT"
        standalone_q = lines[1].strip() if len(lines) >= 2 else user_input

        if intent == "CHAT":
            # 纯闲聊，直接调用 LLM
            llm_call_count += 1
            answer = st.write_stream(llm.stream(user_input))
        else:
            # RAG 流程
            st.info(f"🔍 检索关键词：{standalone_q}")

            with st.spinner("深度检索与分析资料中..."):
                top_docs, context_text = manual_retrieve(standalone_q, selected_doc)

                if not context_text:
                    answer = "抱歉，未在文档库中找到相关依据。"
                    st.markdown(answer)
                else:
                    llm_call_count += 1
                    answer = st.write_stream(qa_chain.stream({
                        "context": context_text,
                        "chat_history": st.session_state.chat_history,
                        "input": standalone_q
                    }))

            # 显示溯源信息
            if st.session_state.get("last_search_results"):
                with st.expander("🔍 匹配详情与溯源得分 (Top 5)"):
                    for doc, score in st.session_state.last_search_results:
                        color = "green" if score > 0 else "gray"
                        st.write(
                            f"文件: **{doc.metadata.get('source_file', '未知')}** | "
                            f"语义关联度: :{color}[{round(float(score), 3)}]"
                        )
                        st.caption(doc.page_content)
                        st.divider()

        # 更新会话历史
        st.session_state.chat_history.extend([
            HumanMessage(content=user_input),
            AIMessage(content=answer)
        ])
        st.session_state.messages.append({"role": "assistant", "content": answer})

    # ------------------- 调试信息 -------------------
    total_time = time.perf_counter() - total_start_time
    with st.chat_message("assistant"):
        st.caption("调试信息：")
        st.caption(f"- LLM 调用次数: {llm_call_count} 次")
        st.caption(f"- 总响应时间: {total_time:.2f} 秒")