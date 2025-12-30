# chains/intent_rephrase.py
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from config import API_KEY, BASE_URL, LLM_MODEL

llm = ChatOpenAI(model=LLM_MODEL, api_key=API_KEY, base_url=BASE_URL, temperature=0)

rephrase_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是一个智能助手。请严格按照以下规则处理用户输入：
1. 如果是闲聊/无关问题，直接回复'CHAT'并在下一行输出原问题。
2. 如果是知识查询/需要检索的问题，回复'RAG'并在下一行输出优化后的检索语句（仅优化检索效率，不要添加外部信息）。
只输出两行：
第一行：意图（CHAT 或 RAG）
第二行：最终语句（原问题或优化后的检索语句）"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])

rephrase_chain = rephrase_prompt | llm | StrOutputParser()