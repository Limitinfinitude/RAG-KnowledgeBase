# utils/smart_chunker.py
"""
智能分块策略：多层级分块 + 父子文档 + 文档摘要
解决固定chunk对抽象/概念/总结类问题失效的问题
"""
import re
import hashlib
from typing import List, Dict, Tuple, Optional
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ==================== 分块配置 ====================
CHUNK_CONFIGS = {
    # 小chunk：用于精确匹配（事实性问题）
    "small": {
        "chunk_size": 300,
        "chunk_overlap": 50,
        "description": "精确匹配层（事实问题）"
    },
    # 中chunk：用于上下文完整（解释性问题）
    "medium": {
        "chunk_size": 800,
        "chunk_overlap": 100,
        "description": "上下文层（解释问题）"
    },
    # 大chunk：用于章节级别（概念性问题）
    "large": {
        "chunk_size": 2000,
        "chunk_overlap": 200,
        "description": "章节层（概念问题）"
    }
}

# 中文分隔符（优先级从高到低）
CHINESE_SEPARATORS = [
    "\n\n\n",      # 章节分隔
    "\n\n",        # 段落分隔
    "\n",          # 行分隔
    "。",          # 句号
    "！",          # 感叹号
    "？",          # 问号
    "；",          # 分号
    "，",          # 逗号
    " ",           # 空格
    ""             # 字符级别
]


