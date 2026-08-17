# utils/chat_responses.py
"""
闲聊回复逻辑
针对简单的问候和关于系统的问题，提供直接的回复，不查询知识库
"""
import random

# 问候语回复
GREETING_RESPONSES = [
    "你好！我是一个基于文档的智能问答助手。",
    "你好！有什么我可以帮助你的吗？",
    "Hi！我可以帮你查询文档中的信息。",
]

# 关于系统的回复
SYSTEM_INFO_RESPONSES = {
    "identity": [
        "我是一个RAG（检索增强生成）智能问答助手，专门帮助你从上传的文档中查找和理解信息。",
        "我是一个基于文档的问答系统，可以帮你快速检索和理解文档内容。",
    ],
    "capability": [
        "我可以帮你：\n1. 从上传的文档中检索相关信息\n2. 回答关于文档内容的问题\n3. 总结和分析文档内容\n\n请问你想了解文档中的什么信息？",
        "我的主要功能是：\n- 智能检索文档内容\n- 基于文档回答问题\n- 提供信息溯源\n\n你可以直接提问关于已上传文档的任何问题。",
    ],
    "usage": [
        "使用很简单：\n1. 在知识库管理页面上传你的文档\n2. 回到这里直接提问\n3. 我会从文档中检索相关信息来回答你\n\n你想了解什么内容呢？",
        "你可以直接提问关于文档内容的问题，例如：\n- '文档中提到的XXX是什么？'\n- '如何进行XXX操作？'\n- 'XXX和YYY有什么区别？'\n\n试试看吧！",
    ]
}

# 感谢回复
THANK_RESPONSES = [
    "不客气！还有什么我可以帮你的吗？",
    "很高兴能帮到你！",
    "不用谢！有其他问题随时问我。",
]

# 再见回复
GOODBYE_RESPONSES = [
    "再见！有问题随时回来找我。",
    "拜拜！期待下次为你服务。",
    "再见！祝你工作顺利！",
]


def get_chat_response(query: str) -> str:
    """
    根据用户查询返回合适的闲聊回复
    :param query: 用户查询
    :return: 回复文本
    """
    query_lower = query.lower().strip()
    query_zh = query.strip()
    
    # 问候语
    greetings = ["你好", "hello", "hi", "嗨", "早上好", "下午好", "晚上好"]
    for greeting in greetings:
        if query_lower == greeting or query_zh == greeting:
            return random.choice(GREETING_RESPONSES)
        # 前缀匹配必须落在词边界上，否则 "hipaa…" 会被当成 "hi" 问候
        rest = query_lower[len(greeting):]
        if query_lower.startswith(greeting) and (not rest or not rest[0].isalpha()):
            return random.choice(GREETING_RESPONSES)
    
    # 关于身份
    identity_keywords = ["你是谁", "你是什么", "你叫什么", "你的名字", "介绍一下", "介绍自己"]
    for keyword in identity_keywords:
        if keyword in query_zh:
            return random.choice(SYSTEM_INFO_RESPONSES["identity"])
    
    # 关于功能
    capability_keywords = ["你能做什么", "你能干什么", "你会什么", "你有什么功能", "功能有哪些"]
    for keyword in capability_keywords:
        if keyword in query_zh:
            return random.choice(SYSTEM_INFO_RESPONSES["capability"])
    
    # 关于使用
    usage_keywords = ["怎么使用", "如何使用", "怎么用", "使用方法", "使用说明"]
    for keyword in usage_keywords:
        if keyword in query_zh:
            return random.choice(SYSTEM_INFO_RESPONSES["usage"])
    
    # 感谢
    thank_keywords = ["谢谢", "感谢", "多谢"]
    for keyword in thank_keywords:
        if keyword in query_zh:
            return random.choice(THANK_RESPONSES)
    
    # 再见
    goodbye_keywords = ["再见", "拜拜", "bye", "goodbye"]
    for keyword in goodbye_keywords:
        if keyword in query_zh:
            return random.choice(GOODBYE_RESPONSES)
    
    # 默认闲聊回复
    return "我是一个基于文档的问答助手，请问你想了解文档中的什么信息呢？"

