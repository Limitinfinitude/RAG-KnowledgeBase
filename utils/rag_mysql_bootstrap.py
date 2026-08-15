"""RAG 扩展表种子：内置提示词（从 services.rag_prompts 抽取）、数据字典条目。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Tuple


def _system_body(pt: Any) -> str:
    return str(pt.messages[0].prompt.template)


def _dict_seeds() -> List[Tuple[str, str, str, str]]:
    """(table_name, column_name, zh_label, description)"""
    return [
        ("prompt_templates", "slug", "模板键", "与代码中模板标识一致，如 rephrase"),
        ("prompt_templates", "template_body", "提示词正文", "System 角色完整文本"),
        ("user_preferences", "pref_key", "偏好键", "如 theme、chat_prefs"),
        ("user_preferences", "pref_value", "偏好值", "JSON 字符串"),
        ("chat_sessions", "mode", "会话模式", "rag / instant / chat"),
        ("chat_sessions", "client_conv_key", "客户端会话键", "对齐前端 localStorage"),
        ("chat_messages", "meta_json", "消息元数据", "引用、耗时等 JSON"),
        ("ai_model_presets", "preset_name", "预设名", "用户多模型配置名称"),
        ("ai_model_presets", "api_key_stored", "密钥存储", "敏感字段，生产建议加密"),
        ("llm_call_logs", "call_type", "调用类型", "qa、rephrase、ingest 等"),
        ("llm_call_logs", "latency_ms", "耗时毫秒", "单次 LLM 调用"),
        ("kb_documents", "storage_path", "存储路径", "相对用户 knowledge_db 根"),
        ("kb_documents", "parse_status", "解析状态", "pending/done/error 等"),
        ("kb_chunks", "chunk_index", "块序号", "文档内顺序"),
        ("kb_chunks", "content_sha256", "内容摘要", "可选防重复"),
        ("document_parse_logs", "parser", "解析器", "pdf、docx、txt"),
        ("faiss_index_registry", "storage_key", "索引目录键", "如 faiss_index"),
        ("faiss_index_registry", "vector_count", "向量条数", "与索引文件同步"),
        ("faiss_vector_mapping", "faiss_internal_id", "FAISS 行号", "矩阵行下标"),
        ("sys_data_dictionary", "zh_label", "中文标签", "列中文短名"),
        ("app_settings", "payload", "配置 JSON", "全局 system_settings 合并后快照"),
        ("user_feedback", "status", "反馈状态", "open/processing/closed"),
        ("message_quality_feedback", "rating", "评价", "good 有用 / bad 需改进"),
        ("message_quality_feedback", "page_mode", "页面", "rag 知识库问答 / instant 即时文档"),
        ("login_failure", "reason", "失败原因", "unknown_user、bad_password 等"),
    ]


def bootstrap_rag_mysql_schema(conn: Any) -> None:
    """在已有 users 等基础表上写入种子（幂等）。"""
    now = datetime.now(timezone.utc).isoformat()

    try:
        from services.rag_prompts import qa_prompt, qa_prompt_hybrid, rephrase_prompt
    except Exception:
        return

    seeds = [
        ("rephrase", "意图识别与检索语句重写", _system_body(rephrase_prompt), "LangChain rephrase_prompt"),
        ("qa_rag", "知识库问答（仅文档）", _system_body(qa_prompt), "LangChain qa_prompt"),
        ("qa_hybrid", "知识库 + 联网摘要", _system_body(qa_prompt_hybrid), "LangChain qa_prompt_hybrid"),
    ]
    for slug, name, body, desc in seeds:
        if not (body or "").strip():
            continue
        ex = conn.execute(
            "SELECT id FROM prompt_templates WHERE slug = ? LIMIT 1",
            (slug,),
        ).fetchone()
        if ex:
            continue
        conn.execute(
            """
            INSERT INTO prompt_templates (
                slug, name, template_body, description, is_builtin, is_active, user_id, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, 1, NULL, 1, ?, ?)
            """,
            (slug, name, body, desc, now, now),
        )

    try:
        from utils.prompt_template_defaults import extra_prompt_seeds

        for slug, name, body, desc in extra_prompt_seeds():
            if not (body or "").strip():
                continue
            ex2 = conn.execute(
                "SELECT id FROM prompt_templates WHERE slug = ? LIMIT 1",
                (slug,),
            ).fetchone()
            if ex2:
                continue
            conn.execute(
                """
                INSERT INTO prompt_templates (
                    slug, name, template_body, description, is_builtin, is_active, user_id, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, 1, NULL, 1, ?, ?)
                """,
                (slug, name, body, desc, now, now),
            )
    except Exception:
        pass

    for table_name, column_name, zh_label, description in _dict_seeds():
        conn.execute(
            """
            INSERT IGNORE INTO sys_data_dictionary (table_name, column_name, zh_label, description)
            VALUES (?, ?, ?, ?)
            """,
            (table_name, column_name, zh_label, description),
        )
