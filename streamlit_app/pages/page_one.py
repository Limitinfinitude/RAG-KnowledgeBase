# pages/page_one.py
import _project_root  # noqa: F401

import streamlit as st
import time
import requests
import re
from datetime import datetime

# 导入模块化UI
import utils.ui_utils
import utils.styles
import utils.chat_ui
import utils.sidebar_ui

# ------------------- 子页面加载样式（关键！） -------------------
utils.ui_utils.load_custom_css()  # 基础布局样式
utils.styles.load_all_styles()    # 聊天和组件样式

# ------------------- 导入核心模块 -------------------
import os
from config import *
from utils.logger import log_query, log_error, log_token_usage
from utils.token_tracker import track_token_usage, extract_token_usage
from utils.intent_classifier import classify_intent
from utils.chat_responses import get_chat_response
from utils.reranker import get_reranker
from langchain_core.messages import HumanMessage, AIMessage

from services.chat_turn import augment_rag_with_web_search, filter_sources_for_traceability
from services.rag_prompts import get_qa_hybrid_prompt, get_qa_prompt, get_rephrase_prompt
from services.retrieval import retrieve_for_rag
from services.ui_sink import RetrievalUISink
from services.vector_store import load_embeddings_and_vector_db

# ------------------- 会话状态初始化 -------------------
# API配置初始化（使用新的配置系统）
if "current_api_config" not in st.session_state:
    st.session_state.current_api_config = "DeepSeek"

# 对话列表在 app.py 中已通过 init_conversations_if_needed 从磁盘恢复
from utils.conversation_storage import sync_session_conversation_to_storage


def _evidence_for_trace_ui(answer: str, evidence_sources: list) -> list:
    """与 Web 端一致：优先 [来源N]，否则按回答与片段重叠筛选，避免展示全部检索块。"""
    if not evidence_sources:
        return []
    ser = []
    for s in evidence_sources:
        try:
            sc = float(s["score"]) if s.get("score") is not None else None
        except (TypeError, ValueError):
            sc = None
        ser.append(
            {
                "index": s.get("index"),
                "file": s.get("file"),
                "content": s.get("content"),
                "score": sc,
                "chunk_level": s.get("chunk_level"),
                "metadata": {},
            }
        )
    filtered = filter_sources_for_traceability(answer, ser)
    by_idx = {}
    for s in evidence_sources:
        try:
            ii = int(s.get("index") or 0)
            if ii > 0:
                by_idx[ii] = s
        except (TypeError, ValueError):
            pass
    out = []
    for f in filtered:
        try:
            ii = int(f.get("index") or 0)
            if ii in by_idx:
                out.append(by_idx[ii])
        except (TypeError, ValueError):
            pass
    return out

# 当前对话快捷引用
current_conv = st.session_state.conversations[st.session_state.current_conversation]
# 从持久化存储加载消息和历史（确保刷新后能恢复）
st.session_state.messages = current_conv.get("messages", [])
st.session_state.chat_history = current_conv.get("chat_history", [])

# 确保messages和chat_history同步（修复刷新后丢失的问题）
if len(st.session_state.messages) > 0 and len(st.session_state.chat_history) == 0:
    # 如果messages有数据但chat_history为空，尝试从messages重建chat_history
    from langchain_core.messages import HumanMessage, AIMessage
    for msg in st.session_state.messages:
        if msg.get("role") == "user":
            st.session_state.chat_history.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "assistant":
            st.session_state.chat_history.append(AIMessage(content=msg.get("content", "")))

# ------------------- 加载核心引擎 -------------------
@st.cache_resource
def load_engines_base():
    return load_embeddings_and_vector_db()

# 检查是否需要刷新向量库（自动检测文件上传）
if "vector_db_reload_needed" not in st.session_state:
    st.session_state.vector_db_reload_needed = False

# 检查向量库索引文件的修改时间，如果更新了则自动刷新
index_dir = os.path.join(DB_DIR, "faiss_index")
index_file = os.path.join(index_dir, "index.faiss")
if os.path.exists(index_file):
    # 获取索引文件的修改时间
    index_mtime = os.path.getmtime(index_file)
    if "last_index_mtime" not in st.session_state:
        st.session_state.last_index_mtime = index_mtime
    elif st.session_state.last_index_mtime < index_mtime:
        # 索引文件已更新，需要刷新
        st.session_state.vector_db_reload_needed = True
        st.session_state.last_index_mtime = index_mtime

