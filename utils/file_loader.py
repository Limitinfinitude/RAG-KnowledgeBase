# utils/file_loader.py
import os
import tempfile
import traceback
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from config import TESSERACT_CMD, DB_DIR

# 设置Tesseract路径
pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def ingest_file(uploaded_file, vector_db):
    """
    处理上传的文件并入库
    :param uploaded_file: Streamlit上传的文件对象
    :param vector_db: 向量数据库实例
    :return: 处理后的文本块数量
    """
    temp_path = None
    try:
        # 1. 创建临时文件（修复：确保文件扩展名正确）
        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=file_ext,
                mode='wb'
        ) as tmp:
            tmp.write(uploaded_file.getbuffer())  # 修复：使用getbuffer()替代read()
            temp_path = tmp.name

        # 2. 根据文件类型处理
        docs = []
        if file_ext == '.txt':
            # 处理TXT文件
            with open(temp_path, 'rb') as f:
                raw_data = f.read()

            # 多编码尝试解码
            decoded_text = None
            encodings = ['utf-8', 'gb18030', 'gbk', 'latin-1']
            for enc in encodings:
                try:
                    decoded_text = raw_data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue

            if decoded_text is None:
                raise ValueError(f"无法解码文件 {uploaded_file.name}，不支持的编码格式")

            docs = [Document(
                page_content=decoded_text.strip(),
                metadata={"source_file": uploaded_file.name}
            )]

        elif file_ext == '.pdf':
            # 处理PDF文件
            try:
                # 首先尝试直接读取文本
                loader = PyPDFLoader(temp_path)
                pdf_docs = loader.load()

                # 检查是否提取到有效文本
                has_text = any(doc.page_content.strip() for doc in pdf_docs)

                if not has_text:
                    # OCR处理图片型PDF
                    st_images = convert_from_path(
                        temp_path,
                        poppler_path=None,  # 根据需要设置poppler路径
                        fmt='png',
                        dpi=300
                    )

                    # 逐页OCR
                    ocr_text = []
                    for i, img in enumerate(st_images):
                        try:
                            page_text = pytesseract.image_to_string(img, lang='chi_sim')
                            ocr_text.append(f"第{i + 1}页：\n{page_text}")
                        except Exception as e:
                            print(f"第{i + 1}页OCR失败: {e}")
                            ocr_text.append(f"第{i + 1}页：OCR识别失败")

                    full_text = "\n\n".join(ocr_text)
                    docs = [Document(
                        page_content=full_text,
                        metadata={"source_file": uploaded_file.name}
                    )]
                else:
                    # 文本型PDF，更新metadata
                    docs = []
                    for i, doc in enumerate(pdf_docs):
                        doc.metadata.update({
                            "source_file": uploaded_file.name,
                            "page": i + 1
                        })
                        docs.append(doc)

            except Exception as e:
                raise RuntimeError(f"PDF处理失败: {str(e)}\n{traceback.format_exc()}")

        else:
            print(f"不支持的文件类型: {file_ext}")
            return 0

        # 3. 文本分块（修复：优化分块参数）
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800,
            chunk_overlap=80,  # 修复：降低重叠率，避免冗余
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
            length_function=len
        )

        chunks = splitter.split_documents(docs)

        # 4. 确保每个chunk都有正确的metadata
        for chunk in chunks:
            chunk.metadata["source_file"] = uploaded_file.name
            chunk.metadata["file_type"] = file_ext.lstrip('.')

        # 5. 批量添加到向量库（修复：使用批量添加）
        if chunks:
            # FAISS 支持 add_documents，和 Chroma 接口完全兼容
            vector_db.add_documents(chunks)
            print(f"成功入库 {len(chunks)} 个文本块，文件：{uploaded_file.name}")
            # 显式保存 FAISS 索引
            index_dir = os.path.join(DB_DIR, "faiss_index")
            os.makedirs(index_dir, exist_ok=True)
            vector_db.save_local(index_dir)
            print(f"FAISS 索引已保存到: {index_dir}")
        return len(chunks)

    except Exception as e:
        print(f"文件处理失败 {uploaded_file.name}: {str(e)}")
        print(traceback.format_exc())
        raise  # 抛出异常让上层处理

    finally:
        # 清理临时文件（修复：确保文件关闭后删除）
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                print(f"删除临时文件失败 {temp_path}: {e}")