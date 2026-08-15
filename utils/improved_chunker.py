# utils/improved_chunker.py
"""
改进的分块器：解决分块边界不自然和文档类型差异问题
"""
import re
import hashlib
from typing import List, Dict, Tuple, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ==================== 文档类型识别 ====================
def detect_document_type(text: str, file_type: str = "txt") -> str:
    """
    检测文档类型
    :param text: 文档内容
    :param file_type: 文件扩展名
    :return: "code" | "table" | "technical" | "prose" | "mixed"
    """
    # 代码特征检测
    code_patterns = [
        r'def\s+\w+\s*\(',           # Python函数
        r'class\s+\w+',              # 类定义
        r'function\s+\w+',           # JavaScript函数
        r'import\s+\w+',             # 导入语句
        r'#include',                 # C/C++包含
        r'public\s+class',           # Java类
        r'```[\s\S]*?```',          # Markdown代码块
    ]
    
    code_count = sum(len(re.findall(pattern, text, re.IGNORECASE)) for pattern in code_patterns)
    
    # 表格特征检测
    table_patterns = [
        r'\|.*\|',                   # Markdown表格
        r'\s+\|\s+',                 # 表格分隔符
        r'\t+',                      # Tab分隔
    ]
    
    table_count = sum(len(re.findall(pattern, text)) for pattern in table_patterns)
    
    # 技术文档特征（术语密集）
    technical_keywords = [
        'API', '函数', '参数', '返回值', '接口', '协议', '算法', '数据结构',
        '配置', '设置', '方法', '类', '对象', '变量', '常量'
    ]
    technical_count = sum(text.count(keyword) for keyword in technical_keywords)
    
    # 判断文档类型
    text_length = len(text)
    
    if code_count > text_length / 500:  # 代码密度高
        return "code"
    elif table_count > text_length / 1000:  # 表格密度高
        return "table"
    elif technical_count > text_length / 200:  # 技术术语密集
        return "technical"
    elif code_count > 0 or table_count > 0:
        return "mixed"
    else:
        return "prose"


# ==================== 结构化内容检测 ====================
def detect_code_blocks(text: str) -> List[Tuple[int, int, str]]:
    """
    检测代码块位置
    :param text: 文档内容
    :return: [(start, end, language), ...]
    """
    code_blocks = []
    
    # Markdown代码块
    pattern = r'```(\w+)?\n([\s\S]*?)```'
    for match in re.finditer(pattern, text):
        start = match.start()
        end = match.end()
        language = match.group(1) or "unknown"
        code_blocks.append((start, end, language))
    
    # Python代码块（缩进检测）
    lines = text.split('\n')
    in_code_block = False
    code_start = 0
    indent_threshold = 4
    
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped:
            continue
        
        indent = len(line) - len(stripped)
        is_code_line = (
            stripped.startswith(('def ', 'class ', 'import ', 'from ', 'if ', 'for ', 'while ')) or
            (indent >= indent_threshold and in_code_block)
        )
        
        if is_code_line and not in_code_block:
            in_code_block = True
            code_start = sum(len(lines[j]) + 1 for j in range(i))
        elif not is_code_line and in_code_block:
            in_code_block = False
            code_end = sum(len(lines[j]) + 1 for j in range(i))
            if code_end > code_start:
                code_blocks.append((code_start, code_end, "python"))
    
    return code_blocks


def detect_tables(text: str) -> List[Tuple[int, int]]:
    """
    检测表格位置
    :param text: 文档内容
    :return: [(start, end), ...]
    """
    tables = []
    
    # Markdown表格
    lines = text.split('\n')
    table_start = None
    
    for i, line in enumerate(lines):
        # 检查是否是表格行（包含 | 分隔符）
        if '|' in line and line.strip().startswith('|') and line.strip().endswith('|'):
            if table_start is None:
                table_start = sum(len(lines[j]) + 1 for j in range(i))
        elif table_start is not None:
            # 表格结束
            table_end = sum(len(lines[j]) + 1 for j in range(i))
            tables.append((table_start, table_end))
            table_start = None
    
    # 如果最后一行是表格，也要记录
    if table_start is not None:
        table_end = len(text)
        tables.append((table_start, table_end))
    
    return tables


# ==================== 句子完整性检查 ====================
def is_sentence_complete(text: str) -> bool:
    """
    检查文本是否以完整句子结尾
    :param text: 文本内容
    :return: True if complete, False otherwise
    """
    if not text.strip():
        return True
    
    # 检查是否以句子结束符结尾
    sentence_endings = ['。', '！', '？', '.', '!', '?', '\n\n']
    text_stripped = text.rstrip()
    
    # 检查最后几个字符
    last_chars = text_stripped[-3:] if len(text_stripped) >= 3 else text_stripped
    
    for ending in sentence_endings:
        if text_stripped.endswith(ending):
            return True
    
    return False


