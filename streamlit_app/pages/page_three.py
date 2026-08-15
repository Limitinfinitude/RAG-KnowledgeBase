# pages/page_three.py
import _project_root  # noqa: F401

import streamlit as st
import os
from datetime import datetime
from config import STREAMLIT_KB_DIR
from utils.logger import get_recent_logs, get_statistics
import utils.ui_utils
utils.ui_utils.load_custom_css()

st.title("监控台")

LOG_DIR = os.path.join(STREAMLIT_KB_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "system.log")

# ==================== 统计概览 ====================
st.markdown("---")
st.markdown("### 统计概览")

stats = get_statistics()

if stats:
    # 第一行：基础统计
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("总查询数", stats.get("total_queries", 0))
    with col2:
        st.metric("总检索数", stats.get("total_retrievals", 0))
    with col3:
        st.metric("总错误数", stats.get("total_errors", 0))
    with col4:
        st.metric("平均响应时间", f"{stats.get('avg_response_time', 0)}s")
    with col5:
        st.metric("平均重排序时间", f"{stats.get('avg_rerank_time', 0)}s")
    
    # 第二行：Token统计
    st.markdown("---")
    st.markdown("#### 💰 Token使用统计")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    total_tokens = stats.get("total_tokens", 0)
    total_prompt_tokens = stats.get("total_prompt_tokens", 0)
    total_completion_tokens = stats.get("total_completion_tokens", 0)
    estimated_cost = stats.get("estimated_cost", 0.0)
    model_token_stats = stats.get("model_token_stats", {}) or {}

    with col1:
        st.metric("总Token数", f"{total_tokens:,}")
    with col2:
        st.metric("输入Token", f"{total_prompt_tokens:,}")
    with col3:
        st.metric("输出Token", f"{total_completion_tokens:,}")
    with col4:
        st.metric("估算费用", f"¥{estimated_cost:.4f}")
    with col5:
        # 计算平均每次调用的token数
        total_calls = sum(model_stats.get("calls", 0) for model_stats in model_token_stats.values())
        avg_tokens = total_tokens / total_calls if total_calls > 0 else 0
        st.metric("平均Token/次", f"{avg_tokens:.0f}")
    
    # 按模型统计
    if model_token_stats:
        st.markdown("##### 按模型统计")
        for model, model_stats in model_token_stats.items():
            with st.expander(f"📊 {model} - {model_stats['calls']} 次调用"):
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("输入Token", f"{model_stats['prompt_tokens']:,}")
                with col2:
                    st.metric("输出Token", f"{model_stats['completion_tokens']:,}")
                with col3:
                    st.metric("总Token", f"{model_stats['total_tokens']:,}")
                with col4:
                    st.metric("调用次数", model_stats['calls'])
    
    st.markdown("---")
    
    # 意图分布
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 意图分布")
        intent_dist = stats.get("intent_distribution", {})
        if intent_dist:
            for intent, count in intent_dist.items():
                st.progress(count / sum(intent_dist.values()), text=f"{intent}: {count}")
        else:
            st.info("暂无数据")
    
    with col2:
        st.markdown("#### 重排序器类型分布")
        reranker_dist = stats.get("reranker_distribution", {})
        if reranker_dist:
            for r_type, count in reranker_dist.items():
                st.progress(count / sum(reranker_dist.values()), text=f"{r_type}: {count}")
        else:
            st.info("暂无数据")
else:
    st.info("暂无统计数据")

# ==================== 日志查看 ====================
st.markdown("---")
st.markdown("### 日志查看")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["全部日志", "查询日志", "检索日志", "错误日志", "文件操作", "Token使用"])

with tab1:
    limit = st.slider("显示数量", 10, 200, 50, key="all_logs_limit")
    logs = get_recent_logs(limit=limit)
    
    if logs:
        for log in logs:
            log_type = log.get("type", "unknown")
            timestamp = log.get("timestamp", "")
            
            with st.expander(f"[{log_type.upper()}] {timestamp[:19] if timestamp else 'Unknown'}"):
                st.json(log)
    else:
        st.info("暂无日志")

with tab2:
    limit = st.slider("显示数量", 10, 200, 50, key="query_logs_limit")
    logs = get_recent_logs(category="queries", limit=limit)
    
    if logs:
        for log in logs:
            query = log.get("query", "")[:100]
            intent = log.get("intent", "UNKNOWN")
            response_time = log.get("response_time", 0)
            timestamp = log.get("timestamp", "")[:19]
            
            st.markdown(f"**{timestamp}** | {intent} | {response_time:.2f}s")
            st.caption(query)
            st.markdown("---")
    else:
        st.info("暂无查询日志")