# ==================== 核心分块类 ====================
class SmartChunker:
    """
    智能分块器：支持多层级分块和父子文档策略
    """

    def __init__(self, level_configs: Optional[Dict[str, Dict]] = None):
        self._level_configs = level_configs if level_configs is not None else CHUNK_CONFIGS
        self.splitters = {}
        for level, config in self._level_configs.items():
            self.splitters[level] = RecursiveCharacterTextSplitter(
                chunk_size=config["chunk_size"],
                chunk_overlap=config["chunk_overlap"],
                separators=CHINESE_SEPARATORS,
                length_function=len
            )
    
    def create_multi_level_chunks(
        self, 
        text: str, 
        source_file: str,
        file_type: str = "txt"
    ) -> Dict[str, List[Document]]:
        """
        创建多层级分块（改进版：支持边界修复和文档类型识别）
        :param text: 原始文本
        :param source_file: 源文件名
        :param file_type: 文件类型
        :return: {"small": [...], "medium": [...], "large": [...], "summary": [...]}
        """
        result = {}
        
        # 【优化1】：检测文档类型
        from utils.improved_chunker import detect_document_type, is_sentence_complete, fix_chunk_boundary
        doc_type = detect_document_type(text, file_type)
        
        # 【优化2】：根据文档类型调整配置
        adjusted_configs = {}
        for level, config in self._level_configs.items():
            adjusted_config = config.copy()
            if doc_type == "code":
                # 代码：增大chunk，减少重叠
                adjusted_config["chunk_size"] = int(config["chunk_size"] * 1.5)
                adjusted_config["chunk_overlap"] = int(config["chunk_overlap"] * 0.5)
            elif doc_type == "technical":
                # 技术文档：适当增大chunk
                adjusted_config["chunk_size"] = int(config["chunk_size"] * 1.2)
            adjusted_configs[level] = adjusted_config
        
        # 基础文档
        base_doc = Document(
            page_content=text,
            metadata={"source_file": source_file, "file_type": file_type, "doc_type": doc_type}
        )
        
        # 1. 创建各层级chunk
        for level, splitter in self.splitters.items():
            # 如果配置被调整，创建新的splitter
            if level in adjusted_configs:
                config = adjusted_configs[level]
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=config["chunk_size"],
                    chunk_overlap=config["chunk_overlap"],
                    separators=CHINESE_SEPARATORS,
                    length_function=len
                )
            
            chunks = splitter.split_documents([base_doc])
            
            # 【优化3】：修复chunk边界，确保句子完整
            improved_chunks = []
            current_pos = 0
            
            for i, chunk in enumerate(chunks):
                chunk_text = chunk.page_content
                
                # 查找chunk在原文中的位置
                chunk_start = text.find(chunk_text[:50], current_pos)
                if chunk_start == -1:
                    chunk_start = current_pos
                
                # 修复边界
                fixed_text = fix_chunk_boundary(chunk_text, text, chunk_start)
                
                # 更新chunk内容
                chunk.page_content = fixed_text
                
                # 添加层级和位置信息
                chunk_id = self._generate_chunk_id(fixed_text)
                chunk.metadata.update({
                    "chunk_level": level,
                    "chunk_index": i,
                    "chunk_id": chunk_id,
                    "total_chunks": len(chunks),
                    "source_file": source_file,
                    "file_type": file_type,
                    "doc_type": doc_type,
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_start + len(fixed_text),
                    "is_sentence_complete": is_sentence_complete(fixed_text)
                })
                
                improved_chunks.append(chunk)
                current_pos = chunk_start + len(fixed_text)
            
            result[level] = improved_chunks
        
        # 2. 创建文档摘要（用于总结类问题）
        summary_chunk = self._create_summary_chunk(text, source_file, file_type)
        result["summary"] = [summary_chunk] if summary_chunk else []
        
        # 3. 建立父子关系
        self._build_parent_child_relations(result)
        
        return result
    
    def _generate_chunk_id(self, content: str) -> str:
        """生成chunk的唯一ID"""
        return hashlib.md5(content[:100].encode()).hexdigest()[:8]
    
    def _create_summary_chunk(
        self, 
        text: str, 
        source_file: str,
        file_type: str,
        use_llm: bool = False
    ) -> Optional[Document]:
        """
        创建文档摘要chunk（改进版：支持LLM生成高质量摘要）
        从文档中提取关键信息作为摘要
        """
        # 【优化5】：可选使用LLM生成摘要
        if use_llm:
            try:
                from services.llm_factory import build_chat_llm

                llm = build_chat_llm(0.0)
                
                # 如果文档太长，只取前5000字
                text_for_summary = text[:5000] if len(text) > 5000 else text
                
                prompt = f"""请为以下文档生成一个简洁的摘要（200-300字）：

文档内容：
{text_for_summary}

要求：
1. 提取文档的核心主题和关键信息
2. 总结文档的主要内容
3. 列出3-5个关键词
4. 格式：主题、主要内容、关键词"""
                
                llm_summary = llm.invoke(prompt).content
                
                return Document(
                    page_content=llm_summary,
                    metadata={
                        "source_file": source_file,
                        "file_type": file_type,
                        "chunk_level": "summary",
                        "chunk_index": 0,
                        "is_summary": True,
                        "original_length": len(text),
                        "summary_type": "llm_generated"
                    }
                )
            except Exception as e:
                logger.warning("[Summary] LLM生成摘要失败: %s，使用规则提取", e)
                # 回退到规则提取
        
        # 规则提取摘要（改进版）
        summary_parts = []
        
        # 1. 文件基本信息
        summary_parts.append(f"文档：{source_file}")
        
        # 2. 提取标题/章节（改进：提取更多结构信息）
        titles = self._extract_titles(text)
        if titles:
            summary_parts.append("章节：" + "、".join(titles[:15]))  # 增加到15个
        
        # 3. 提取首段作为概述（改进：提取前3段）
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if paragraphs:
            # 提取前3段（跳过太短的）
            overview_paras = []
            for para in paragraphs[:5]:
                if len(para) > 50:
                    overview_paras.append(para[:300])
                    if len(overview_paras) >= 3:
                        break
            if overview_paras:
                summary_parts.append(f"概述：\n" + "\n\n".join(overview_paras))
        
        # 4. 提取关键词（改进：使用更好的提取方法）
        keywords = self._extract_keywords_improved(text)
        if keywords:
            summary_parts.append("关键词：" + "、".join(keywords[:25]))  # 增加到25个
        
        # 5. 文档统计（改进：添加更多统计信息）
        char_count = len(text)
        para_count = len([p for p in text.split("\n\n") if p.strip()])
        line_count = len([l for l in text.split("\n") if l.strip()])
        summary_parts.append(f"统计：{char_count}字，约{para_count}段，{line_count}行")
        
        summary_text = "\n".join(summary_parts)
        
        return Document(
            page_content=summary_text,
            metadata={
                "source_file": source_file,
                "file_type": file_type,
                "chunk_level": "summary",
                "chunk_index": 0,
                "is_summary": True,
                "original_length": len(text),
                "summary_type": "rule_based"
            }
        )
    
    def _extract_keywords_improved(self, text: str) -> List[str]:
        """
        改进的关键词提取（使用TF-IDF思想）
        """
        # 分词（改进：更好的分词方法）
        words = re.split(r'[，。！？、；：\s\n]+', text)
        
        # 过滤和统计
        filtered = []
        for word in words:
            word = word.strip()
            # 保留2-10字的词
            if 2 <= len(word) <= 10:
                # 过滤纯数字和常见停用词（扩展停用词列表）
                stop_words = [
                    '的', '了', '是', '在', '和', '有', '这', '那', '说', '道',
                    '就', '也', '都', '还', '要', '会', '可以', '能够', '应该',
                    '一个', '两个', '三个', '一些', '很多', '非常', '特别'
                ]
                if not word.isdigit() and word not in stop_words:
                    filtered.append(word)
        
        # 统计词频
        word_count = {}
        for word in filtered:
            word_count[word] = word_count.get(word, 0) + 1
        
        # 按频率排序，返回高频词（改进：考虑文档长度）
        text_length = len(text)
        min_freq = max(2, text_length // 5000)  # 根据文档长度调整最小频率
        
        sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
        keywords = [word for word, count in sorted_words[:40] if count >= min_freq]
        
        return keywords
    
    def _extract_titles(self, text: str) -> List[str]:
        """提取章节标题"""
        titles = []
        
        # 匹配常见的章节格式
        patterns = [
            r'^第[一二三四五六七八九十百\d]+[章节回篇].*',  # 第X章
            r'^[一二三四五六七八九十]+[、.．].*',           # 一、xxx
            r'^\d+[、.．].*',                              # 1、xxx
            r'^#+\s+.*',                                   # Markdown标题
            r'^【.*】',                                    # 【标题】
        ]
        
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            for pattern in patterns:
                if re.match(pattern, line):
                    titles.append(line[:50])  # 限制长度
                    break
        
        return titles
    
    def _extract_first_paragraph(self, text: str) -> str:
        """提取首段"""
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        if paragraphs:
            # 跳过太短的段落（可能是标题）
            for para in paragraphs:
                if len(para) > 50:
                    return para[:500]
        return ""
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单的高频词提取）"""
        # 分词（简单按标点分割）
        words = re.split(r'[，。！？、；：\s]+', text)
        
        # 过滤
        filtered = []
        for word in words:
            word = word.strip()
            # 保留2-10字的词
            if 2 <= len(word) <= 10:
                # 过滤纯数字和常见停用词
                if not word.isdigit() and word not in ['的', '了', '是', '在', '和', '有', '这', '那', '说', '道']:
                    filtered.append(word)
        
        # 统计词频
        word_count = {}
        for word in filtered:
            word_count[word] = word_count.get(word, 0) + 1
        
        # 按频率排序，返回高频词
        sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_words[:30] if count >= 3]
    
    def _build_parent_child_relations(self, chunks_dict: Dict[str, List[Document]]):
        """
        建立父子关系：小chunk指向中chunk，中chunk指向大chunk（改进版：使用位置信息和chunk_id映射）
        """
        levels = ["small", "medium", "large"]
        
        # 【优化4】：建立chunk_id映射表，快速查找
        chunk_id_maps = {}
        for level in levels:
            if level in chunks_dict:
                chunk_id_maps[level] = {
                    chunk.metadata.get("chunk_id"): (i, chunk)
                    for i, chunk in enumerate(chunks_dict[level])
                }
        
        for i, level in enumerate(levels[:-1]):
            parent_level = levels[i + 1]
            
            if level not in chunks_dict or parent_level not in chunks_dict:
                continue
            
            child_chunks = chunks_dict[level]
            parent_chunks = chunks_dict[parent_level]
            
            if not parent_chunks:
                continue
            
            # 使用位置信息建立父子关系（更准确）
            for child in child_chunks:
                child_start = child.metadata.get("chunk_start")
                child_end = child.metadata.get("chunk_end")
                child_id = child.metadata.get("chunk_id")
                
                best_parent_idx = 0
                best_containment = 0
                
                if child_start is not None and child_end is not None:
                    # 方法1：使用位置信息（最准确）
                    for j, parent in enumerate(parent_chunks):
                        parent_start = parent.metadata.get("chunk_start")
                        parent_end = parent.metadata.get("chunk_end")
                        
                        if parent_start is not None and parent_end is not None:
                            # 检查子chunk是否在父chunk范围内
                            if parent_start <= child_start and child_end <= parent_end:
                                containment = (child_end - child_start) / max(1, parent_end - parent_start)
                                if containment > best_containment:
                                    best_containment = containment
                                    best_parent_idx = j
                
                if best_containment == 0:
                    # 方法2：回退到内容匹配
                    child_start_text = child.page_content[:50]
                    best_overlap = 0
                    
                    for j, parent in enumerate(parent_chunks):
                        if child_start_text in parent.page_content:
                            overlap = len(set(child.page_content) & set(parent.page_content))
                            if overlap > best_overlap:
                                best_overlap = overlap
                                best_parent_idx = j
                
                # 记录父chunk信息
                child.metadata["parent_chunk_index"] = best_parent_idx
                child.metadata["parent_chunk_level"] = parent_level
                
                # 记录父chunk的chunk_id（用于快速查找）
                if best_parent_idx < len(parent_chunks):
                    parent_chunk = parent_chunks[best_parent_idx]
                    parent_chunk_id = parent_chunk.metadata.get("chunk_id")
                    if parent_chunk_id:
                        child.metadata["parent_chunk_id"] = parent_chunk_id


# ==================== 查询类型识别 ====================
def classify_query_type(query: str) -> str:
    """
    识别查询类型，决定使用哪种分块策略
    :param query: 用户查询
    :return: "precise" | "concept" | "summary"
    """
    query = query.strip()
    
    # 总结类问题（需要全局视角）
    summary_patterns = [
        r"总结|概括|概述|简介|介绍|主题|主旨|中心思想",
        r"讲了什么|说了什么|写了什么|描述了什么",
        r"主要内容|核心内容|大意|要点|要义",
        r"全文|全书|整体|整篇|通篇",
        r"有哪些.*章|有几.*章|章节.*有哪些"
    ]
    for pattern in summary_patterns:
        if re.search(pattern, query):
            return "summary"
    
    # 概念类问题（需要上下文理解）
    concept_patterns = [
        r"什么是|是什么|定义|概念|含义|意思",
        r"为什么|原因|原理|机制|道理",
        r"如何|怎么|怎样|方法|步骤|流程|过程",
        r"区别|差异|不同|对比|比较|关系",
        r"特点|特征|特性|性格|品质|品格",
        r"作用|功能|意义|价值|影响"
    ]
    for pattern in concept_patterns:
        if re.search(pattern, query):
            return "concept"
    
    # 精确类问题（需要精确匹配）
    precise_patterns = [
        r"谁是|是谁|叫什么|名字",
        r"哪里|在哪|何处|地点|位置",
        r"什么时候|何时|时间|日期",
        r"多少|几个|几次|数量|数字",
        r"^.{0,10}的.{0,10}[是叫有在]",  # X的Y是什么
    ]
    for pattern in precise_patterns:
        if re.search(pattern, query):
            return "precise"
    
    # 默认使用概念类（平衡精确度和上下文）
    return "concept"


# ==================== 工具函数 ====================
def get_chunk_level_for_query(query_type: str) -> List[str]:
    """
    根据查询类型返回应该使用的chunk层级
    :param query_type: "precise" | "concept" | "summary"
    :return: chunk层级列表
    """
    if query_type == "summary":
        # 总结类：优先用摘要，其次大chunk
        return ["summary", "large"]
    elif query_type == "concept":
        # 概念类：优先用中chunk，兼顾大chunk
        return ["medium", "large"]
    else:  # precise
        # 精确类：优先用小chunk，返回时可以扩展到中chunk
        return ["small", "medium"]


def merge_chunks_by_level(chunks_dict: Dict[str, List[Document]], levels: List[str]) -> List[Document]:
    """
    合并指定层级的chunks
    """
    result = []
    for level in levels:
        if level in chunks_dict:
            result.extend(chunks_dict[level])
    return result


def _build_level_configs_for_run(doc_length_factor: float) -> Dict[str, Dict]:
    """合并系统管理端切片参数 + 文档长度因子，不修改全局 CHUNK_CONFIGS。"""
    from utils.web_system_settings import get_merged_chunk_levels

    merged_sizes = get_merged_chunk_levels()
    level_configs: Dict[str, Dict] = {}
    for level, config in CHUNK_CONFIGS.items():
        c = config.copy()
        if level in merged_sizes:
            c["chunk_size"] = merged_sizes[level]["chunk_size"]
            c["chunk_overlap"] = merged_sizes[level]["chunk_overlap"]
        if doc_length_factor != 1.0:
            c["chunk_size"] = int(c["chunk_size"] * doc_length_factor)
            c["chunk_overlap"] = int(c["chunk_overlap"] * doc_length_factor)
        level_configs[level] = c
    return level_configs


# ==================== 主入口 ====================
def smart_chunk_document(
    text: str,
    source_file: str,
    file_type: str = "txt",
    use_llm_summary: bool = False,
    doc_length_factor: float = 1.0
) -> Tuple[List[Document], Dict]:
    """
    智能分块主入口（改进版：支持动态参数适配和LLM摘要）
    :param text: 原始文本
    :param source_file: 源文件名
    :param file_type: 文件类型
    :param use_llm_summary: 是否使用LLM生成摘要（默认False，节省资源）
    :param doc_length_factor: 文档长度因子（用于动态调整chunk大小）
    :return: (所有chunks的列表, 分块统计信息)
    """
    chunker = SmartChunker(level_configs=_build_level_configs_for_run(doc_length_factor))
    chunks_dict = chunker.create_multi_level_chunks(text, source_file, file_type)
    
    # 【优化7】：可选使用LLM生成摘要
    if use_llm_summary:
        summary_chunk = chunker._create_summary_chunk(text, source_file, file_type, use_llm=True)
        if summary_chunk:
            chunks_dict["summary"] = [summary_chunk]
    
    # 合并所有层级的chunks
    all_chunks = []
    stats = {"total": 0}
    
    for level, chunks in chunks_dict.items():
        all_chunks.extend(chunks)
        stats[level] = len(chunks)
        stats["total"] += len(chunks)
    
    return all_chunks, stats

