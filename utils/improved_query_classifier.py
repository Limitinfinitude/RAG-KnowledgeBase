# utils/improved_query_classifier.py
"""
检索管线层 · 查询类型与召回参数

仅在 `services/retrieval.py` 等检索流程中使用：区分 precise/concept/summary 等类型，
并影响 fetch_k、chunk_level 偏好等。**不**用于判断「闲聊 vs RAG」；后者见
`utils/intent_classifier.py`（`classify_intent_lightweight`）。

两套分类器上下位关系：先由 intent 决定是否检索，再（若检索）由本模块细化检索策略。
"""
import re
from typing import Dict, List, Tuple, Optional
from langchain_core.prompts import ChatPromptTemplate

from services.llm_factory import build_chat_llm
from utils.prompt_runtime import get_query_classifier_system
from utils.rag_prompt_hardening import prepend_to_text_prompt


# 查询类型定义
QUERY_TYPES = {
    "precise": "精确类（事实性问题）",
    "concept": "概念类（解释性问题）",
    "summary": "总结类（全局性问题）",
    "comparison": "比较类（对比分析）",
    "conditional": "条件类（条件查询）",
    "reasoning": "推理类（逻辑推理）"
}


def classify_query_type_rule_based(query: str) -> str:
    """
    基于规则的查询类型识别（快速、容错性好）
    """
    query = query.strip()
    query_lower = query.lower()
    
    # 口语化表达映射（口语词 -> 正式表达列表）
    oral_mapping = {
        "咋": ["如何", "怎么", "怎样"],
        "啥": ["什么", "什么是"],
        "咋样": ["怎么样"],
        "咋办": ["怎么办"],
        "咋弄": ["怎么弄"],
        "咋做": ["怎么做"]
    }
    
    # 替换口语化表达（使用第一个正式表达）
    for oral, formal_list in oral_mapping.items():
        if oral in query:
            query = query.replace(oral, formal_list[0])  # 使用第一个正式表达
    
    # 1. 总结类（优先级最高，避免被其他规则误判）
    summary_patterns = [
        r"总结|概括|概述|简介|介绍|主题|主旨|中心思想",
        r"讲了什么|说了什么|写了什么|描述了什么",
        r"主要内容|核心内容|大意|要点|要义",
        r"全文|全书|整体|整篇|通篇",
        r"有哪些.*章|有几.*章|章节.*有哪些",
        r"文档.*内容|资料.*内容"
    ]
    for pattern in summary_patterns:
        if re.search(pattern, query):
            return "summary"
    
    # 2. 比较类
    comparison_patterns = [
        r"区别|差异|不同|对比|比较|关系|联系",
        r"哪个.*更好|哪个.*更|.*和.*的区别|.*与.*的区别",
        r"相比|相较|对比.*和"
    ]
    for pattern in comparison_patterns:
        if re.search(pattern, query):
            return "comparison"
    
    # 3. 条件类
    conditional_patterns = [
        r"满足.*条件|符合.*要求|达到.*标准",
        r"哪些.*满足|哪些.*符合|哪些.*达到",
        r"如果.*那么|假如.*则|当.*时",
        r"条件.*是|要求.*是|标准.*是"
    ]
    for pattern in conditional_patterns:
        if re.search(pattern, query):
            return "conditional"
    
    # 4. 推理类
    reasoning_patterns = [
        r"为什么|原因|原理|机制|道理|依据",
        r"如何.*判断|怎么.*判断|怎样.*判断",
        r"推导|推理|推断|推测",
        r"因为.*所以|由于.*因此"
    ]
    for pattern in reasoning_patterns:
        if re.search(pattern, query):
            return "reasoning"
    
    # 5. 概念类
    concept_patterns = [
        r"什么是|是什么|定义|概念|含义|意思",
        r"如何|怎么|怎样|方法|步骤|流程|过程",
        r"特点|特征|特性|性格|品质|品格",
        r"作用|功能|意义|价值|影响"
    ]
    for pattern in concept_patterns:
        if re.search(pattern, query):
            return "concept"
    
    # 6. 精确类（最后匹配，作为兜底）
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
    
    # 默认：概念类（平衡精确度和上下文）
    return "concept"