with tab3:
    limit = st.slider("显示数量", 10, 200, 50, key="retrieval_logs_limit")
    logs = get_recent_logs(category="retrievals", limit=limit)
    
    if logs:
        for log in logs:
            query = log.get("query", "")[:100]
            initial_count = log.get("initial_count", 0)
            reranked_count = log.get("reranked_count", 0)
            rerank_time = log.get("rerank_time", 0)
            reranker_type = log.get("reranker_type", "unknown")
            timestamp = log.get("timestamp", "")[:19]
            
            st.markdown(f"**{timestamp}** | {reranker_type} | {rerank_time:.3f}s")
            st.caption(f"查询: {query}")
            st.caption(f"文档数: {initial_count} -> {reranked_count}")
            st.markdown("---")
    else:
        st.info("暂无检索日志")

with tab4:
    limit = st.slider("显示数量", 10, 200, 50, key="error_logs_limit")
    logs = get_recent_logs(category="errors", limit=limit)
    
    if logs:
        for log in logs:
            error_type = log.get("error_type", "unknown")
            error_message = log.get("error_message", "")
            timestamp = log.get("timestamp", "")[:19]
            context = log.get("context", {})
            
            st.error(f"**{timestamp}** | [{error_type}]")
            st.text(error_message)
            if context:
                with st.expander("上下文"):
                    st.json(context)
            st.markdown("---")
    else:
        st.info("暂无错误日志")

with tab5:
    limit = st.slider("显示数量", 10, 200, 50, key="file_logs_limit")
    upload_logs = get_recent_logs(category="uploads", limit=limit // 2)
    delete_logs = get_recent_logs(category="deletes", limit=limit // 2)
    
    st.markdown("#### 文件上传")
    if upload_logs:
        for log in upload_logs:
            file_name = log.get("file_name", "")
            file_size = log.get("file_size", 0)
            chunks = log.get("chunks", 0)
            category = log.get("category", "")
            timestamp = log.get("timestamp", "")[:19]
            
            st.markdown(f"**{timestamp}** | {file_name}")
            st.caption(f"大小: {file_size / (1024*1024):.2f}MB | 分块: {chunks} | 知识库: {category}")
            st.markdown("---")
    else:
        st.info("暂无上传日志")
    
    st.markdown("#### 文件删除")
    if delete_logs:
        for log in delete_logs:
            file_name = log.get("file_name", "")
            chunks_deleted = log.get("chunks_deleted", 0)
            timestamp = log.get("timestamp", "")[:19]
            
            st.markdown(f"**{timestamp}** | {file_name}")
            st.caption(f"删除分块数: {chunks_deleted}")
            st.markdown("---")
    else:
        st.info("暂无删除日志")

with tab6:
    limit = st.slider("显示数量", 10, 200, 50, key="token_logs_limit")
    logs = get_recent_logs(category="token_usage", limit=limit)
    
    if logs:
        # 汇总信息
        total_prompt = sum(log.get("prompt_tokens", 0) for log in logs)
        total_completion = sum(log.get("completion_tokens", 0) for log in logs)
        total_all = sum(log.get("total_tokens", 0) for log in logs)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("总输入Token", f"{total_prompt:,}")
        with col2:
            st.metric("总输出Token", f"{total_completion:,}")
        with col3:
            st.metric("总Token", f"{total_all:,}")
        
        st.markdown("---")
        st.markdown("#### 详细记录")
        
        for log in logs:
            timestamp = log.get("timestamp", "")[:19]
            model = log.get("model", "unknown")
            call_type = log.get("call_type", "unknown")
            prompt_tokens = log.get("prompt_tokens", 0)
            completion_tokens = log.get("completion_tokens", 0)
            total_tokens = log.get("total_tokens", 0)
            
            with st.expander(f"**{timestamp}** | {model} | {call_type} | {total_tokens:,} tokens"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("输入Token", f"{prompt_tokens:,}")
                with col2:
                    st.metric("输出Token", f"{completion_tokens:,}")
                with col3:
                    st.metric("总Token", f"{total_tokens:,}")
    else:
        st.info("暂无Token使用记录")

# ==================== 系统日志文件 ====================
st.markdown("---")
st.markdown("### 系统日志文件")

if os.path.exists(LOG_FILE):
    file_size = os.path.getsize(LOG_FILE) / 1024  # KB
    st.info(f"日志文件大小: {file_size:.2f} KB")
    
    if st.button("查看最新日志", key="view_log_file"):
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_lines = lines[-100:]  # 最后100行
                st.code('\n'.join(recent_lines))
        except Exception as e:
            st.error(f"读取日志文件失败: {e}")
else:
    st.info("日志文件不存在")

