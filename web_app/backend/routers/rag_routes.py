from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRouter

from langchain_core.messages import HumanMessage, SystemMessage

from services.chat_turn import run_chat_turn, run_chat_turn_astream
from services.llm_factory import build_chat_llm, build_chat_openai_explicit
from services.vector_queries import list_indexed_source_files
from utils.api_config import (
    get_active_preset_name,
    get_api_config_for,
    load_api_config,
    save_api_config,
)
from utils.web_system_settings import get_llm_preset_templates
from utils.auth_store import User
from utils.document_deleter import delete_document_from_vector_db
from utils.document_preview import (
    get_document_full_view_payload,
    get_document_structure,
    get_plain_text_for_kb_substring_search,
    substring_hits_with_context,
)
from utils.metadata_manager import (
    add_category,
    delete_category,
    get_all_documents,
    get_categories,
    get_documents_by_category,
    update_document_metadata,
)
from utils.path_context import get_kb_dir
from utils.prompt_runtime import get_conversation_title_system
from utils.reranker import get_cached_reranker
from utils.rag_prompt_hardening import prepend_to_first_system
from utils.web_system_settings import (
    get_allowed_extensions,
    get_effective_max_upload_bytes_for_user,
    get_max_docs_per_user,
    get_per_user_storage_cap_bytes,
    get_system_prompt_extra,
    is_instant_web_search_ui_enabled,
    is_kb_disabled_for_user,
    is_rag_web_search_ui_enabled,
)
from web_app.backend.stats_helpers import user_kb_dir_total_bytes
from web_app.backend.deps import get_admin_user
from web_app.backend.resource_limits import rag_chat_slot
from services.instant_chat_turn import run_instant_chat_turn, run_instant_chat_turn_astream
from utils.instant_doc_parse import parse_upload_bytes
from web_app.backend.schemas import (
    CategoryCreateBody,
    ChatRequest,
    ChatResponse,
    ConfigSaveBody,
    ConfigTestBody,
    ConversationTitleBody,
    ConversationTitleResponse,
    DocMetaPatch,
    InstantChatRequest,
    InstantDocParseResponse,
)

from .. import ingest_queue, vdb_cache

router = APIRouter(tags=["rag"])


def _ext_allowed(filename: str) -> bool:
    allowed = set(get_allowed_extensions())
    name = (filename or "").strip()
    if "." not in name:
        return False
    ext = name.rsplit(".", 1)[-1].lower()
    return ext in allowed


@router.get("/api/health")
def health():
    out = {"ok": True, "deployment": "web_multi_user", "per_user_kb": True}
    try:
        out.update(vdb_cache.cache_stats())
    except Exception:
        pass
    return out


@router.get("/api/knowledge-bases")
def knowledge_bases():
    cats = get_categories()
    names = ["全部知识库"] + [c for c in cats if c != "全部知识库"]
    return {"categories": names}


@router.get("/api/kb/stats")
def kb_stats(request: Request, category: str = Query("全部知识库")):
    all_docs = get_all_documents()
    if category == "全部知识库":
        kb_docs = all_docs
    else:
        kb_docs = get_documents_by_category(category)
    total_chunks = sum(doc.get("chunks_count", 0) for doc in kb_docs)
    total_size = sum(doc.get("file_size_mb", 0) for doc in kb_docs)
    latest = ""
    for doc in kb_docs:
        t = str(doc.get("upload_time") or "")
        if t > latest:
            latest = t
    return {
        "category": category,
        "total_docs": len(kb_docs),
        "total_chunks": int(total_chunks),
        "total_size_mb": round(float(total_size), 2),
        "latest_upload_time": latest or None,
        "user_id": request.state.user.id,
    }


@router.get("/api/documents")
def list_documents(category: str = Query("全部知识库")):
    if category == "全部知识库":
        docs = get_all_documents()
    else:
        docs = get_documents_by_category(category)
    return {"documents": docs}


