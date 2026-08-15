# utils/conversation_storage.py
"""
对话历史持久化存储模块
"""
import logging
import os
import json
from typing import Any, Dict, List, Optional

from utils.path_context import get_kb_dir

logger = logging.getLogger(__name__)


def _conversations_file() -> str:
    return os.path.join(get_kb_dir(), "conversations.json")


def _doc_qa_file() -> str:
    return os.path.join(get_kb_dir(), "doc_qa_messages.json")


def init_conversations_if_needed(session_state: Any) -> None:
    """
    每个浏览器会话首次运行时从磁盘加载多轮对话（应在 app 入口调用，避免未进问答页时 session 未初始化）。
    """
    if "conversations" not in session_state:
        saved = load_conversations()
        if saved:
            session_state.conversations = saved
        else:
            session_state.conversations = {
                "默认对话": {"messages": [], "chat_history": [], "metadata": {}}
            }
    if "current_conversation" not in session_state:
        session_state.current_conversation = "默认对话"
    if session_state.current_conversation not in session_state.conversations:
        session_state.conversations[session_state.current_conversation] = {
            "messages": [],
            "chat_history": [],
            "metadata": {},
        }


def sync_session_conversation_to_storage(session_state: Any) -> None:
    """将当前会话的 messages/chat_history 写回 conversations 并保存（每轮脚本末尾调用）。"""
    if "conversations" not in session_state or "current_conversation" not in session_state:
        return
    cname = session_state.current_conversation
    if cname not in session_state.conversations:
        session_state.conversations[cname] = {
            "messages": [],
            "chat_history": [],
            "metadata": {},
        }
    session_state.conversations[cname] = {
        "messages": list(session_state.get("messages", [])),
        "chat_history": session_state.get("chat_history", []),
        "metadata": session_state.conversations[cname].get("metadata", {}),
    }
    try:
        save_conversations(session_state.conversations)
    except Exception as e:
        logger.exception("同步对话到磁盘失败: %s", e)


def rebuild_doc_qa_chat_history(messages: List[dict]) -> List:
    from langchain_core.messages import AIMessage, HumanMessage

    hist = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "") or ""
        if role == "user":
            hist.append(HumanMessage(content=content))
        elif role == "assistant":
            hist.append(AIMessage(content=content))
    return hist


def hydrate_doc_qa_session(session_state: Any) -> None:
    """首次进入文档问答页时从磁盘恢复消息列表与 LangChain chat_history。"""
    if "doc_qa_messages" in session_state:
        if "doc_qa_chat_history" not in session_state:
            session_state.doc_qa_chat_history = rebuild_doc_qa_chat_history(
                session_state.doc_qa_messages
            )
        return
    saved = load_doc_qa_messages()
    session_state.doc_qa_messages = saved if saved else []
    session_state.doc_qa_chat_history = rebuild_doc_qa_chat_history(
        session_state.doc_qa_messages
    )


def load_doc_qa_messages() -> Optional[List[dict]]:
    dq = _doc_qa_file()
    if not os.path.exists(dq):
        return None
    try:
        with open(dq, "r", encoding="utf-8") as f:
            data = json.load(f)
        msgs = data.get("messages")
        return msgs if isinstance(msgs, list) else None
    except Exception as e:
        logger.warning("加载文档问答记录失败: %s", e)
        return None


def save_doc_qa_messages(messages: List[dict]) -> None:
    try:
        dq = _doc_qa_file()
        os.makedirs(get_kb_dir(), exist_ok=True)
        tmp = dq + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"messages": messages}, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, dq)
    except Exception as e:
        logger.exception("保存文档问答记录失败: %s", e)


def load_conversations():
    """从文件加载对话历史"""
    cf = _conversations_file()
    if os.path.exists(cf):
        try:
            with open(cf, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 转换chat_history从字典格式回到LangChain消息对象
                from langchain_core.messages import HumanMessage, AIMessage
                
                for name, conv in data.items():
                    chat_history = []
                    for msg_dict in conv.get("chat_history", []):
                        if msg_dict.get("type") == "human":
                            chat_history.append(HumanMessage(content=msg_dict.get("content", "")))
                        elif msg_dict.get("type") == "ai":
                            chat_history.append(AIMessage(content=msg_dict.get("content", "")))
                    conv["chat_history"] = chat_history
                    
                    # 【修复】：确保messages和chat_history同步
                    # 如果messages有数据但chat_history为空，尝试从messages重建chat_history
                    if len(conv.get("messages", [])) > 0 and len(chat_history) == 0:
                        for msg in conv.get("messages", []):
                            if msg.get("role") == "user":
                                chat_history.append(HumanMessage(content=msg.get("content", "")))
                            elif msg.get("role") == "assistant":
                                chat_history.append(AIMessage(content=msg.get("content", "")))
                        conv["chat_history"] = chat_history
                
                return data
        except Exception as e:
            logger.warning("加载对话历史失败: %s", e)
            return {}
    return {}


def save_conversations(conversations):
    """保存对话历史到文件"""
    try:
        os.makedirs(get_kb_dir(), exist_ok=True)
        # 转换消息对象为可序列化的格式
        serializable_conv = {}
        for name, conv in conversations.items():
            # 处理chat_history（LangChain消息对象）
            chat_history_serialized = []
            for msg in conv.get("chat_history", []):
                if hasattr(msg, 'content'):
                    # LangChain消息对象
                    msg_type = "human" if msg.__class__.__name__ == "HumanMessage" else "ai"
                    chat_history_serialized.append({
                        "type": msg_type,
                        "content": msg.content
                    })
                elif isinstance(msg, dict):
                    chat_history_serialized.append(msg)
                else:
                    chat_history_serialized.append({"type": "unknown", "content": str(msg)})
            
            serializable_conv[name] = {
                "messages": conv.get("messages", []),
                "chat_history": chat_history_serialized,
                "metadata": conv.get("metadata", {})
            }
        
        cf = _conversations_file()
        tmp_path = cf + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                serializable_conv,
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        os.replace(tmp_path, cf)
    except Exception as e:
        logger.exception("保存对话历史失败: %s", e)


def add_message_to_conversation(conversation_name, role, content, metadata=None):
    """添加消息到对话"""
    conversations = load_conversations()
    if conversation_name not in conversations:
        conversations[conversation_name] = {
            "messages": [],
            "chat_history": [],
            "metadata": {}
        }
    
    conversations[conversation_name]["messages"].append({
        "role": role,
        "content": content,
        "metadata": metadata or {}
    })
    
    save_conversations(conversations)

