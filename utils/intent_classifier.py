# utils/intent_classifier.py
"""
对话路由层 · 轻量意图（闲聊 vs 检索问答）

与 `improved_query_classifier` 分工不同：
- **本模块**：在 `chat_turn` / `instant_chat_turn` 等入口处判断本轮是否走「免检索闲聊」，
  `classify_intent_lightweight` 返回 `"CHAT"` 或 `None`（`None` 表示走 RAG），不决定检索条数或 chunk 策略。
- **improved_query_classifier**：仅在检索管线内部使用，用于查询类型、fetch_k、chunk 层级等，
  不参与「要不要先调向量库」的路由决策。

勿将二者合并或混用职责，以免路由与检索参数纠缠。
"""
import re
from typing import Tuple, Optional


# 闲聊关键词（如果包含这些，很可能是闲聊）
CHAT_KEYWORDS = [
    # 问候语
    "你好", "hello", "hi", "嗨", "早上好", "下午好", "晚上好", "早安", "晚安",
    "再见", "拜拜", "bye",
    
    # 礼貌用语
    "谢谢", "感谢", "不客气", "没关系", "抱歉", "对不起",
    
    # 寒暄
    "你好吗", "怎么样", "最近", "在干嘛", "做什么", "忙什么",
    
    # 闲聊话题
    "天气", "今天", "明天", "星期", "几号", "几月",
    "笑话", "讲个", "说个", "聊聊", "聊天", "聊什么",
    
    # 关于系统本身的问题（不涉及知识库内容）
    "你是谁", "你是什么", "介绍一下", "介绍自己", "你叫什么", "你的名字",
    "你能做什么", "你能干什么", "你会什么", "你有什么功能", "功能有哪些",
    "怎么使用", "如何使用你", "怎么用", "使用方法", "使用说明",
    "你是ai", "你是机器人", "你是助手", "你是什么模型"
]

# 知识问答关键词（如果包含这些，很可能是知识查询）
RAG_KEYWORDS = [
    "什么是", "什么是", "定义", "解释", "说明", "介绍",
    "如何", "怎么", "怎样", "方法", "步骤", "流程",
    "为什么", "原因", "原理", "机制",
    "多少", "几个", "哪些", "什么", "哪个",
    "区别", "差异", "对比", "比较",
    "包含", "包括", "属于", "相关",
    "根据", "依据", "文档", "资料", "文件", "内容"
]

# 问题模式（正则表达式）
QUESTION_PATTERNS = [
    r"^(.+)[?？]$",  # 以问号结尾
    r"^(什么|怎么|如何|为什么|哪个|哪些|多少|几).+",  # 以疑问词开头
    r"(.+)(是什么|怎么做|如何做|为什么|有什么区别)",  # 包含疑问短语
]


def classify_intent_lightweight(query: str) -> Optional[str]:
    """
    企业级策略：默认RAG，识别少数明确闲聊和系统问题
    :param query: 用户查询
    :return: "CHAT" 或 None（默认走RAG）
    """
    query_lower = query.lower().strip()
    query_zh = query.strip()
    
    # 【优先识别】：避免浪费检索资源的问题
    
    # 1. 极简问候语（单独出现，长度<=5）
    if len(query_zh) <= 5:
        simple_greetings = ["你好", "hi", "hello", "嗨", "谢谢", "再见", "拜拜", "bye"]
        for greeting in simple_greetings:
            if query_lower == greeting or query_zh == greeting:
                return "CHAT"
    
    # 2. 感谢、再见（单独出现）
    if len(query_zh) <= 10:
        polite_words = ["谢谢你", "谢了", "多谢", "感谢", "再见了", "拜拜了"]
        for word in polite_words:
            if query_zh == word or query_lower == word:
                return "CHAT"
    
    # 3. 【关键新增】：关于系统本身的问题（不要检索文档）
    # 这些问题应该直接用LLM回答，而不是浪费资源检索文档
    system_questions = [
        # 身份相关
        "你是谁", "你是什么", "你叫什么", "你的名字", "你叫啥", "你是哪个",
        "介绍一下你", "介绍下你", "介绍自己", "自我介绍",

        # 功能相关
        "你能做什么", "你能干什么", "你会什么", "你有什么功能", "你可以做什么",
        "你能帮我什么", "你能帮我做什么", "你有哪些功能", "功能有哪些",
    ]

    # 使用相关的短语不能单独作为 CHAT 判据：
    # 「灭火器怎么使用」「怎么使用灭火器」是知识库问题，会被"怎么使用"子串误伤成闲聊（不检索）。
    # 只有同时出现系统指代词（你/系统/助手/平台/知识库…）才认为在问本系统的用法。
    usage_phrases = ["怎么使用", "如何使用", "怎么用", "使用方法", "使用说明",
                     "怎么问", "如何提问", "怎么提问"]
    system_refs = ["你", "系统", "助手", "平台", "知识库"]

    # 检查是否是系统问题（短问题，长度<30）
    if len(query_zh) < 30:
        for sq in system_questions:
            if sq in query_zh:
                return "CHAT"
        for up in usage_phrases:
            if up in query_zh and any(r in query_zh for r in system_refs):
                return "CHAT"
    
    # 其他所有情况：默认走RAG流程
    return None  # 返回None，默认走RAG


def classify_intent_with_llm(query: str, chat_history: list, llm_chain) -> Tuple[str, str]:
    """
    使用LLM判断意图（当轻量级方法无法确定时）
    :param query: 用户查询
    :param chat_history: 聊天历史
    :param llm_chain: LLM chain
    :return: (intent, optimized_query)
    """
    try:
        response = llm_chain.invoke({
            "input": query,
            "chat_history": chat_history
        })
        lines = response.strip().split("\n", 1)
        intent = lines[0].strip().upper() if lines else "CHAT"
        optimized_query = lines[1].strip() if len(lines) > 1 else query
        return intent, optimized_query
    except Exception as e:
        # 如果LLM调用失败，默认使用RAG模式
        return "RAG", query


def classify_intent(query: str, chat_history: list = None, llm_chain=None, 
                   use_lightweight_first: bool = True) -> Tuple[str, str]:
    """
    企业级意图分类：默认RAG，极少闲聊
    :param query: 用户查询
    :param chat_history: 聊天历史
    :param llm_chain: LLM chain（可选）
    :param use_lightweight_first: 是否优先使用轻量级方法
    :return: (intent, optimized_query)
    """
    # 先检查是否是明确的闲聊（问候、感谢、再见）
    lightweight_intent = classify_intent_lightweight(query)
    if lightweight_intent == "CHAT":
        return "CHAT", query
    
    # 其他所有情况：默认走RAG流程
    # 让LLM优化检索关键词（考虑上下文）
    if llm_chain:
        try:
            response = llm_chain.invoke({
                "input": query,
                "chat_history": chat_history or []
            })
            lines = response.strip().split("\n", 1)
            # 提取优化后的查询
            optimized_query = lines[1].strip() if len(lines) > 1 else query
            return "RAG", optimized_query
        except:
            return "RAG", query
    else:
        # 没有LLM chain，直接返回RAG
        return "RAG", query