@router.get("/api/documents/preview")
def doc_preview(
    request: Request,
    file_name: str = Query(...),
    mode: str = Query("content"),
):
    if mode not in ("content", "structure"):
        raise HTTPException(status_code=400, detail="mode 须为 content 或 structure")
    uid = request.state.user.id
    vdb, _ = vdb_cache.get_cached_vdb_pair(uid)
    if mode == "structure":
        return get_document_structure(file_name, vdb)
    return get_document_full_view_payload(file_name, vdb)


@router.get("/api/documents/search")
def doc_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    category: str = Query("全部知识库"),
    max_total: int = Query(800, ge=1, le=3000, description="返回条数上限（每条为一处命中）"),
    max_per_file: int = Query(200, ge=1, le=500, description="单篇正文内最多返回几处命中"),
    context_before: int = Query(90, ge=20, le=400),
    context_after: int = Query(120, ge=20, le=500),
):
    """全文子串检索：列出文件名、描述、正文中每一处命中（大小写不敏感），带前后文便于前端高亮。"""
    uid = request.state.user.id
    vdb, _ = vdb_cache.get_cached_vdb_pair(uid)
    qn = q.strip()

    if category == "全部知识库":
        scoped = get_all_documents()
    else:
        scoped = get_documents_by_category(category)

    results: List[dict] = []
    truncated = False

    def push(hit: dict) -> bool:
        results.append(hit)
        if len(results) >= max_total:
            return True
        return False

    for d in scoped:
        fn = d.get("file_name")
        if not fn:
            continue
        fn_s = str(fn)
        for h in substring_hits_with_context(
            fn_s,
            qn,
            context_before=min(80, context_before),
            context_after=min(80, context_after),
            max_hits=max_per_file,
        ):
            if push({**h, "file_name": fn_s, "match_type": "meta_filename"}):
                truncated = True
                break
        if truncated:
            break
        desc = d.get("description") or ""
        if isinstance(desc, str) and desc.strip():
            for h in substring_hits_with_context(
                desc,
                qn,
                context_before=min(100, context_before),
                context_after=min(120, context_after),
                max_hits=max_per_file,
            ):
                if push({**h, "file_name": fn_s, "match_type": "meta_description"}):
                    truncated = True
                    break
        if truncated:
            break

    if not truncated:
        for d in scoped:
            fn = d.get("file_name")
            if not fn:
                continue
            fn_s = str(fn)
            try:
                text = get_plain_text_for_kb_substring_search(fn_s, vdb)
            except Exception:
                text = ""
            if not text:
                continue
            for h in substring_hits_with_context(
                text,
                qn,
                context_before=context_before,
                context_after=context_after,
                max_hits=max_per_file,
            ):
                if push({**h, "file_name": fn_s, "match_type": "content"}):
                    truncated = True
                    break
            if truncated:
                break

    return {
        "query": qn,
        "match_mode": "substring_fulltext",
        "results": results,
        "result_count": len(results),
        "max_total": max_total,
        "truncated": truncated,
    }


@router.patch("/api/documents/metadata")
def patch_doc_metadata(p: DocMetaPatch):
    kwargs = {}
    if p.category is not None:
        kwargs["category"] = p.category
    if p.description is not None:
        kwargs["description"] = p.description
    if not kwargs:
        raise HTTPException(status_code=400, detail="无更新字段")
    if not update_document_metadata(p.file_name, **kwargs):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}


@router.delete("/api/documents")
def delete_document(request: Request, file_name: str = Query(...)):
    uid = request.state.user.id
    # 私有 vdb 副本：删除会原地修改内存索引，不能与检索线程共享缓存对象
    from utils.db import get_vector_db

    _vdb, emb = vdb_cache.get_cached_vdb_pair(uid)
    vdb = get_vector_db(emb)
    ok, deleted_count = delete_document_from_vector_db(file_name, vdb, emb)
    if not ok or deleted_count == 0:
        raise HTTPException(status_code=404, detail="未找到该文档或无可删块")
    vdb_cache.bump_user_cache(uid)
    # 已删文档不能继续留在 BM25 索引里被关键词检索到
    try:
        from web_app.backend.ingest_queue import _invalidate_and_prewarm_bm25

        _invalidate_and_prewarm_bm25(uid)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("删除后 BM25 索引失效调度失败: %s", file_name)
    return {"ok": True, "chunks_deleted": deleted_count}


