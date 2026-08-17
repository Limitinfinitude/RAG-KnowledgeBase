# pages/page_two.py
import _project_root  # noqa: F401

import streamlit as st
import os
import shutil
from datetime import datetime
from config import DB_DIR
from services.ingest import ingest_file, MAX_FILE_SIZE_BYTES
from services.vector_store import load_embeddings_and_vector_db
from utils.metadata_manager import (
    get_all_documents, get_categories, add_category, delete_category,
    get_documents_by_category, update_document_metadata, delete_document_metadata,
    get_document_metadata
)
from utils.document_preview import (
    get_document_structure, preview_document_content
)
from utils.document_deleter import delete_document_from_vector_db
import utils.ui_utils
utils.ui_utils.load_custom_css()

st.title("知识库管理")

# pages/page_two.py 顶部也加一遍（保险）
if "model_mode" not in st.session_state:
    st.session_state.model_mode = "API 调用 (OpenAI)"
    st.session_state.ollama_base_url = "http://localhost:11434"
    st.session_state.ollama_model = "qwen2.5:7b"

# 重新加载向量库（管理页面独立；与问答页共用 services 加载逻辑）
if "vector_db_reload" in st.session_state and st.session_state.vector_db_reload:
    st.session_state.vector_db_reload = False
vector_db, embeddings = load_embeddings_and_vector_db()

index_dir = os.path.join(DB_DIR, "faiss_index")

# 初始化session state
if "selected_knowledge_base" not in st.session_state:
    st.session_state.selected_knowledge_base = "全部知识库"
if "editing_doc" not in st.session_state:
    st.session_state.editing_doc = None
if "previewing_doc" not in st.session_state:
    st.session_state.previewing_doc = None
if "deleting_doc" not in st.session_state:
    st.session_state.deleting_doc = None

# ==================== 顶部：知识库选择 ====================
st.markdown("---")
col1, col2, col3 = st.columns([3, 2, 1])

with col1:
    st.markdown("### 选择知识库")
    knowledge_bases = get_categories()
    selected_kb = st.selectbox(
        "选择要查看的知识库",
        options=["全部知识库"] + knowledge_bases,
        index=0 if st.session_state.selected_knowledge_base == "全部知识库" 
              else (knowledge_bases.index(st.session_state.selected_knowledge_base) + 1 
                    if st.session_state.selected_knowledge_base in knowledge_bases else 0),
        key="kb_selector",
        label_visibility="collapsed"
    )
    st.session_state.selected_knowledge_base = selected_kb

with col2:
    st.markdown("### 统计信息")
    all_docs = get_all_documents()
    if selected_kb == "全部知识库":
        kb_docs = all_docs
    else:
        kb_docs = get_documents_by_category(selected_kb)
    
    total_docs = len(kb_docs)
    total_chunks = sum(doc.get("chunks_count", 0) for doc in kb_docs)
    total_size = sum(doc.get("file_size_mb", 0) for doc in kb_docs)
    
    st.metric("文档数量", total_docs)
    st.metric("文本块总数", total_chunks)
    st.metric("总大小 (MB)", f"{total_size:.2f}")

with col3:
    st.markdown("### 操作")
    with st.popover("新建知识库", use_container_width=True):
        new_kb = st.text_input("知识库名称", key="new_kb_input")
        if st.button("创建", key="create_kb", use_container_width=True):
            if new_kb and new_kb.strip():
                if add_category(new_kb.strip()):
                    st.success(f"知识库 '{new_kb.strip()}' 创建成功")
                    st.rerun()
                else:
                    st.warning("知识库已存在")
            else:
                st.warning("请输入知识库名称")
    
    with st.popover("管理知识库", use_container_width=True):
        kb_list = get_categories()
        if kb_list:
            for kb in kb_list:
                kb_col1, kb_col2 = st.columns([3, 1])
                with kb_col1:
                    st.text(kb)
                with kb_col2:
                    if st.button("删除", key=f"del_kb_{kb}", use_container_width=True):
                        if kb != "默认知识库":
                            delete_category(kb)
                            st.success(f"知识库 '{kb}' 已删除")
                            if st.session_state.selected_knowledge_base == kb:
                                st.session_state.selected_knowledge_base = "全部知识库"
                            st.rerun()
                        else:
                            st.warning("不能删除默认知识库")

st.markdown("---")

# ==================== 使用Tabs组织功能 ====================
tab1, tab2, tab3 = st.tabs(["文档管理", "上传文档", "系统设置"])

