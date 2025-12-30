# pages/page_two.py
import streamlit as st
import os
import shutil
from datetime import datetime
from config import DB_DIR
from utils.file_loader import ingest_file
from utils.embedding import get_embeddings
from utils.db import get_vector_db
import utils.ui_utils
utils.ui_utils.load_custom_css()
st.title("📂 知识库管理")
# pages/page_two.py 顶部也加一遍（保险）
if "model_mode" not in st.session_state:
    st.session_state.model_mode = "API 调用 (OpenAI)"
    st.session_state.ollama_base_url = "http://localhost:11434"
    st.session_state.ollama_model = "qwen2.5:7b"
# 重新加载向量库（管理页面独立）
embeddings = get_embeddings()
vector_db = get_vector_db(embeddings)

index_dir = os.path.join(DB_DIR, "faiss_index")

# ------------------- 上传文档 -------------------
st.subheader("📤 上传新文档")
uploaded_files = st.file_uploader(
    "选择 PDF 或 TXT 文件（支持多选）",
    accept_multiple_files=True,
    type=["pdf", "txt"],
    key="kb_upload_page_two"
)

if st.button("🔄 开始入库", type="primary"):
    if uploaded_files:
        with st.spinner("正在处理并入库..."):
            total_chunks = 0
            for file in uploaded_files:
                total_chunks += ingest_file(file, vector_db)
            # 入库后立即保存
            os.makedirs(index_dir, exist_ok=True)
            vector_db.save_local(index_dir)
            st.success(f"成功入库 {total_chunks} 个文本块")
            st.rerun()
    else:
        st.warning("请先上传文件")

# ------------------- 已上传文档列表 -------------------
st.subheader("📋 已上传文档列表")
try:
    docs = vector_db.similarity_search("", k=30000)
    real_docs = [d for d in docs if d.metadata.get("source_file") not in ["system", None]]

    if real_docs:
        from collections import defaultdict
        stats = defaultdict(lambda: {"chunks": 0, "type": ""})
        for d in real_docs:
            name = d.metadata["source_file"]
            stats[name]["chunks"] += 1
            stats[name]["type"] = "PDF" if name.lower().endswith(".pdf") else "TXT"

        data = [
            {
                "文档名称": name,
                "分块数量": info["chunks"],
                "文件类型": info["type"],
                "上传时间": "未知"  # 可后续加时间元数据
            }
            for name, info in stats.items()
        ]
        st.dataframe(data, use_container_width=True)
    else:
        st.info("知识库中暂无文档")
except Exception as e:
    st.error(f"读取失败: {e}")

# ------------------- 索引管理 -------------------
st.subheader("🗄️ 索引操作")
c1, c2, c3 = st.columns(3)

with c1:
    if st.button("💾 手动保存索引"):
        os.makedirs(index_dir, exist_ok=True)
        vector_db.save_local(index_dir)
        st.success("索引已保存")

with c2:
    if st.button("🗑️ 清空知识库"):
        if st.checkbox("⚠️ 确认清空（不可恢复）"):
            if os.path.exists(index_dir):
                shutil.rmtree(index_dir)
                st.success("知识库已清空")
                st.rerun()

with c3:
    st.download_button(
        label="📥 下载索引备份",
        data="手动备份请复制 faiss_index 文件夹",
        file_name="backup_instruction.txt",
        help="FAISS 索引为文件夹形式，请直接复制 knowledge_db/faiss_index"
    )

st.caption(f"索引存储路径：`{index_dir}`")