@router.post("/api/categories")
def create_category(body: CategoryCreateBody):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称为空")
    if add_category(name):
        return {"ok": True}
    raise HTTPException(status_code=409, detail="知识库已存在")


@router.delete("/api/categories")
def remove_category(name: str = Query(...)):
    if name == "默认知识库":
        raise HTTPException(status_code=400, detail="不能删除默认知识库")
    if delete_category(name):
        return {"ok": True}
    raise HTTPException(status_code=404, detail="知识库不存在")


@router.post("/api/upload")
async def upload_documents(
    request: Request,
    category: str = Form("默认知识库"),
    description: str = Form(""),
    files: List[UploadFile] = File(...),
):
    uid = request.state.user.id
    results: List[dict] = []
    max_bytes = get_effective_max_upload_bytes_for_user(uid)
    storage_cap = get_per_user_storage_cap_bytes()
    cat = category.strip() or "默认知识库"
    desc = description or ""
    staging_root = os.path.join(get_kb_dir(), "upload_staging")
    os.makedirs(staging_root, exist_ok=True)

    if is_kb_disabled_for_user(uid, cat):
        raise HTTPException(status_code=403, detail="该知识库已被管理员禁用，无法上传")

    for uf in files:
        raw_name = uf.filename or "unnamed"
        if not _ext_allowed(raw_name):
            results.append(
                {
                    "file_name": raw_name,
                    "ok": False,
                    "error": f"不允许的格式，允许: {', '.join(get_allowed_extensions())}",
                }
            )
            continue
        data = await uf.read()
        if len(data) > max_bytes:
            results.append(
                {
                    "file_name": raw_name,
                    "ok": False,
                    "error": f"超过单文件大小限制 {max_bytes / (1024 * 1024):.1f}MB",
                }
            )
            continue
        if storage_cap > 0:
            used = user_kb_dir_total_bytes(uid)
            if used + len(data) > storage_cap:
                results.append(
                    {
                        "file_name": raw_name,
                        "ok": False,
                        "error": f"超过单用户存储空间上限（约 {storage_cap / (1024 * 1024):.0f}MB，已用约 {used / (1024 * 1024):.1f}MB）",
                    }
                )
                continue
        ok_slot, slot_err = ingest_queue.try_reserve_ingest_slot(uid)
        if not ok_slot:
            results.append({"file_name": raw_name, "ok": False, "error": slot_err})
            continue
        job_id = str(uuid.uuid4())
        safe_base = os.path.basename(raw_name.replace("\\", "/"))
        staging_path = os.path.join(staging_root, f"{job_id}_{safe_base}")
        try:
            with open(staging_path, "wb") as f:
                f.write(data)
            ingest_queue.enqueue_staged_file(job_id, uid, raw_name, cat, desc, staging_path)
            results.append(
                {
                    "file_name": raw_name,
                    "ok": True,
                    "queued": True,
                    "job_id": job_id,
                }
            )
        except Exception as e:
            ingest_queue.release_ingest_slot(uid)
            ingest_queue.forget_job(job_id)
            try:
                if os.path.isfile(staging_path):
                    os.unlink(staging_path)
            except OSError:
                pass
            results.append({"file_name": raw_name, "ok": False, "error": str(e)})
    return {"results": results}


@router.get("/api/upload/jobs")
def list_upload_jobs(request: Request, limit: int = Query(40, ge=1, le=100)):
    uid = request.state.user.id
    jobs = ingest_queue.list_jobs_for_user(uid, limit=limit)
    return {"jobs": [ingest_queue.job_to_dict(j) for j in jobs]}