# ==================== Tab 1: 文档管理 ====================
with tab1:
    if selected_kb == "全部知识库":
        display_docs = all_docs
        st.info(f"显示所有知识库的文档（共 {len(display_docs)} 个文档）")
    else:
        display_docs = get_documents_by_category(selected_kb)
        st.info(f"知识库「{selected_kb}」中的文档（共 {len(display_docs)} 个文档）")
    
    if display_docs:
        # 使用更清晰的卡片式布局
        for idx, doc_info in enumerate(display_docs):
            file_name = doc_info.get("file_name", "未知")
            file_type = doc_info.get("file_type", "")
            category = doc_info.get("category", "默认知识库")
            upload_time = doc_info.get("upload_time", "未知")
            chunks_count = doc_info.get("chunks_count", 0)
            file_size_mb = doc_info.get("file_size_mb", 0)
            description = doc_info.get("description", "")
            
            # 使用容器创建卡片效果
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.markdown(f"#### {file_name}")
                    st.caption(f"知识库: {category} | {chunks_count} 块 | {file_size_mb}MB | {upload_time}")
                    if description:
                        st.markdown(f"*{description}*")
                
                with col2:
                    if st.button("预览", key=f"preview_{file_name}", use_container_width=True):
                        st.session_state.previewing_doc = file_name
                        st.rerun()
                    if st.button("编辑", key=f"edit_{file_name}", use_container_width=True):
                        st.session_state.editing_doc = file_name
                        st.rerun()
                
                with col3:
                    if st.button("结构", key=f"structure_{file_name}", use_container_width=True):
                        st.session_state.previewing_doc = file_name
                        st.session_state.show_structure = True
                        st.rerun()
                    if st.button("删除", key=f"delete_{file_name}", use_container_width=True):
                        st.session_state.deleting_doc = file_name
                        st.rerun()
                
                st.markdown("---")
    else:
        st.info("该知识库中暂无文档" if selected_kb != "全部知识库" else "知识库中暂无文档")

# ==================== Tab 2: 上传文档 ====================
with tab2:
    st.markdown("### 上传新文档到知识库")
    
    # 选择目标知识库
    target_kb = st.selectbox(
        "选择目标知识库",
        options=get_categories(),
        key="upload_target_kb"
    )
    
    # 文件上传
    uploaded_files = st.file_uploader(
        f"选择文件（支持 PDF、TXT、DOCX、MD、Excel，最大 {MAX_FILE_SIZE_BYTES / (1024*1024)}MB）",
        accept_multiple_files=True,
        type=["pdf", "docx", "pptx", "txt", "md", "csv", "html", "xlsx", "xls", "jpg", "jpeg", "png"],
        key="kb_upload_page_two"
    )

    # 显示文件大小信息
    if uploaded_files:
        st.markdown("#### 待上传文件列表")
        file_info_cols = st.columns(3)
        for idx, file in enumerate(uploaded_files):
            file_size_mb = len(file.getbuffer()) / (1024 * 1024)
            col_idx = idx % 3
            with file_info_cols[col_idx]:
                if file_size_mb > MAX_FILE_SIZE_BYTES / (1024 * 1024):
                    st.error(f"{file.name}\n{file_size_mb:.2f}MB (超过限制)")
                else:
                    st.success(f"{file.name}\n{file_size_mb:.2f}MB")
    
    # 文档描述
    description = st.text_area("文档描述（可选）", key="upload_description", height=100)
    
    # 上传按钮
    if st.button("开始入库", type="primary", use_container_width=True):
        if uploaded_files:
            with st.spinner("正在处理并入库..."):
                total_chunks = 0
                success_count = 0
                error_files = []

                for file in uploaded_files:
                    try:
                        file_size = len(file.getbuffer())
                        if file_size > MAX_FILE_SIZE_BYTES:
                            error_files.append(f"{file.name} (超过大小限制)")
                            continue

                        chunks = ingest_file(file, vector_db, category=target_kb, description=description)
                        total_chunks += chunks
                        success_count += 1
                    except Exception as e:
                        error_files.append(f"{file.name} ({str(e)})")

                # 入库后立即保存
                os.makedirs(index_dir, exist_ok=True)
                vector_db.save_local(index_dir)

                if success_count > 0:
                    st.success(f"成功入库 {success_count} 个文件，共 {total_chunks} 个文本块")
                    # 设置标志，触发 page_one.py 自动刷新向量库
                    st.session_state.vector_db_reload_needed = True
                if error_files:
                    st.error(f"以下文件处理失败：{', '.join(error_files)}")
            st.rerun()
        else:
            st.warning("请先上传文件")

# ==================== Tab 3: 系统设置 ====================
with tab3:
    st.markdown("### 系统设置")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 索引管理")
        
        # 刷新向量库按钮
        if st.button("🔄 刷新向量库", use_container_width=True, type="primary"):
            st.session_state.vector_db_reload_needed = True
            st.success("向量库将在下次访问问答页面时刷新")
        st.caption("上传新文档后，如果问答页面没有检索到，点击此按钮刷新")
        
        st.markdown("---")
        
        if st.button("手动保存索引", use_container_width=True):
            os.makedirs(index_dir, exist_ok=True)
            vector_db.save_local(index_dir)
            st.success("索引已保存")

        if st.button("清空所有知识库", use_container_width=True, type="secondary"):
            if st.checkbox("确认清空（不可恢复）", key="clear_confirm"):
                if os.path.exists(index_dir):
                    shutil.rmtree(index_dir)
                metadata_file = os.path.join(DB_DIR, "documents_metadata.json")
                if os.path.exists(metadata_file):
                    os.remove(metadata_file)
                st.success("所有知识库已清空")
                st.rerun()

        st.download_button(
            label="下载索引备份说明",
            data="手动备份请复制 faiss_index 文件夹",
            file_name="backup_instruction.txt",
            help="FAISS 索引为文件夹形式，请复制 data/streamlit/knowledge_db/faiss_index",
            use_container_width=True
        )

    with col2:
        st.markdown("#### 系统信息")
        st.info(f"**索引路径**: `{index_dir}`")
        st.info(f"**最大文件大小**: {MAX_FILE_SIZE_BYTES / (1024*1024)}MB")
        st.info(f"**支持格式**: PDF, TXT, DOCX, MD, Excel")
        st.info(f"**知识库数量**: {len(get_categories())}")

