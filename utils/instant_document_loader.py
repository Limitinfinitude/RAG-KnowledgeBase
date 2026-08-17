# utils/instant_document_loader.py
"""
即时文档加载器：用于文档问答页面
不经过向量库，直接解析文档内容供LLM使用

解析统一走 utils/document_parsers（与知识库入库、Web 即时对话同一套解析器），
本模块只负责临时文件管理与 Streamlit 错误展示。
"""
import os
import tempfile
from typing import List

import streamlit as st

from langchain_core.documents import Document

from utils.document_parsers import parse_file_to_documents


def parse_document_instant(uploaded_file) -> List[Document]:
    """
    即时解析文档（不经过向量库）
    支持的格式与知识库上传一致：pdf / docx / pptx / txt / md / csv / html / xlsx / xls

    :param uploaded_file: Streamlit上传的文件对象
    :return: 文档列表；解析失败时经 st.error 提示并返回空列表
    """
    temp_path = None
    try:
        # 1. 创建临时文件
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=file_ext,
                mode='wb'
        ) as tmp:
            tmp.write(uploaded_file.getbuffer())
            temp_path = tmp.name

        # 2. 统一解析
        return parse_file_to_documents(temp_path, uploaded_file.name)

    except Exception as e:
        st.error(f"文档解析失败: {str(e)}")
        return []
    finally:
        # 清理临时文件
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def combine_documents(docs_list: List[List[Document]]) -> str:
    """
    合并多个文档的内容为单个文本字符串

    :param docs_list: 文档列表的列表（每个文件对应一个文档列表）
    :return: 合并后的文本内容
    """
    combined_parts = []

    for file_docs in docs_list:
        if not file_docs:
            continue

        # 获取文件名
        file_name = file_docs[0].metadata.get("source_file", "未知文件")
        _file_type = file_docs[0].metadata.get("file_type", "")

        # 合并该文件的所有页面/段落
        file_content = "\n\n".join([doc.page_content for doc in file_docs])

        # 添加文件标识
        combined_parts.append(f"【文件：{file_name}】\n{file_content}")

    return "\n\n" + "="*80 + "\n\n".join(combined_parts)
