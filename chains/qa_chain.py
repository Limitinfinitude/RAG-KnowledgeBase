# chains/qa_chain.py
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser
from config import API_KEY, BASE_URL, LLM_MODEL

llm = ChatOpenAI(model=LLM_MODEL, api_key=API_KEY, base_url=BASE_URL, temperature=0)

qa_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是一个基于文档的【总结与事实陈述】助手。

【核心任务】：
1. 根据【文档资料】内容，总结并回答用户的问题。
2. 如果资料中的描述与用户提问意思一致，请进行关联并给出事实总结。
3. 严禁提及资料中完全不存在的虚假事实。
4. 回答必须体现出是从资料中总结出来的（例如：根据资料显示...）。

【约束】：
- 如果资料里没有相关动作的描述，才回答“根据现有资料无法回答”。
- 不要使用任何外部常识。

【文档资料】：
{context}"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}"),
])

qa_chain = qa_prompt | llm | StrOutputParser()