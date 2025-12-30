# components/sidebar.py
import streamlit as st
import os
import shutil
from utils.file_loader import ingest_file
from utils.db import get_vector_db
from config import DB_DIR

def render_sidebar(vector_db):
    st.header("📂 知识管理")

    files = st.file_uploader(
        "新增文档（支持PDF/TXT）",
        accept_multiple_files=True,
        type=["pdf", "txt"]
    )

    if st.button("🔄 开始入库", type="primary"):
        if files:
            with st.spinner("正在处理并入库文档，请稍等..."):
                total_chunks = 0
                for f in files:
                    chunks_num = ingest_file(f, vector_db)
                    total_chunks += chunks_num
                st.success(f"成功入库 {total_chunks} 个文本块")
                st.rerun()
        else:
            st.warning("请先上传文档")

    # 修改清空库的实现
    if st.button("🗑️ 清空知识库与聊天记录"):
        if st.checkbox("我确认要删除所有向量数据和聊天记录（不可恢复）"):
            # 删除 FAISS 索引目录
            index_dir = os.path.join(DB_DIR, "faiss_index")
            if os.path.exists(index_dir):
                shutil.rmtree(index_dir)
                st.success("向量库已清空")

            # 清空聊天记录
            st.session_state.chat_history = []
            st.session_state.messages = []
            st.rerun()

    st.divider()

    # 获取当前库中所有文档名
    try:
        # 方法1：使用 similarity_search 检索一个无关查询，获取所有文档（FAISS 支持）
        # 查询一个不可能匹配的向量（如空字符串），k 设置为一个大数（如10000），即可拿到所有
        dummy_results = vector_db.similarity_search("", k=10000)
        all_sources = list(set(
            doc.metadata.get("source_file", "未知")
            for doc in dummy_results
            if doc.metadata.get("source_file") not in ["system"]  # 排除初始化空文档
        ))
    except Exception as e:
        print(f"获取文档列表失败: {e}")
        all_sources = []

    # 如果库是空的，all_sources 会为空列表
    selected_doc = st.selectbox(
        "🎯 检索范围",
        ["全部文档"] + sorted(all_sources),
        index=0
    )

    return selected_doc