if st.session_state.vector_db_reload_needed:
    # 清除缓存，重新加载
    load_engines_base.clear()
    st.session_state.vector_db_reload_needed = False
    st.info("🔄 向量库已自动刷新")

vector_db, embeddings = load_engines_base()


# ------------------- 侧边栏：对话管理和设置 -------------------
with st.sidebar:
    # 知识库选择（放在最前面）
    selected_kb = utils.sidebar_ui.render_knowledge_base_selector()
    st.session_state.selected_kb = selected_kb
    
    utils.sidebar_ui.render_conversation_management()
    utils.sidebar_ui.render_search_mode_settings()  # 检索模式设置
    utils.sidebar_ui.render_reranker_settings()
    utils.sidebar_ui.render_web_search_settings()
    utils.sidebar_ui.render_model_settings_link()
    utils.sidebar_ui.render_temperature_settings()

# ------------------- 主页面内容 -------------------
utils.chat_ui.render_header()
chat_container = utils.chat_ui.render_chat_history()
user_input = utils.chat_ui.render_chat_input()

# ------------------- 初始化LLM -------------------
from utils.api_config import get_current_config

# 获取当前API配置
if "current_api_config" not in st.session_state:
    st.session_state.current_api_config = "DeepSeek"

# 获取温度设置（默认0.0）
if "llm_temperature" not in st.session_state:
    st.session_state.llm_temperature = 0.0

def get_llm_instance():
    """获取LLM实例（每次调用都使用最新的温度设置）"""
    try:
        get_current_config()
    except Exception as e:
        st.error(f"LLM初始化失败: {str(e)}")
        st.info("请前往「模型设置」页面配置API")
    from services.llm_factory import build_chat_llm

    return build_chat_llm(st.session_state.llm_temperature)


def handle_llm_error(e: Exception, context: str = "") -> str:
    """
    统一处理LLM调用错误
    :param e: 异常对象
    :param context: 错误上下文描述
    :return: 友好的错误提示文本
    """
    error_msg = str(e).lower()
    
    if "authentication" in error_msg or "401" in error_msg or "invalid api key" in error_msg:
        st.error("❌ API认证失败")
        st.warning("请检查API密钥是否正确，并确保Base URL配置正确")
        st.info("💡 请前往「模型设置」页面配置正确的API密钥")
        return "抱歉，API认证失败。请检查「模型设置」中的API配置。"
    elif "rate limit" in error_msg or "429" in error_msg:
        st.warning("⚠️ API调用频率超限")
        st.info("请稍后再试，或检查API配额")
        return "抱歉，API调用频率超限，请稍后再试。"
    elif "network" in error_msg or "connection" in error_msg or "timeout" in error_msg:
        st.error("❌ 网络连接失败")
        st.info("请检查网络连接或API服务是否可用")
        return "抱歉，无法连接到AI服务，请检查网络连接。"
    else:
        st.error(f"❌ 调用AI服务失败: {str(e)}")
        st.info("💡 请前往「模型设置」页面检查配置，或稍后重试")
        return f"抱歉，服务暂时不可用。错误信息：{str(e)[:100]}"

# 初始化LLM（用于创建chains）
llm = get_llm_instance()

# ------------------- 重排序器缓存 -------------------
@st.cache_resource
def get_cached_reranker():
    return get_reranker()


# ------------------- 知识库选择（在侧边栏中） -------------------
# 知识库选择器已在侧边栏中渲染，通过session_state获取
if "selected_kb" not in st.session_state:
    st.session_state.selected_kb = "全部知识库"
selected_kb = st.session_state.selected_kb