# ==================== 文档预览模态 ====================
if st.session_state.previewing_doc:
    st.markdown("---")
    with st.container():
        st.markdown("### 文档预览")
        
        doc_metadata = get_document_metadata(st.session_state.previewing_doc)
        if doc_metadata:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("文件大小", f"{doc_metadata.get('file_size_mb', 0)} MB")
            col2.metric("分块数量", doc_metadata.get('chunks_count', 0))
            col3.metric("知识库", doc_metadata.get('category', '未知'))
            col4.metric("上传时间", doc_metadata.get('upload_time', '未知')[:10])
        
        # 显示结构或内容
        if st.session_state.get("show_structure", False):
            st.markdown("#### 文档结构")
            structure = get_document_structure(st.session_state.previewing_doc, vector_db)
            st.json(structure)
        else:
            st.markdown("#### 文档内容预览（前10个分块）")
            preview_content = preview_document_content(st.session_state.previewing_doc, vector_db, max_chunks=10)
            
            for chunk_info in preview_content:
                if "error" not in chunk_info:
                    with st.expander(f"分块 {chunk_info['chunk_id']} (页面: {chunk_info['page']}, 字符数: {chunk_info['chars']})"):
                        st.text(chunk_info['content'])
        
        if st.button("关闭预览", use_container_width=True):
            st.session_state.previewing_doc = None
            st.session_state.show_structure = False
            st.rerun()

# ==================== 文档编辑模态 ====================
if st.session_state.editing_doc:
    st.markdown("---")
    with st.container():
        st.markdown("### 编辑文档信息")
        
        doc_metadata = get_document_metadata(st.session_state.editing_doc)
        if doc_metadata:
            with st.form("edit_document_form"):
                new_category = st.selectbox(
                    "知识库",
                    options=get_categories(),
                    index=get_categories().index(doc_metadata.get('category', '默认知识库')) 
                           if doc_metadata.get('category', '默认知识库') in get_categories() else 0,
                    key="edit_category"
                )
                new_description = st.text_area(
                    "描述",
                    value=doc_metadata.get('description', ''),
                    key="edit_description",
                    height=100
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    submit = st.form_submit_button("保存", type="primary", use_container_width=True)
                with col2:
                    cancel = st.form_submit_button("取消", use_container_width=True)
                
                if submit:
                    update_document_metadata(
                        st.session_state.editing_doc,
                        category=new_category,
                        description=new_description
                    )
                    st.success("文档信息已更新")
                    st.session_state.editing_doc = None
                    st.rerun()
                
                if cancel:
                    st.session_state.editing_doc = None
                    st.rerun()
        else:
            st.warning("未找到文档元数据")
            if st.button("关闭"):
                st.session_state.editing_doc = None
                st.rerun()

# ==================== 文档删除确认模态 ====================
if st.session_state.deleting_doc:
    st.markdown("---")
    with st.container():
        st.markdown("### 删除文档确认")
        
        doc_metadata = get_document_metadata(st.session_state.deleting_doc)
        if doc_metadata:
            st.warning("**此操作将永久删除文档及其所有向量数据，无法恢复！**")
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.info(f"**文档名称**: {st.session_state.deleting_doc}")
                st.info(f"**所属知识库**: {doc_metadata.get('category', '未知')}")
                st.info(f"**分块数量**: {doc_metadata.get('chunks_count', 0)}")
                st.info(f"**文件大小**: {doc_metadata.get('file_size_mb', 0)} MB")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("确认删除", type="primary", key="confirm_delete", use_container_width=True):
                    try:
                        with st.spinner("正在删除文档，请稍候..."):
                            # 从向量库中安全删除文档
                            success, deleted_count = delete_document_from_vector_db(
                                st.session_state.deleting_doc,
                                vector_db,
                                embeddings
                            )
                            
                            if success:
                                st.success(f"文档已成功删除！删除了 {deleted_count} 个文本块")
                                # 标记需要重新加载向量库
                                st.session_state.vector_db_reload = True
                                st.session_state.deleting_doc = None
                                st.rerun()
                            else:
                                st.error("删除失败，请重试")
                    except Exception as e:
                        st.error(f"删除失败: {e}")
                        import traceback
                        st.code(traceback.format_exc())
            
            with col2:
                if st.button("取消", key="cancel_delete", use_container_width=True):
                    st.session_state.deleting_doc = None
                    st.rerun()
        else:
            st.warning("未找到文档元数据")
            if st.button("关闭"):
                st.session_state.deleting_doc = None
                st.rerun()