def classify_query_type_llm(query: str, chat_history: List = None) -> Tuple[str, float]:
    """
    使用LLM进行查询类型识别（更准确，但需要API调用）
    返回: (query_type, confidence)
    """
    try:
        llm = build_chat_llm(0.0)

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                prepend_to_text_prompt(get_query_classifier_system()),
            ),
            ("human", "查询：{query}")
        ])
        
        response = llm.invoke(prompt.format_messages(query=query))
        query_type = response.content.strip().lower()
        
        # 验证类型是否有效
        if query_type in QUERY_TYPES:
            return query_type, 0.9  # LLM分类置信度较高
        else:
            # 如果LLM返回无效类型，回退到规则分类
            return classify_query_type_rule_based(query), 0.7
    except Exception as e:
        print(f"[QueryClassifier] LLM分类失败: {e}，使用规则分类")
        return classify_query_type_rule_based(query), 0.5


def classify_query_type_hybrid(
    query: str,
    use_llm: bool = False,
    chat_history: List = None
) -> Tuple[str, float]:
    """
    混合分类：优先使用规则（快速），复杂情况使用LLM（准确）
    
    :param query: 查询文本
    :param use_llm: 是否使用LLM（默认False，快速模式）
    :param chat_history: 对话历史（用于LLM分类）
    :return: (query_type, confidence)
    """
    # 快速规则分类
    rule_type = classify_query_type_rule_based(query)
    
    # 判断是否需要LLM分类
    needs_llm = False
    if use_llm:
        # 如果查询包含多个类型关键词，使用LLM
        type_keywords_count = sum([
            len(re.findall(r"总结|概括|概述", query)),
            len(re.findall(r"区别|对比|比较", query)),
            len(re.findall(r"什么是|如何|为什么", query)),
            len(re.findall(r"满足|条件|如果", query))
        ])
        if type_keywords_count >= 2:
            needs_llm = True
    
    if needs_llm:
        return classify_query_type_llm(query, chat_history)
    else:
        return rule_type, 0.8  # 规则分类置信度


def get_chunk_level_for_query_improved(query_type: str) -> List[str]:
    """
    根据查询类型返回应该使用的chunk层级（改进版）
    """
    chunk_mapping = {
        "precise": ["small", "medium"],  # 精确类：优先小chunk
        "concept": ["medium", "large"],  # 概念类：优先中chunk
        "summary": ["summary", "large"],  # 总结类：优先摘要和大chunk
        "comparison": ["medium", "large"],  # 比较类：需要上下文
        "conditional": ["small", "medium"],  # 条件类：需要精确匹配
        "reasoning": ["medium", "large"]  # 推理类：需要上下文
    }
    return chunk_mapping.get(query_type, ["medium", "large"])


def get_retrieval_params_for_query(
    query_type: str,
    query_length: int,
    kb_doc_count: int = 0
) -> Dict:
    """
    根据查询类型和上下文动态调整检索参数
    
    :param query_type: 查询类型
    :param query_length: 查询长度（字符数）
    :param kb_doc_count: 知识库文档数量
    :return: 检索参数字典
    """
    base_k = 10
    
    # 根据查询类型调整
    type_multipliers = {
        "precise": 1.5,  # 精确类：较少召回
        "concept": 2.0,  # 概念类：中等召回
        "summary": 2.5,  # 总结类：更多召回
        "comparison": 2.0,  # 比较类：中等召回
        "conditional": 1.5,  # 条件类：较少召回
        "reasoning": 2.0  # 推理类：中等召回
    }
    multiplier = type_multipliers.get(query_type, 2.0)
    
    # 根据查询长度调整（短查询需要更少召回）
    if query_length < 10:
        length_factor = 0.8
    elif query_length > 50:
        length_factor = 1.2
    else:
        length_factor = 1.0
    
    # 根据知识库大小调整
    if kb_doc_count > 1000:
        kb_factor = 1.2  # 大知识库需要更多召回
    elif kb_doc_count < 100:
        kb_factor = 0.9  # 小知识库可以减少召回
    else:
        kb_factor = 1.0
    
    fetch_k = int(base_k * multiplier * length_factor * kb_factor)
    
    return {
        "fetch_k": fetch_k,
        "top_k": base_k,
        "similarity_threshold": 0.3
    }