# ------------------- 用户输入处理 -------------------
if user_input:
    llm_call_count = 0
    total_start_time = time.perf_counter()
    # 累计token使用
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0

    st.session_state.messages.append({"role": "user", "content": user_input})
    with chat_container:
        # 用户消息：使用st.chat_message显示头像，并直接应用样式
        with st.chat_message("user"):
            # 直接使用内联样式确保蓝色背景生效
            st.markdown(f"""
                <div style="background: #E3F2FD; color: #1976D2; padding: 10px 16px; border-radius: 12px; line-height: 1.5;">
                    {user_input}
                </div>
            """, unsafe_allow_html=True)

        # 助手回复区域
        with st.chat_message("assistant"):
            # 【企业级策略】：默认RAG，只有极少数明确闲聊才特殊处理
            from utils.intent_classifier import classify_intent_lightweight
            
            # 检查是否是明确的闲聊（问候、感谢、再见）
            is_simple_chat = classify_intent_lightweight(user_input)
            
            if is_simple_chat == "CHAT":
                # 闲聊模式：问候、感谢、再见、系统问题
                st.markdown("""<div class="info-box">闲聊模式（不检索知识库）</div>""", unsafe_allow_html=True)
                llm_call_count += 1
                
                # 根据问题类型生成不同的prompt
                system_keywords = ["你是谁", "你是什么", "你叫什么", "介绍", "你能做什么", "功能", "怎么使用"]
                is_system_question = any(kw in user_input for kw in system_keywords)
                
                if is_system_question:
                    # 系统相关问题：提供详细介绍
                    prompt = f"""用户问：{user_input}

请你作为一个RAG（检索增强生成）智能问答助手来回答。要点：
1. 简要介绍你是一个基于文档的智能问答系统
2. 主要功能是帮助用户从上传的文档中检索和理解信息
3. 可以回答关于文档内容的问题，提供信息溯源
4. 语气要友好、专业，2-3句话即可"""
                    try:
                        current_llm = get_llm_instance()
                        response = current_llm.invoke(prompt)
                        # 提取并记录token使用
                        usage = track_token_usage(response, call_type="chat")
                        if usage:
                            total_prompt_tokens += usage.get("prompt_tokens", 0)
                            total_completion_tokens += usage.get("completion_tokens", 0)
                            total_tokens += usage.get("total_tokens", 0)
                        answer = response.content if hasattr(response, 'content') else str(response)
                    except Exception as e:
                        answer = handle_llm_error(e, "系统介绍")
                    # 模拟流式显示
                    answer_placeholder = st.empty()
                    displayed_text = ""
                    for char in answer:
                        displayed_text += char
                        answer_placeholder.markdown(displayed_text)
                else:
                    # 普通闲聊：简短回复
                    try:
                        current_llm = get_llm_instance()
                        response = current_llm.invoke(
                            f"用户说：{user_input}\n\n请简短、友好地回复（1-2句话）。"
                        )
                        # 提取并记录token使用
                        usage = track_token_usage(response, call_type="chat")
                        if usage:
                            total_prompt_tokens += usage.get("prompt_tokens", 0)
                            total_completion_tokens += usage.get("completion_tokens", 0)
                            total_tokens += usage.get("total_tokens", 0)
                        answer = response.content if hasattr(response, 'content') else str(response)
                        # 模拟流式显示
                        answer_placeholder = st.empty()
                        displayed_text = ""
                        for char in answer:
                            displayed_text += char
                            answer_placeholder.markdown(displayed_text)
                    except Exception as e:
                        error_msg = str(e)
                        if "Authentication" in error_msg or "authentication" in error_msg or "401" in error_msg:
                            st.error("❌ API认证失败，请检查API密钥是否正确")
                            st.info("💡 请前往「模型设置」页面配置正确的API密钥和Base URL")
                            answer = "抱歉，无法连接到AI服务。请检查API配置。"
                        else:
                            st.error(f"❌ 调用AI服务失败: {error_msg}")
                            st.info("💡 请检查网络连接或前往「模型设置」页面检查配置")
                            answer = "抱歉，服务暂时不可用。"
                        # 显示错误消息
                        answer_placeholder = st.empty()
                        answer_placeholder.markdown(answer)
            else:
                # 【默认流程】：所有其他问题都走RAG检索
                # 【优化】：智能判断是否需要LLM重写查询
                # 只有在以下情况才需要LLM重写：
                # 1. 有聊天历史（需要解决指代词）
                # 2. 查询包含明显的指代词（他、它、这个等）
                needs_rephrase = False
                standalone_q = user_input
                
                # 检查是否有聊天历史
                has_history = len(st.session_state.chat_history) > 0
                
                # 检查是否包含指代词
                pronouns = ["他", "她", "它", "这个", "那个", "这些", "那些", "其", "该"]
                has_pronoun = any(pronoun in user_input for pronoun in pronouns)
                
                # 只有同时满足：有历史 且 有指代词，才需要LLM重写
                if has_history and has_pronoun:
                    needs_rephrase = True
                    llm_call_count += 1
                    with st.spinner("🔍 优化检索关键词（解决指代）..."):
                        try:
                            # 直接调用LLM以获取token使用信息
                            current_llm = get_llm_instance()
                            messages = get_rephrase_prompt().format_messages(
                                input=user_input,
                                chat_history=st.session_state.chat_history
                            )
                            response = current_llm.invoke(messages)
                            # 提取并记录token使用
                            usage = track_token_usage(response, call_type="rephrase")
                            if usage:
                                total_prompt_tokens += usage.get("prompt_tokens", 0)
                                total_completion_tokens += usage.get("completion_tokens", 0)
                                total_tokens += usage.get("total_tokens", 0)
                            # 获取文本内容
                            response_text = response.content if hasattr(response, 'content') else str(response)
                            lines = response_text.strip().split("\n", 1)
                            standalone_q = lines[1].strip() if len(lines) > 1 else user_input
                        except Exception as e:
                            st.warning(f"关键词优化失败，使用原始查询: {e}")
                            standalone_q = user_input
                
                if needs_rephrase:
                    st.markdown(f"""<div class="info-box">检索关键词：{standalone_q}</div>""", unsafe_allow_html=True)
                
                # 检索知识库（领域逻辑在 services.retrieval）
                with st.spinner("📚 正在检索知识库..."):
                    sink = RetrievalUISink.streamlit(st)
                    _reranker = (
                        get_cached_reranker()
                        if st.session_state.get("enable_reranker", False)
                        else None
                    )
                    ret = retrieve_for_rag(
                        vector_db=vector_db,
                        query=standalone_q,
                        selected_kb=selected_kb,
                        k=10,
                        search_mode=st.session_state.get("search_mode", "vector"),
                        enable_reranker=st.session_state.get("enable_reranker", False),
                        reranker=_reranker,
                        sink=sink,
                    )
                    st.session_state.last_search_results = ret.last_search_results
                    context_text, evidence_raw, has_web = augment_rag_with_web_search(
                        ret,
                        standalone_q,
                        st.session_state.get("enable_web_search", False),
                    )
                    st.session_state.evidence_sources = evidence_raw
                    top_docs = ret.scored_docs
                
                # 3. 【双路策略】：根据检索结果的质量决定如何回答
                if not (context_text or "").strip():
                    # 完全没有找到文档
                    st.markdown("""<div class="warning-box">未找到相关文档</div>""", unsafe_allow_html=True)
                    llm_call_count += 1
                    try:
                        current_llm = get_llm_instance()
                        response = current_llm.invoke(
                            f"知识库中没有找到与「{user_input}」相关的信息。请告诉用户：\n"
                            f"1. 知识库中暂无相关文档\n"
                            f"2. 建议上传相关文档或换个方式提问\n"
                            f"语气要友好、专业。"
                        )
                        # 提取并记录token使用
                        usage = track_token_usage(response, call_type="qa")
                        if usage:
                            total_prompt_tokens += usage.get("prompt_tokens", 0)
                            total_completion_tokens += usage.get("completion_tokens", 0)
                            total_tokens += usage.get("total_tokens", 0)
                        answer = response.content if hasattr(response, 'content') else str(response)
                    except Exception as e:
                        answer = handle_llm_error(e, "无文档回答")
                    # 模拟流式显示
                    answer_placeholder = st.empty()
                    displayed_text = ""
                    for char in answer:
                        displayed_text += char
                        answer_placeholder.markdown(displayed_text)
                else:
                    # 找到文档，检查相关性分数
                    max_score = max(
                        [score for _, score in st.session_state.last_search_results[:5]]
                        if st.session_state.last_search_results
                        else [0]
                    )
                    if has_web:
                        max_score = max(max_score, 0.35)
                    web_low = ""
                    if has_web:
                        web_low = (
                            "\n- 资料中含「联网检索摘要」时，可与知识库片段一并使用，引用写 [来源n]；"
                            "摘要非全文，勿编造其中未出现的细节。\n"
                        )
                    if has_web:
                        st.markdown(
                            """<div class="info-box">已附加联网网页摘要（与知识库一并供模型参考）</div>""",
                            unsafe_allow_html=True,
                        )

                    if max_score < 0.3:
                        # 分数很低，但可能包含答案（需要仔细检查）
                        st.markdown(f"""<div class="info-box">检索相关性较低（{max_score:.2f}），正在仔细检查内容...</div>""", unsafe_allow_html=True)
                        llm_call_count += 1
                        try:
                            current_llm = get_llm_instance()
                            # 【优化】：改进低相关性提示词，要求仔细检查所有上下文
                            response = current_llm.invoke(
                                f"""你是一个严格的文档问答助手。请仔细阅读以下检索到的文档内容，即使相关性分数较低，也要检查是否包含用户问题的答案。

【重要】：
1. 仔细阅读完整的文档内容，不要只看开头
2. 即使文档中只提到关键词，也要尝试回答
3. 如果文档中确实包含答案（即使只是简单提及），必须基于文档回答
4. 只有在文档中完全找不到相关信息时，才说"无法回答"

【检索到的完整文档内容】：
{context_text}

【用户问题】：
{user_input}

【要求】：
- 如果文档中包含答案（即使只是简单提及），请基于文档内容回答
- 如果文档中确实没有相关信息，才说"根据现有资料无法回答"
- 回答时要引用具体来源，如"根据[来源1]..."或"文档中提到..."
- 语气要专业、准确{web_low}"""
                            )
                            # 提取并记录token使用
                            usage = track_token_usage(response, call_type="qa")
                            if usage:
                                total_prompt_tokens += usage.get("prompt_tokens", 0)
                                total_completion_tokens += usage.get("completion_tokens", 0)
                                total_tokens += usage.get("total_tokens", 0)
                            answer = response.content if hasattr(response, 'content') else str(response)
                        except Exception as e:
                            answer = handle_llm_error(e, "低相关性回答")
                        # 模拟流式显示
                        answer_placeholder = st.empty()
                        displayed_text = ""
                        for char in answer:
                            displayed_text += char
                            answer_placeholder.markdown(displayed_text)
                    else:
                        # 分数合理，基于文档回答
                        st.markdown(f"""<div class="info-box">检索成功（相关性：{max_score:.2f}）</div>""", unsafe_allow_html=True)
                        llm_call_count += 1
                        
                        try:
                            # 使用invoke获取完整response以捕获token，然后模拟流式显示
                            current_llm = get_llm_instance()
                            tpl = get_qa_hybrid_prompt() if has_web else get_qa_prompt()
                            messages = tpl.format_messages(
                                context=context_text,
                                chat_history=st.session_state.chat_history,
                                input=standalone_q
                            )
                            response = current_llm.invoke(messages)
                            # 提取并记录token使用
                            usage = track_token_usage(response, call_type="qa")
                            if usage:
                                total_prompt_tokens += usage.get("prompt_tokens", 0)
                                total_completion_tokens += usage.get("completion_tokens", 0)
                                total_tokens += usage.get("total_tokens", 0)
                            # 获取文本内容
                            answer = response.content if hasattr(response, 'content') else str(response)
                        except Exception as e:
                            answer = handle_llm_error(e, "RAG问答")
                        
                        # 模拟流式显示（统一处理，无论成功还是错误）
                        answer_placeholder = st.empty()
                        displayed_text = ""
                        for char in answer:
                            displayed_text += char
                            answer_placeholder.markdown(displayed_text)

                # 【调试信息】：检索后的chunk展示
                if st.session_state.get("last_search_results"):
                    # 过滤掉 system 文档
                    valid_results = [
                        (doc, score) for doc, score in st.session_state.last_search_results
                        if doc.metadata.get("source_file") not in ["system", None]
                        and doc.metadata.get("note") != "empty_init"
                    ]
                    
                    if valid_results:
                        with st.expander("🔍 检索后的Chunk展示（调试）", expanded=False):
                            st.caption("显示所有检索到的chunks，用于调试检索效果")
                            for idx, (doc, score) in enumerate(valid_results[:10], 1):  # 显示更多用于调试
                                score_float = utils.ui_utils.safe_similarity_ratio(score)
                                score_pct = int(score_float * 100)
                                
                                # 简约的分数显示
                                if score_float > 0.7:
                                    score_color = "#34c759"
                                elif score_float > 0.5:
                                    score_color = "#ff9500"
                                else:
                                    score_color = "#8e8e93"
                                
                                # chunk层级
                                chunk_level = doc.metadata.get("chunk_level", "medium")
                                level_label = {"small": "精确", "medium": "段落", "large": "章节", "summary": "摘要"}.get(chunk_level, "")

                                st.markdown(f"""
                                    <div style="padding: 10px 12px; margin: 6px 0; border-radius: 8px; background-color: #fafafa; border: 1px solid #e5e5e5;">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                            <span style="font-size: 0.85rem; color: #333; font-weight: 500;">#{idx} {doc.metadata.get('source_file', '未知')}</span>
                                            <span style="font-size: 0.75rem; color: {score_color}; font-weight: 500;">{score_pct}%</span>
                                        </div>
                                        <div style="font-size: 0.8rem; color: #666; line-height: 1.5; margin-bottom: 4px;">
                                            {doc.page_content[:300]}...
                                        </div>
                                        <div style="font-size: 0.7rem; color: #999;">
                                            {level_label} | Chunk ID: {doc.metadata.get('chunk_id', 'N/A')[:8]}
                                        </div>
                                    </div>
                                """, unsafe_allow_html=True)

                # 【证据级溯源】：与回答对齐（显式 [来源N] 或文本重叠），不再默认展示全部检索块
                evidence_sources = st.session_state.get("evidence_sources", [])
                traced = _evidence_for_trace_ui(answer, evidence_sources)
                if traced:
                    with st.expander("📚 证据级溯源（与回答对齐）", expanded=True):
                        st.caption("依据模型标注的 [来源N] 或与回答文本重合度筛选，弱化无关片段")
                        for source in traced:
                            idx = source.get("index", 0)
                            score_float = utils.ui_utils.safe_similarity_ratio(source.get("score", 0.0))
                            score_pct = int(score_float * 100)

                            if score_float > 0.7:
                                score_color = "#34c759"
                            elif score_float > 0.5:
                                score_color = "#ff9500"
                            else:
                                score_color = "#8e8e93"

                            chunk_level = source.get("chunk_level", "medium")
                            level_label = {"small": "精确", "medium": "段落", "large": "章节", "summary": "摘要"}.get(
                                chunk_level, ""
                            )

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

            # 保存证据级溯源信息到消息元数据
            assistant_message_metadata = {}
            evidence_sources = st.session_state.get("evidence_sources", [])
            traced_meta = _evidence_for_trace_ui(answer, evidence_sources)
            if traced_meta:
                cited_sources = []
                for source in traced_meta:
                    idx = source.get("index", 0)
                    cited_sources.append(
                        {
                            "index": idx,
                            "file": source.get("file", "未知"),
                            "score": utils.ui_utils.safe_similarity_ratio(source.get("score", 0.0)),
                            "content": source.get("content", ""),
                            "full_content": source.get("full_content", ""),
                            "chunk_level": source.get("chunk_level", "medium"),
                            "metadata": source.get("metadata", {}),
                        }
                    )
                assistant_message_metadata["evidence_sources"] = cited_sources

            # 更新历史
            st.session_state.chat_history.extend([HumanMessage(content=user_input), AIMessage(content=answer)])
            st.session_state.messages.append({
                "role": "assistant", 
                "content": answer,
                "metadata": assistant_message_metadata
            })

            total_time = time.perf_counter() - total_start_time
            
            # 记录查询日志
            try:
                query_intent = "CHAT" if is_simple_chat == "CHAT" else "RAG"
                log_query(
                    query=user_input,
                    intent=query_intent,
                    response_time=total_time,
                    retrieved_docs=len(st.session_state.get("last_search_results", [])),
                    llm_calls=llm_call_count,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_tokens
                )
            except Exception as e:
                log_error("log_query_error", str(e), {"query": user_input[:50]})
            
            st.markdown(f"""
                <div class="debug-info">
                    LLM调用 {llm_call_count} 次 · 耗时 {total_time:.2f} 秒
                </div>
            """, unsafe_allow_html=True)

# 每轮结束时把当前对话写回 conversations 并落盘（刷新浏览器 / 重启服务后由 app 入口重新加载）
sync_session_conversation_to_storage(st.session_state)