def fix_chunk_boundary(chunk_text: str, original_text: str, chunk_start: int) -> str:
    """
    修复chunk边界，确保句子完整
    :param chunk_text: 当前chunk文本
    :param original_text: 原始文档
    :param chunk_start: chunk在原文中的起始位置
    :return: 修复后的chunk文本
    """
    # 如果已经是完整句子，直接返回
    if is_sentence_complete(chunk_text):
        return chunk_text
    
    # 向前查找最近的句子结束符
    search_start = max(0, chunk_start - 200)  # 最多向前查找200字符
    search_text = original_text[search_start:chunk_start + len(chunk_text)]
    
    # 查找最后一个句子结束符
    sentence_endings = ['。', '！', '？', '.', '!', '?', '\n\n', '\n']
    last_end_pos = -1
    
    for ending in sentence_endings:
        pos = search_text.rfind(ending)
        if pos > last_end_pos:
            last_end_pos = pos
    
    if last_end_pos > 0:
        # 找到句子边界，调整chunk
        relative_pos = last_end_pos - (chunk_start - search_start)
        if relative_pos > 0 and relative_pos < len(chunk_text):
            # 截取到句子边界
            return chunk_text[:relative_pos + 1]
    
    # 如果找不到，尝试向后查找
    chunk_end = chunk_start + len(chunk_text)
    search_end = min(len(original_text), chunk_end + 200)
    search_text = original_text[chunk_start:search_end]
    
    for ending in sentence_endings:
        pos = search_text.find(ending, len(chunk_text))
        if pos > 0:
            # 找到句子边界，扩展chunk
            return search_text[:pos + 1]
    
    # 如果都找不到，返回原文本
    return chunk_text


# ==================== 改进的分块器 ====================
class ImprovedSmartChunker:
    """
    改进的智能分块器：支持文档类型识别和边界修复
    """
    
    def __init__(self):
        # 基础分块配置（会根据文档类型调整）
        self.base_configs = {
            "small": {"chunk_size": 300, "chunk_overlap": 50},
            "medium": {"chunk_size": 800, "chunk_overlap": 100},
            "large": {"chunk_size": 2000, "chunk_overlap": 200}
        }
        
        # 中文分隔符
        self.separators = [
            "\n\n\n", "\n\n", "\n", "。", "！", "？", "；", "，", " ", ""
        ]
    
    def get_config_for_doc_type(self, doc_type: str, level: str) -> Dict:
        """
        根据文档类型调整分块配置
        """
        base_config = self.base_configs[level].copy()
        
        if doc_type == "code":
            # 代码：增大chunk，减少重叠（函数/类应该完整）
            base_config["chunk_size"] = int(base_config["chunk_size"] * 1.5)
            base_config["chunk_overlap"] = int(base_config["chunk_overlap"] * 0.5)
        elif doc_type == "technical":
            # 技术文档：适当增大chunk（术语密集）
            base_config["chunk_size"] = int(base_config["chunk_size"] * 1.2)
        elif doc_type == "table":
            # 表格：保持原样（表格通常较小）
            pass
        elif doc_type == "prose":
            # 散文：可以适当减小chunk
            base_config["chunk_size"] = int(base_config["chunk_size"] * 0.9)
        
        return base_config
    
    def create_improved_chunks(
        self,
        text: str,
        source_file: str,
        file_type: str = "txt"
    ) -> Dict[str, List[Document]]:
        """
        创建改进的多层级分块
        """
        # 1. 检测文档类型
        doc_type = detect_document_type(text, file_type)
        
        # 2. 检测结构化内容
        code_blocks = detect_code_blocks(text)
        tables = detect_tables(text)
        
        # 3. 创建分块器（根据文档类型调整配置）
        splitters = {}
        for level in ["small", "medium", "large"]:
            config = self.get_config_for_doc_type(doc_type, level)
            splitters[level] = RecursiveCharacterTextSplitter(
                chunk_size=config["chunk_size"],
                chunk_overlap=config["chunk_overlap"],
                separators=self.separators,
                length_function=len
            )
        
        # 4. 创建各层级chunk
        result = {}
        base_doc = Document(
            page_content=text,
            metadata={"source_file": source_file, "file_type": file_type, "doc_type": doc_type}
        )
        
        for level, splitter in splitters.items():
            chunks = splitter.split_documents([base_doc])
            
            # 5. 修复chunk边界（确保句子完整）
            improved_chunks = []
            current_pos = 0
            
            for i, chunk in enumerate(chunks):
                chunk_text = chunk.page_content
                
                # 检查是否在代码块或表格中
                chunk_start_in_text = text.find(chunk_text[:50], current_pos)
                if chunk_start_in_text == -1:
                    chunk_start_in_text = current_pos
                
                # 修复边界
                fixed_text = fix_chunk_boundary(chunk_text, text, chunk_start_in_text)
                
                # 更新chunk内容
                chunk.page_content = fixed_text
                
                # 添加metadata
                chunk_id = hashlib.md5(fixed_text[:100].encode()).hexdigest()[:8]
                chunk.metadata.update({
                    "chunk_level": level,
                    "chunk_index": i,
                    "chunk_id": chunk_id,
                    "total_chunks": len(chunks),
                    "source_file": source_file,
                    "file_type": file_type,
                    "doc_type": doc_type,
                    "chunk_start": chunk_start_in_text,
                    "chunk_end": chunk_start_in_text + len(fixed_text),
                    "is_sentence_complete": is_sentence_complete(fixed_text)
                })
                
                improved_chunks.append(chunk)
                current_pos = chunk_start_in_text + len(fixed_text)
            
            result[level] = improved_chunks
        
        # 6. 处理代码块和表格（保持完整）
        if code_blocks or tables:
            result = self._preserve_structured_content(result, text, code_blocks, tables)
        
        return result
    
    def _preserve_structured_content(
        self,
        chunks_dict: Dict[str, List[Document]],
        original_text: str,
        code_blocks: List[Tuple[int, int, str]],
        tables: List[Tuple[int, int]]
    ) -> Dict[str, List[Document]]:
        """
        保护结构化内容（代码块、表格）不被拆分
        """
        # 这里可以实现更复杂的逻辑，确保代码块和表格不被拆分
        # 目前先返回原结果，后续可以优化
        return chunks_dict