@router.get("/api/upload/jobs/{job_id}")
def get_upload_job(request: Request, job_id: str):
    uid = request.state.user.id
    rec = ingest_queue.get_job_for_user(job_id, uid)
    if rec is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return ingest_queue.job_to_dict(rec)


@router.post("/api/index/save")
def index_save(request: Request):
    uid = request.state.user.id
    vdb, _ = vdb_cache.get_cached_vdb_pair(uid)
    index_dir = os.path.join(get_kb_dir(), "faiss_index")
    os.makedirs(index_dir, exist_ok=True)
    vdb.save_local(index_dir)
    vdb_cache.bump_user_cache(uid)
    return {"ok": True}


@router.post("/api/index/reload")
def index_reload(request: Request):
    vdb_cache.bump_user_cache(request.state.user.id)
    return {"ok": True, "reloaded": True}


@router.get("/api/indexed-sources")
def indexed_sources(request: Request):
    vdb, _ = vdb_cache.get_cached_vdb_pair(request.state.user.id)
    return {"sources": list_indexed_source_files(vdb)}


@router.get("/api/config/presets")
def config_presets():
    return {"presets": list(load_api_config().keys())}


@router.get("/api/config/detail")
def config_detail(preset: str = Query(..., min_length=1)):
    c = get_api_config_for(preset)
    return {
        "preset": preset,
        "base_url": c.get("base_url", ""),
        "model": c.get("model", ""),
        "provider": c.get("provider", "custom"),
        "has_api_key": bool((c.get("api_key") or "").strip()),
    }


@router.get("/api/config/summary")
def config_summary(preset: Optional[str] = None):
    key = preset.strip() if preset and preset.strip() else None
    c = get_api_config_for(key)
    used_name = key if key else get_active_preset_name()
    return {
        "preset": used_name,
        "model": c.get("model", ""),
        "base_url": c.get("base_url", ""),
        "has_api_key": bool((c.get("api_key") or "").strip()),
    }


@router.post("/api/config/save")
def config_save(body: ConfigSaveBody, _: User = Depends(get_admin_user)):
    preset = body.preset.strip()
    if not preset:
        raise HTTPException(status_code=400, detail="预设名不能为空")
    configs = load_api_config()
    tmpl = get_llm_preset_templates()
    if preset not in configs:
        configs[preset] = dict(
            tmpl.get("自定义") or tmpl.get("DeepSeek") or next(iter(tmpl.values()))
        )
    cur = configs[preset]
    new_key = (body.api_key or "").strip()
    if not new_key:
        new_key = (cur.get("api_key") or "").strip()
    configs[preset] = {
        "base_url": body.base_url.strip(),
        "api_key": new_key,
        "model": body.model.strip(),
        "provider": body.provider.strip() or "custom",
    }
    save_api_config(configs)
    return {"ok": True}


@router.delete("/api/config/delete")
def config_delete(preset: str = Query(..., min_length=1), _: User = Depends(get_admin_user)):
    from utils.api_config import delete_api_config

    try:
        delete_api_config(preset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "presets": list(load_api_config().keys())}


