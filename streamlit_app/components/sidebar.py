# components/sidebar.py
import streamlit as st
import os
import shutil
from utils.path_context import get_kb_dir
from utils.metadata_manager import get_categories
from services.ingest import ingest_file, MAX_FILE_SIZE_BYTES
from services.vector_queries import list_indexed_source_files

def render_sidebar(vector_db):
    st.header("知识管理")

    files = st.file_uploader(
        f"新增文档（支持PDF/TXT/DOCX/MD/Excel，最大{MAX_FILE_SIZE_BYTES / (1024*1024)}MB）",
        accept_multiple_files=True,
        type=["pdf", "txt", "docx", "doc", "md", "xlsx", "xls"]
    )
    
    # 显示文件大小信息
    if files:
        for file in files:
            file_size_mb = len(file.getbuffer()) / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_BYTES / (1024 * 1024):
                st.error(f"{file.name}: 文件大小 {file_size_mb:.2f}MB 超过限制")
            else:
                st.info(f"{file.name}: {file_size_mb:.2f}MB")
    
    default_category = st.selectbox("知识库", options=get_categories(), key="sidebar_category")

    if st.button("开始入库", type="primary"):
        if files:
            with st.spinner("正在处理并入库文档，请稍等..."):
                total_chunks = 0
                success_count = 0
                for f in files:
                    try:
                        file_size = len(f.getbuffer())
                        if file_size > MAX_FILE_SIZE_BYTES:
                            st.warning(f"{f.name} 超过大小限制，已跳过")
                            continue
                        chunks_num = ingest_file(f, vector_db, category=default_category)
                        total_chunks += chunks_num
                        success_count += 1
                    except Exception as e:
                        st.error(f"{f.name} 处理失败: {str(e)}")
                if success_count > 0:
                    st.success(f"成功入库 {success_count} 个文件，共 {total_chunks} 个文本块")
                    # 设置标志，触发 page_one.py 自动刷新向量库
                    st.session_state.vector_db_reload_needed = True
                st.rerun()
        else:
            st.warning("请先上传文档")

    # 修改清空库的实现
    if st.button("清空知识库与聊天记录"):
        if st.checkbox("我确认要删除所有向量数据和聊天记录（不可恢复）"):
            # 删除 FAISS 索引目录
            index_dir = os.path.join(get_kb_dir(), "faiss_index")
            if os.path.exists(index_dir):
                shutil.rmtree(index_dir)
                st.success("向量库已清空")

            # 清空聊天记录
            st.session_state.chat_history = []
            st.session_state.messages = []
            st.rerun()

    st.divider()

    all_sources = list_indexed_source_files(vector_db, k=10000)

    # 如果库是空的，all_sources 会为空列表
    selected_doc = st.selectbox(
        "检索范围",
        ["全部文档"] + sorted(all_sources),
        index=0
    )

    return selected_doc