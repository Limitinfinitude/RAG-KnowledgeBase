"""RAG / 知识库 / 对话 等业务表的 MySQL DDL（与认证库同库，便于事务与备份）。"""
from __future__ import annotations

from typing import List

# 说明：以下为「完整系统」关系模型；运行时仍可能以本地 JSON/FAISS 为主，本库用于渐进迁移与审计。
# 不对 users(id) 建外键：遗留库里 users.id 可能为 BIGINT 有符号/INT 等，与 BIGINT UNSIGNED 会触发 MySQL 3780。
RAG_MYSQL_DDL: List[str] = [
    # —— 提示词模板（可覆盖原 services/rag_prompts.py 中写死的 system 段）——
    """
    CREATE TABLE IF NOT EXISTS prompt_templates (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        slug VARCHAR(64) NOT NULL COMMENT '唯一键，如 rephrase / qa_rag / qa_hybrid',
        name VARCHAR(128) NOT NULL DEFAULT '',
        template_body MEDIUMTEXT NOT NULL COMMENT 'system 提示全文；占位符与 LangChain 模板一致',
        description VARCHAR(512) NULL,
        is_builtin TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1=内置种子',
        is_active TINYINT(1) NOT NULL DEFAULT 1 COMMENT '0=停用则回退代码内建',
        updated_by_username VARCHAR(64) NULL COMMENT '管理端最后修改人',
        user_id BIGINT UNSIGNED NULL COMMENT '预留按用户覆盖；当前全局行均为 NULL',
        version INT NOT NULL DEFAULT 1,
        created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_prompt_slug (slug),
        KEY idx_prompt_user (user_id),
        KEY idx_prompt_active (is_active)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 用户偏好（键值，避免与 app_settings 全局配置混淆）——
    """
    CREATE TABLE IF NOT EXISTS user_preferences (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        pref_key VARCHAR(64) NOT NULL COMMENT '如 chat_prefs / theme / retrieval_defaults',
        pref_value MEDIUMTEXT NOT NULL COMMENT 'JSON 字符串',
        updated_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_user_pref (user_id, pref_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 对话会话 ——
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        title VARCHAR(512) NOT NULL DEFAULT '',
        mode VARCHAR(32) NOT NULL DEFAULT 'rag' COMMENT 'rag|instant|chat',
        client_conv_key VARCHAR(128) NULL COMMENT '前端 localStorage 会话 id 等',
        session_payload MEDIUMTEXT NULL COMMENT '即时档 instantDoc 等 JSON',
        created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL,
        KEY idx_chat_sess_user_mode_key (user_id, mode, client_conv_key),
        KEY idx_chat_sess_user_upd (user_id, updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 对话消息 ——
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        session_id BIGINT UNSIGNED NOT NULL,
        role VARCHAR(16) NOT NULL COMMENT 'user|assistant|system',
        content MEDIUMTEXT NULL,
        prompt_tokens INT NULL,
        completion_tokens INT NULL,
        sort_order INT NOT NULL DEFAULT 0,
        meta_json VARCHAR(4000) NULL COMMENT '引用、耗时等 JSON',
        created_at VARCHAR(40) NOT NULL,
        KEY idx_chat_msg_sess (session_id, sort_order),
        CONSTRAINT fk_chat_msg_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 单条消息的检索/联网证据（避免塞进 meta_json 被截断导致刷新后丢失）——
    """
    CREATE TABLE IF NOT EXISTS chat_message_evidence (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        message_id BIGINT UNSIGNED NOT NULL COMMENT 'chat_messages.id',
        sort_order INT NOT NULL DEFAULT 0 COMMENT '同条助手消息内顺序，对齐 sources 数组',
        evidence_json MEDIUMTEXT NOT NULL COMMENT '单条 source：index,file,content,score,chunk_level,metadata 等 JSON',
        created_at VARCHAR(40) NOT NULL,
        KEY idx_cme_msg_order (message_id, sort_order),
        CONSTRAINT fk_cme_message FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— AI 模型配置（多预设，对齐 Web api_config 形态）——
    """
    CREATE TABLE IF NOT EXISTS ai_model_presets (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        preset_name VARCHAR(64) NOT NULL COMMENT '展示名',
        provider VARCHAR(32) NOT NULL DEFAULT 'custom',
        base_url VARCHAR(768) NOT NULL DEFAULT '',
        model VARCHAR(128) NOT NULL DEFAULT '',
        api_key_stored MEDIUMTEXT NULL COMMENT '敏感；生产建议加密或仅占位',
        extra_json MEDIUMTEXT NULL COMMENT 'temperature 等 JSON',
        is_default TINYINT(1) NOT NULL DEFAULT 0,
        created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_ai_preset (user_id, preset_name),
        KEY idx_ai_preset_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 模型调用日志（与文件 statistics.json 可并存，便于 SQL 分析）——
    """
    CREATE TABLE IF NOT EXISTS llm_call_logs (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        session_id BIGINT UNSIGNED NULL,
        call_type VARCHAR(32) NOT NULL DEFAULT 'qa' COMMENT 'qa|rephrase|title|ingest|other',
        model VARCHAR(128) NULL,
        prompt_tokens INT NULL,
        completion_tokens INT NULL,
        total_tokens INT NULL,
        latency_ms DOUBLE NULL,
        api_path VARCHAR(256) NULL,
        success TINYINT(1) NOT NULL DEFAULT 1,
        error_message VARCHAR(4000) NULL,
        KEY idx_llm_log_user_time (user_id, created_at),
        KEY idx_llm_log_time (created_at),
        KEY idx_llm_log_session (session_id),
        KEY idx_llm_type_time (call_type, created_at),
        CONSTRAINT fk_llm_log_session FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 知识库文件（与 documents_metadata.json 可迁移对齐）——
    """
    CREATE TABLE IF NOT EXISTS kb_documents (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        file_name VARCHAR(512) NOT NULL,
        storage_path VARCHAR(1024) NOT NULL COMMENT '相对用户 knowledge_db 根的路径',
        category VARCHAR(128) NOT NULL DEFAULT '默认知识库',
        size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
        file_ext VARCHAR(32) NULL,
        parse_status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'pending|parsing|done|error|soft_deleted',
        chunk_count INT NOT NULL DEFAULT 0,
        description VARCHAR(2000) NULL,
        deleted_at VARCHAR(40) NULL,
        created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_kb_doc (user_id, category, file_name),
        KEY idx_kb_doc_user_status (user_id, parse_status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 文件分块 ——
    """
    CREATE TABLE IF NOT EXISTS kb_chunks (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        doc_id BIGINT UNSIGNED NOT NULL,
        chunk_index INT NOT NULL,
        char_start INT NULL,
        char_end INT NULL,
        token_count INT NULL,
        content_sha256 CHAR(64) NULL,
        preview VARCHAR(1000) NULL,
        created_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_kb_chunk (doc_id, chunk_index),
        KEY idx_kb_chunk_doc (doc_id),
        CONSTRAINT fk_kb_chunk_doc FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 文件解析日志 ——
    """
    CREATE TABLE IF NOT EXISTS document_parse_logs (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        doc_id BIGINT UNSIGNED NOT NULL,
        started_at VARCHAR(40) NOT NULL,
        finished_at VARCHAR(40) NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'started' COMMENT 'started|ok|error',
        parser VARCHAR(64) NULL COMMENT 'pdf|docx|txt',
        error_detail VARCHAR(4000) NULL,
        bytes_processed BIGINT UNSIGNED NULL,
        KEY idx_parse_doc (doc_id, started_at),
        CONSTRAINT fk_parse_doc FOREIGN KEY (doc_id) REFERENCES kb_documents(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— FAISS 索引登记（与磁盘 index 目录对应）——
    """
    CREATE TABLE IF NOT EXISTS faiss_index_registry (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        index_kind VARCHAR(32) NOT NULL DEFAULT 'flat' COMMENT 'flat|ivf 等',
        storage_key VARCHAR(256) NOT NULL COMMENT '如 faiss_index 目录标识',
        embedding_model VARCHAR(128) NULL,
        dimension INT NULL,
        vector_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
        linked_doc_count INT NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT 'building|active|stale',
        last_rebuilt_at VARCHAR(40) NULL COMMENT '上次重建向量索引时间',
        notes VARCHAR(512) NULL COMMENT '管理端备注',
        updated_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_faiss_reg (user_id, storage_key),
        KEY idx_faiss_reg_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— FAISS 向量与分块关联 ——
    """
    CREATE TABLE IF NOT EXISTS faiss_vector_mapping (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        faiss_index_id BIGINT UNSIGNED NOT NULL,
        kb_chunk_id BIGINT UNSIGNED NOT NULL,
        faiss_internal_id INT NOT NULL COMMENT 'FAISS 向量矩阵行号',
        created_at VARCHAR(40) NOT NULL,
        UNIQUE KEY uq_faiss_map (faiss_index_id, faiss_internal_id),
        KEY idx_faiss_map_chunk (kb_chunk_id),
        KEY idx_faiss_map_user (user_id),
        CONSTRAINT fk_faiss_map_index FOREIGN KEY (faiss_index_id) REFERENCES faiss_index_registry(id) ON DELETE CASCADE,
        CONSTRAINT fk_faiss_map_chunk FOREIGN KEY (kb_chunk_id) REFERENCES kb_chunks(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 入库/索引异步任务（与 FAISS 文件配合，供管理端展示队列）——
    """
    CREATE TABLE IF NOT EXISTS ingest_jobs (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        user_id BIGINT UNSIGNED NOT NULL,
        job_type VARCHAR(32) NOT NULL DEFAULT 'index' COMMENT 'index|reindex|delete_vector',
        status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'pending|running|done|error',
        payload_json VARCHAR(4000) NULL,
        error_message VARCHAR(2000) NULL,
        created_at VARCHAR(40) NOT NULL,
        updated_at VARCHAR(40) NOT NULL,
        KEY idx_ingest_user_time (user_id, created_at),
        KEY idx_ingest_status (status, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 单条助手消息质量反馈（问答页「有用 / 需改进」）——
    """
    CREATE TABLE IF NOT EXISTS message_quality_feedback (
        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        created_at VARCHAR(40) NOT NULL,
        user_id BIGINT UNSIGNED NULL,
        username VARCHAR(128) NULL,
        rating VARCHAR(16) NOT NULL COMMENT 'good|bad',
        page_mode VARCHAR(32) NOT NULL DEFAULT 'rag' COMMENT 'rag|instant',
        client_conv_id VARCHAR(128) NULL COMMENT '前端会话 id（localStorage）',
        message_index INT NULL COMMENT '该条 assistant 在会话 messages 中的下标',
        user_message_excerpt VARCHAR(2000) NULL COMMENT '紧邻上一轮用户问题摘要',
        assistant_excerpt MEDIUMTEXT NULL COMMENT '助手回复摘要',
        client_meta VARCHAR(1000) NULL COMMENT '可选备注 JSON',
        KEY idx_mqf_created (created_at),
        KEY idx_mqf_user_time (user_id, created_at),
        KEY idx_mqf_rating_time (rating, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    # —— 数据字典（给人看的元数据说明，可管理端维护）——
    """
    CREATE TABLE IF NOT EXISTS sys_data_dictionary (
        id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        table_name VARCHAR(64) NOT NULL,
        column_name VARCHAR(64) NOT NULL,
        zh_label VARCHAR(128) NOT NULL DEFAULT '',
        description VARCHAR(2000) NOT NULL DEFAULT '',
        UNIQUE KEY uq_dict_col (table_name, column_name)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

# 已存在旧表时补列（与 auth_db_backend.mysql_upgrade_schema 合并执行）
RAG_MYSQL_COLUMN_UPGRADES: List[tuple[str, str, str]] = [
    ("chat_sessions", "session_payload", "MEDIUMTEXT NULL"),
    ("prompt_templates", "is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
    ("prompt_templates", "updated_by_username", "VARCHAR(64) NULL"),
    ("faiss_index_registry", "last_rebuilt_at", "VARCHAR(40) NULL"),
    ("faiss_index_registry", "notes", "VARCHAR(512) NULL"),
]

# 补索引（已存在则忽略）
RAG_MYSQL_INDEX_TRY: List[str] = [
    "CREATE INDEX idx_llm_type_time ON llm_call_logs (call_type, created_at)",
    "CREATE INDEX idx_prompt_active ON prompt_templates (is_active)",
    "CREATE INDEX idx_chat_sess_user_mode_key ON chat_sessions (user_id, mode, client_conv_key)",
]

# 已存在列时尝试改类型（失败则忽略，如已是 MEDIUMTEXT）
RAG_MYSQL_ALTER_TRY: List[str] = [
    """
    ALTER TABLE chat_messages MODIFY COLUMN meta_json MEDIUMTEXT NULL
    COMMENT 'meta/timing/latency；检索片段在 chat_message_evidence'
    """,
]