@router.post("/api/config/test")
def config_test(body: ConfigTestBody, _: User = Depends(get_admin_user)):
    if not body.api_key.strip():
        raise HTTPException(status_code=400, detail="请填写 API Key")
    if not body.base_url.strip():
        raise HTTPException(status_code=400, detail="请填写 Base URL")
    if not body.model.strip():
        raise HTTPException(status_code=400, detail="请填写模型名称")
    try:
        llm = build_chat_openai_explicit(
            model=body.model.strip(),
            api_key=body.api_key.strip(),
            base_url=body.base_url.strip(),
            temperature=0,
            timeout=15,
        )
        r = llm.invoke("你好")
        text = (r.content if hasattr(r, "content") else str(r))[:200]
        return {"ok": True, "reply_preview": text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/bm25-status")
def bm25_status():
    p = os.path.join(get_kb_dir(), "bm25_index.pkl")
    return {"exists": os.path.isfile(p), "relative_path": "users/<id>/knowledge_db/bm25_index.pkl"}


@router.post("/api/instant-doc/parse", response_model=InstantDocParseResponse)
async def instant_doc_parse(request: Request, file: UploadFile = File(...)):
    """解析即时文档：不入库；限制 5MB、正文 10 万字符。与知识库上传完全独立。"""
    _ = request.state.user
    raw_name = file.filename or "unnamed"
    try:
        data = await file.read()
        text = parse_upload_bytes(raw_name, data)
        return InstantDocParseResponse(
            ok=True,
            text=text,
            file_name=os.path.basename(raw_name.replace("\\", "/")),
            char_count=len(text),
        )
    except ValueError as e:
        return InstantDocParseResponse(ok=False, file_name=raw_name, error=str(e))
    except Exception as e:
        return InstantDocParseResponse(ok=False, file_name=raw_name, error=f"解析失败：{e}")


@router.post("/api/chat/instant")
async def chat_instant(request: Request, req: InstantChatRequest):
    """即时文档对话：仅用请求内 document_text + 轻量摘录，不访问向量库。"""
    uid = request.state.user.id
    cfg = get_api_config_for(req.api_config_name)
    if not str(cfg.get("api_key") or "").strip():
        err = ChatResponse(
            answer="",
            mode="error",
            error=(
                "尚未配置大模型 API Key，无法调用对话接口。"
                "请管理员在管理端「检索设置 → 模型 API」中填写密钥。"
            ),
        )
        if req.stream:
            return JSONResponse(content=err.model_dump(), media_type="application/json")
        return err
    try:
        llm = build_chat_llm(req.temperature, config_name=req.api_config_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 初始化失败: {e}") from e

    hist = [m.model_dump() for m in req.history]
    pp = (req.persona_prompt or "").strip() or None
    extra_sys = get_system_prompt_extra()
    enable_instant_web = bool(req.enable_web_search) and is_instant_web_search_ui_enabled()
    doc_text = (req.document_text or "").strip()
    if len(doc_text) > 100_000:
        raise HTTPException(status_code=400, detail="document_text 超过 10 万字符")

    if req.stream:

        async def ndjson_agen():
            async with rag_chat_slot():
                async for ev in run_instant_chat_turn_astream(
                    user_input=req.message.strip(),
                    chat_history_messages=hist,
                    document_text=doc_text,
                    document_file_name=(req.document_file_name or "").strip(),
                    llm=llm,
                    response_style=(req.response_style or "balanced").strip() or "balanced",
                    persona_prompt=pp,
                    system_prompt_extra=extra_sys or None,
                    user_id=int(uid),
                    enable_web_search=enable_instant_web,
                ):
                    yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")

        return StreamingResponse(
            ndjson_agen(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    async with rag_chat_slot():
        answer, mode, rq, sources, err = await asyncio.to_thread(
            run_instant_chat_turn,
            user_input=req.message.strip(),
            chat_history_messages=hist,
            document_text=doc_text,
            document_file_name=(req.document_file_name or "").strip(),
            llm=llm,
            response_style=(req.response_style or "balanced").strip() or "balanced",
            persona_prompt=pp,
            system_prompt_extra=extra_sys or None,
            user_id=int(uid),
            enable_web_search=enable_instant_web,
        )
    return ChatResponse(answer=answer, mode=mode, retrieval_query=rq, sources=sources, error=err)


@router.post("/api/chat/conversation-title", response_model=ConversationTitleResponse)
def chat_conversation_title(request: Request, body: ConversationTitleBody):
    """首条用户消息后由前端调用：模型生成短标题写入侧栏。"""
    _ = request.state.user  # 需登录（中间件已注入）
    cfg = get_api_config_for(body.api_config_name)
    if not str(cfg.get("api_key") or "").strip():
        return ConversationTitleResponse(title="")
    try:
        llm = build_chat_llm(0.0, config_name=body.api_config_name)
        bound = llm.bind(max_tokens=96)
        msg = body.message.strip()[:4000]
        resp = bound.invoke(
            prepend_to_first_system(
                [
                    SystemMessage(content=get_conversation_title_system()),
                    HumanMessage(content=msg),
                ]
            )
        )
        text = (getattr(resp, "content", None) or str(resp) or "").strip()
        line = text.split("\n")[0].strip()
        for strip_set in ('"', "\u201c", "\u201d", "「", "」", "【", "】"):
            line = line.strip(strip_set)
        line = line.replace("\r", " ").replace("\n", " ").strip()
        if len(line) > 80:
            line = line[:80]
        return ConversationTitleResponse(title=line)
    except Exception:
        return ConversationTitleResponse(title="")


@router.post("/api/chat")
async def chat(request: Request, req: ChatRequest):
    """普通 JSON 或 NDJSON 流（req.stream=True）；流式走同一路径以免根目录 StaticFiles 对 /api/chat/stream 返回 405。"""
    uid = request.state.user.id
    cfg = get_api_config_for(req.api_config_name)
    if not str(cfg.get("api_key") or "").strip():
        err = ChatResponse(
            answer="",
            mode="error",
            error=(
                "尚未配置大模型 API Key，无法调用对话接口。"
                "请管理员在管理端「模型配置」页填写密钥并保存（写入 MySQL app_settings.llm_api_presets）。"
            ),
        )
        if req.stream:
            return JSONResponse(content=err.model_dump(), media_type="application/json")
        return err
    vdb, _ = vdb_cache.get_cached_vdb_pair(uid)
    try:
        llm = build_chat_llm(req.temperature, config_name=req.api_config_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 初始化失败: {e}") from e

    reranker = None
    if req.enable_reranker:
        try:
            # 缓存构造 + 线程化：模型加载可能秒级，不能阻塞事件循环
            reranker = await asyncio.to_thread(get_cached_reranker)
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("重排序器初始化失败，本次降级为不重排: %s", e)
            reranker = None

    hist = [m.model_dump() for m in req.history]
    pp = (req.persona_prompt or "").strip() or None
    extra_sys = get_system_prompt_extra()
    enable_rag_web = bool(req.enable_web_search) and is_rag_web_search_ui_enabled()

    if req.stream:

        async def ndjson_agen():
            async with rag_chat_slot():
                async for ev in run_chat_turn_astream(
                    user_input=req.message.strip(),
                    chat_history_messages=hist,
                    vector_db=vdb,
                    llm=llm,
                    selected_kb=req.selected_kb,
                    search_mode=req.search_mode,
                    enable_reranker=req.enable_reranker,
                    reranker=reranker,
                    retrieval_k=req.retrieval_k,
                    response_style=(req.response_style or "balanced").strip() or "balanced",
                    persona_prompt=pp,
                    system_prompt_extra=extra_sys or None,
                    user_id=int(uid),
                    enable_web_search=enable_rag_web,
                ):
                    yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")

        return StreamingResponse(
            ndjson_agen(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    async with rag_chat_slot():
        result = await asyncio.to_thread(
            run_chat_turn,
            user_input=req.message.strip(),
            chat_history_messages=hist,
            vector_db=vdb,
            llm=llm,
            selected_kb=req.selected_kb,
            search_mode=req.search_mode,
            enable_reranker=req.enable_reranker,
            reranker=reranker,
            retrieval_k=req.retrieval_k,
            response_style=(req.response_style or "balanced").strip() or "balanced",
            persona_prompt=pp,
            system_prompt_extra=extra_sys or None,
            user_id=int(uid),
            enable_web_search=enable_rag_web,
        )

    return ChatResponse(
        answer=result.answer,
        mode=result.mode,
        retrieval_query=result.retrieval_query,
        sources=result.sources,
        error=result.error,
    )
