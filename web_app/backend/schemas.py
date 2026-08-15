"""Web API 请求/响应模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    selected_kb: str = "全部知识库"
    search_mode: str = "vector"
    enable_reranker: bool = False
    enable_web_search: bool = Field(
        False,
        description="为 True 时在知识库检索后追加网页摘要；供应商与密钥由管理端 system_settings（默认博查）或环境变量配置。",
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    api_config_name: Optional[str] = None
    retrieval_k: int = Field(10, ge=3, le=30)
    response_style: str = "balanced"
    persona_prompt: Optional[str] = Field(default=None, max_length=8000)
    stream: bool = Field(
        False,
        description="为 True 时返回 NDJSON 流（application/x-ndjson），避免单独路径被静态资源抢占。",
    )


class ChatResponse(BaseModel):
    answer: str
    mode: str
    retrieval_query: str = ""
    sources: List[dict] = Field(default_factory=list)
    error: Optional[str] = None


class InstantDocParseResponse(BaseModel):
    ok: bool
    text: str = ""
    file_name: str = ""
    char_count: int = 0
    error: Optional[str] = None


class InstantChatRequest(BaseModel):
    """即时文档问答：正文由前端保存在当前会话；按全文（超长截断）构造上下文，不走向量库；开启联网时响应可含网页摘要溯源（与知识库问答 sources 结构一致）。"""

    message: str = Field(..., min_length=1)
    history: List[ChatMessage] = Field(default_factory=list)
    document_text: str = Field(default="", max_length=100_000)
    document_file_name: str = Field(default="", max_length=512)
    enable_web_search: bool = Field(
        False,
        description="为 True 时在文档上下文后追加网页摘要（无文档且非闲聊时亦可仅依据联网摘要回答）；供应商与密钥同智能问答页。",
    )
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    api_config_name: Optional[str] = None
    response_style: str = "balanced"
    persona_prompt: Optional[str] = Field(default=None, max_length=8000)
    stream: bool = Field(
        False,
        description="为 True 时返回 NDJSON 流。",
    )


class ConversationTitleBody(BaseModel):
    """根据用户首条消息生成侧栏会话标题（短句）。"""

    message: str = Field(..., min_length=1, max_length=4000)
    api_config_name: Optional[str] = None


class ConversationTitleResponse(BaseModel):
    title: str = ""


class ConfigSaveBody(BaseModel):
    preset: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    provider: str = "custom"


class ConfigTestBody(BaseModel):
    base_url: str
    api_key: str
    model: str


class DocMetaPatch(BaseModel):
    file_name: str
    category: Optional[str] = None
    description: Optional[str] = None


class CategoryCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class ClearAllBody(BaseModel):
    confirm: bool = False


class RegisterBody(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class MePatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: Optional[str] = Field(None, max_length=32)
    avatar: Optional[str] = None


class AdminRoleBody(BaseModel):
    role: Literal["admin", "user"]


class AdminUserCreateBody(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"


class AdminUserPatchBody(BaseModel):
    nickname: Optional[str] = Field(None, min_length=1, max_length=32)
    role: Optional[Literal["admin", "user"]] = None
    status: Optional[Literal["active", "disabled"]] = None


class WebUiStatePutBody(BaseModel):
    """与前端 localStorage 对齐的字段；均为可选，未传的键不覆盖服务端已有值。"""

    conversation_store: Optional[str] = Field(
        default=None,
        description="知识库智能问答会话 rag_web_ui_v2_u_*（无 _instant 后缀）",
        max_length=8_000_000,
    )
    conversation_store_instant: Optional[str] = Field(
        default=None,
        description="即时文档问答会话 rag_web_ui_v2_u_*_instant",
        max_length=8_000_000,
    )
    chat_prefs: Optional[Dict[str, Any]] = None
    personas_store: Optional[Dict[str, Any]] = None
    theme: Optional[str] = Field(default=None, max_length=32)


class AdminResetPasswordBody(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class AdminSettingsBody(BaseModel):
    registration_enabled: Optional[bool] = None
    guest_mode_enabled: Optional[bool] = None
    maintenance_mode_enabled: Optional[bool] = None
    rate_limit_qpm_per_user: Optional[int] = Field(None, ge=1, le=6000)
    max_upload_mb: Optional[int] = Field(None, ge=1, le=2048)
    per_user_storage_mb: Optional[int] = Field(None, ge=0, le=500_000)
    per_user_max_upload_mb: Optional[int] = Field(None, ge=0, le=2048)
    max_docs_per_user: Optional[int] = Field(None, ge=1, le=100000)
    allowed_extensions: Optional[List[str]] = None
    sensitive_words: Optional[str] = Field(None, max_length=200_000)
    compliance_auto_disable: Optional[bool] = None
    login_bruteforce_enabled: Optional[bool] = None
    login_bruteforce_window_minutes: Optional[int] = Field(None, ge=1, le=1440)
    login_bruteforce_max_per_ip: Optional[int] = Field(None, ge=1, le=10000)
    login_bruteforce_max_per_username: Optional[int] = Field(None, ge=1, le=1000)
    rag_show_web_search_ui: Optional[bool] = Field(
        default=None,
        description="为 False 时用户前台隐藏智能问答页「联网」开关，且 /api/chat 忽略 enable_web_search。",
    )
    instant_show_web_search_ui: Optional[bool] = Field(
        default=None,
        description="为 False 时隐藏即时文档页「联网」开关，且 /api/chat/instant 忽略 enable_web_search。",
    )


class AdminAdvancedSettingsBody(BaseModel):
    """RAG 默认检索、切片层级、系统提示补充（写入 MySQL app_settings）。"""

    rag_defaults: Optional[Dict[str, Any]] = None
    chunk_levels: Optional[Dict[str, Any]] = None
    system_prompt_extra: Optional[str] = Field(default=None, max_length=12000)
    embedding_model_note: Optional[str] = Field(default=None, max_length=500)
    web_search_provider: Optional[str] = Field(
        default=None,
        description="联网搜索供应商：bocha（默认）、brave、baidu（千帆 web_search）",
    )
    bocha_api_key: Optional[str] = Field(default=None, max_length=512)
    brave_api_key_server: Optional[str] = Field(default=None, max_length=512)
    qianfan_api_key: Optional[str] = Field(default=None, max_length=512)


class AdminVectorUserBody(BaseModel):
    user_id: int = Field(..., ge=1)


class AdminFaissRegistryPatchBody(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=512)
    status: Optional[str] = Field(default=None, max_length=32)


class DeleteAccountBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    confirm_text: str = Field(..., min_length=1, max_length=64)


class AdminDestroyUserBody(BaseModel):
    confirm: bool = False
    typed_username: str = Field(..., min_length=1, max_length=32)


class AdminKbToggleBody(BaseModel):
    user_id: int = Field(..., ge=1)
    category: str = Field(..., min_length=1, max_length=128)
    disabled: bool = True


class AdminKbSoftWipeBody(BaseModel):
    user_id: int = Field(..., ge=1)
    category: str = Field(..., min_length=1, max_length=128)
    confirm: bool = False
    typed_category: str = Field(..., min_length=1, max_length=128)


class PublicFeedbackBody(BaseModel):
    title: str = Field(default="", max_length=200)
    content: str = Field(..., min_length=4, max_length=20000)
    contact: Optional[str] = Field(default=None, max_length=128)


class PublicMessageQualityBody(BaseModel):
    """智能问答 / 即时文档页助手消息「有用 / 需改进」。"""

    rating: Literal["good", "bad"]
    page_mode: Literal["rag", "instant"] = "rag"
    client_conv_id: Optional[str] = Field(default=None, max_length=128)
    message_index: Optional[int] = Field(default=None, ge=0, le=50000)
    user_message_excerpt: Optional[str] = Field(default=None, max_length=2000)
    assistant_excerpt: Optional[str] = Field(default=None, max_length=35000)
    client_meta: Optional[str] = Field(default=None, max_length=1000)


class AdminFeedbackPatchBody(BaseModel):
    status: Optional[Literal["open", "processing", "closed"]] = None
    admin_reply: Optional[str] = Field(default=None, max_length=16000)


class AdminPromptTemplatePutBody(BaseModel):
    """更新全局提示词（slug 为 rephrase / qa_rag / qa_hybrid 等）。"""

    template_body: str = Field(..., min_length=1, max_length=500_000)
    name: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = Field(default=None, max_length=512)
    is_active: Optional[bool] = None
