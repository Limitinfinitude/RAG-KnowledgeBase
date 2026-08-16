"""Web 服务端全局设置：仅存 MySQL 表 app_settings；遗留 JSON 文件仅首次迁移时读入并改名，之后不再读取。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import WEB_SERVER_DIR

_DEFAULT_EXT = ["pdf", "txt", "docx", "doc", "md", "xlsx", "xls"]

_RAG_DEFAULTS: Dict[str, Any] = {
    "default_retrieval_k": 10,
    "default_search_mode": "vector",
    "default_enable_reranker": False,
    "default_response_style": "balanced",
    "default_temperature": 0.0,
}

_CHUNK_LEVEL_DEFAULTS: Dict[str, Dict[str, int]] = {
    "small": {"chunk_size": 300, "chunk_overlap": 50},
    "medium": {"chunk_size": 800, "chunk_overlap": 100},
    "large": {"chunk_size": 2000, "chunk_overlap": 200},
}

_LLM_PRESET_TEMPLATES: Dict[str, Dict[str, str]] = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-chat",
        "provider": "deepseek",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-3.5-turbo",
        "provider": "openai",
    },
    "自定义": {
        "base_url": "",
        "api_key": "",
        "model": "",
        "provider": "custom",
    },
}


def get_llm_preset_templates() -> Dict[str, Dict[str, str]]:
    return {k: dict(v) for k, v in _LLM_PRESET_TEMPLATES.items()}


def _blank_llm_preset_shell() -> Dict[str, str]:
    return {"base_url": "", "api_key": "", "model": "", "provider": "custom"}


def _normalize_llm_api_presets(out: Dict[str, Any]) -> None:
    templates = {k: dict(v) for k, v in _LLM_PRESET_TEMPLATES.items()}
    cur = out.get("llm_api_presets")
    if not isinstance(cur, dict):
        cur = {}
    merged: Dict[str, Dict[str, str]] = {k: dict(v) for k, v in templates.items()}
    for name, sub in cur.items():
        nm = str(name).strip()
        if not nm or len(nm) > 64:
            continue
        if not isinstance(sub, dict):
            continue
        base = dict(merged.get(nm, _blank_llm_preset_shell()))
        for k in ("base_url", "api_key", "model", "provider"):
            if k in sub:
                val = sub.get(k)
                base[k] = "" if val is None else str(val).strip()
        merged[nm] = base
    out["llm_api_presets"] = merged


_DEFAULTS: Dict[str, Any] = {
    "web_search_provider": "bocha",
    "bocha_api_key": "",
    "brave_api_key_server": "",
    "qianfan_api_key": "",
    "registration_enabled": True,
    "guest_mode_enabled": False,
    "maintenance_mode_enabled": False,
    "rate_limit_qpm_per_user": 60,
    "max_upload_mb": 50,
    "per_user_storage_mb": 0,
    "per_user_max_upload_mb": 0,
    "max_docs_per_user": 500,
    "allowed_extensions": list(_DEFAULT_EXT),
    "kb_disabled": {},
    "sensitive_words": "",
    "compliance_auto_disable": True,
    "rag_defaults": dict(_RAG_DEFAULTS),
    "chunk_levels": {k: dict(v) for k, v in _CHUNK_LEVEL_DEFAULTS.items()},
    "system_prompt_extra": "",
    "embedding_model_note": "BAAI/bge-small-zh-v1.5（见 utils/embedding.py，改模型需重启服务）",
    # —— 嵌入模型与重排序模型 provider 配置（local 本地 / siliconflow 硅基流动）——
    "embedding_provider": "local",
    "embedding_model": "BAAI/bge-small-zh-v1.5",
    "siliconflow_api_key": "",
    "siliconflow_base_url": "https://api.siliconflow.cn",
    "rerank_provider": "local",
    "rerank_model": "BAAI/bge-reranker-base",
    "login_bruteforce_enabled": True,
    "login_bruteforce_window_minutes": 15,
    "login_bruteforce_max_per_ip": 40,
    "login_bruteforce_max_per_username": 12,
    "llm_api_presets": {},
    "rag_show_web_search_ui": True,
    "instant_show_web_search_ui": True,
}


def _normalize_embedding_rerank_settings(out: Dict[str, Any]) -> None:
    """归一化嵌入/重排序 provider 配置。"""
    ep = str(out.get("embedding_provider") or "local").strip().lower()
    out["embedding_provider"] = ep if ep in ("local", "siliconflow") else "local"
    rp = str(out.get("rerank_provider") or "local").strip().lower()
    out["rerank_provider"] = rp if rp in ("local", "siliconflow") else "local"
    if not isinstance(out.get("embedding_model"), str) or not out["embedding_model"].strip():
        out["embedding_model"] = _DEFAULTS["embedding_model"]
    if not isinstance(out.get("rerank_model"), str) or not out["rerank_model"].strip():
        out["rerank_model"] = _DEFAULTS["rerank_model"]
    if not isinstance(out.get("siliconflow_api_key"), str):
        out["siliconflow_api_key"] = ""
    if not isinstance(out.get("siliconflow_base_url"), str) or not out["siliconflow_base_url"].strip():
        out["siliconflow_base_url"] = _DEFAULTS["siliconflow_base_url"]


def _normalize_web_search_settings(out: Dict[str, Any]) -> None:
    p = str(out.get("web_search_provider") or "bocha").strip().lower()
    out["web_search_provider"] = p if p in ("brave", "bocha", "baidu") else "bocha"
    if not isinstance(out.get("bocha_api_key"), str):
        out["bocha_api_key"] = ""
    if not isinstance(out.get("brave_api_key_server"), str):
        out["brave_api_key_server"] = ""
    if not isinstance(out.get("qianfan_api_key"), str):
        out["qianfan_api_key"] = ""


def _path() -> str:
    os.makedirs(WEB_SERVER_DIR, exist_ok=True)
    return os.path.join(WEB_SERVER_DIR, "system_settings.json")


def _normalize_bruteforce_settings(out: Dict[str, Any]) -> None:
    out["login_bruteforce_enabled"] = bool(out.get("login_bruteforce_enabled", True))
    try:
        w = int(out.get("login_bruteforce_window_minutes", 15))
    except (TypeError, ValueError):
        w = 15
    out["login_bruteforce_window_minutes"] = max(1, min(w, 1440))
    try:
        mip = int(out.get("login_bruteforce_max_per_ip", 40))
    except (TypeError, ValueError):
        mip = 40
    out["login_bruteforce_max_per_ip"] = max(1, min(mip, 10000))
    try:
        mu = int(out.get("login_bruteforce_max_per_username", 12))
    except (TypeError, ValueError):
        mu = 12
    out["login_bruteforce_max_per_username"] = max(1, min(mu, 1000))


def _normalize_full_settings(out: Dict[str, Any]) -> None:
    if not isinstance(out.get("allowed_extensions"), list) or not out["allowed_extensions"]:
        out["allowed_extensions"] = list(_DEFAULT_EXT)
    rd = out.get("rag_defaults")
    if not isinstance(rd, dict):
        rd = dict(_RAG_DEFAULTS)
    else:
        rd = {**_RAG_DEFAULTS, **{k: v for k, v in rd.items() if k in _RAG_DEFAULTS}}
    out["rag_defaults"] = rd
    cl = out.get("chunk_levels")
    if not isinstance(cl, dict):
        out["chunk_levels"] = {k: dict(v) for k, v in _CHUNK_LEVEL_DEFAULTS.items()}
    else:
        merged_cl: Dict[str, Dict[str, int]] = {}
        for level, d0 in _CHUNK_LEVEL_DEFAULTS.items():
            sub = cl.get(level)
            if isinstance(sub, dict):
                merged_cl[level] = {
                    "chunk_size": int(sub.get("chunk_size", d0["chunk_size"])),
                    "chunk_overlap": int(sub.get("chunk_overlap", d0["chunk_overlap"])),
                }
            else:
                merged_cl[level] = dict(d0)
        out["chunk_levels"] = merged_cl
    if not isinstance(out.get("system_prompt_extra"), str):
        out["system_prompt_extra"] = ""
    if not isinstance(out.get("embedding_model_note"), str):
        out["embedding_model_note"] = _DEFAULTS["embedding_model_note"]
    _normalize_embedding_rerank_settings(out)
    _normalize_web_search_settings(out)
    if not isinstance(out.get("kb_disabled"), dict):
        out["kb_disabled"] = {}
    if not isinstance(out.get("sensitive_words"), str):
        out["sensitive_words"] = ""
    out["compliance_auto_disable"] = bool(out.get("compliance_auto_disable", True))
    try:
        out["per_user_storage_mb"] = int(out.get("per_user_storage_mb") or 0)
    except (TypeError, ValueError):
        out["per_user_storage_mb"] = 0
    try:
        out["per_user_max_upload_mb"] = int(out.get("per_user_max_upload_mb") or 0)
    except (TypeError, ValueError):
        out["per_user_max_upload_mb"] = 0
    _normalize_bruteforce_settings(out)
    _normalize_llm_api_presets(out)


def _consume_legacy_system_settings_json_into(out: Dict[str, Any]) -> bool:
    p = _path()
    if not os.path.isfile(p):
        return False
    bak = p + ".migrated"
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out.update(data)
        try:
            os.replace(p, bak)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _migrate_legacy_api_config_json_into(out: Dict[str, Any]) -> bool:
    try:
        from utils.path_context import get_api_config_dir
    except Exception:
        return False
    path = os.path.join(get_api_config_dir(), "api_config.json")
    if not os.path.isfile(path):
        return False
    bak = path + ".migrated"
    try:
        with open(path, "r", encoding="utf-8") as f:
            file_data = json.load(f)
    except Exception:
        return False
    if not isinstance(file_data, dict):
        try:
            os.replace(path, bak)
        except Exception:
            pass
        return True
    cur_lp = out.get("llm_api_presets")
    merged: Dict[str, Any] = dict(cur_lp) if isinstance(cur_lp, dict) else {}
    for k, v in file_data.items():
        kn = str(k).strip()[:64]
        if not kn or not isinstance(v, dict):
            continue
        if kn not in merged:
            merged[kn] = dict(v)
        else:
            m = dict(merged[kn]) if isinstance(merged[kn], dict) else {}
            for fld in ("base_url", "model", "provider", "api_key"):
                if fld in v and not (str(m.get(fld) or "").strip()):
                    m[fld] = v.get(fld, "")
            merged[kn] = m
    out["llm_api_presets"] = merged
    try:
        os.replace(path, bak)
    except Exception:
        pass
    return True


def _db_load_payload_dict() -> Optional[Dict[str, Any]]:
    try:
        from utils.auth_db_backend import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT payload FROM app_settings WHERE id = ?",
                (1,),
            ).fetchone()
        if row is None:
            return None
        raw = row["payload"] if isinstance(row, dict) else getattr(row, "payload", None)
        if raw is None:
            return {}
        s = str(raw).strip()
        if not s:
            return {}
        data = json.loads(s)
        return data if isinstance(data, dict) else {}
    except Exception:
        return None


def _db_save_payload_dict(out: Dict[str, Any]) -> None:
    from utils.auth_db_backend import get_conn

    blob = json.dumps(out, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (id, payload, updated_at) VALUES (?, ?, ?)
            ON DUPLICATE KEY UPDATE payload = VALUES(payload), updated_at = VALUES(updated_at)
            """,
            (1, blob, now),
        )


def load_system_settings() -> Dict[str, Any]:
    db_raw = _db_load_payload_dict()
    dirty = db_raw is None or (isinstance(db_raw, dict) and len(db_raw) == 0)
    out = dict(_DEFAULTS)
    if isinstance(db_raw, dict):
        out.update(db_raw)

    if _consume_legacy_system_settings_json_into(out):
        dirty = True
    if _migrate_legacy_api_config_json_into(out):
        dirty = True

    _normalize_full_settings(out)

    if dirty:
        try:
            _db_save_payload_dict(out)
        except Exception:
            pass

    return out


def save_system_settings(data: Dict[str, Any]) -> None:
    cur = load_system_settings()
    cur.update(data)
    _normalize_full_settings(cur)
    _db_save_payload_dict(cur)


def get_login_bruteforce_settings() -> tuple[bool, int, int, int]:
    s = load_system_settings()
    _normalize_bruteforce_settings(s)
    return (
        bool(s.get("login_bruteforce_enabled", True)),
        int(s["login_bruteforce_window_minutes"]),
        int(s["login_bruteforce_max_per_ip"]),
        int(s["login_bruteforce_max_per_username"]),
    )


def get_max_upload_bytes() -> int:
    mb = float(load_system_settings().get("max_upload_mb", 50))
    return int(mb * 1024 * 1024)


def get_per_user_storage_cap_bytes() -> int:
    """0 表示不限制单用户目录总占用。"""
    try:
        mb = int(load_system_settings().get("per_user_storage_mb") or 0)
    except (TypeError, ValueError):
        mb = 0
    if mb <= 0:
        return 0
    return int(mb * 1024 * 1024)


def get_effective_max_upload_bytes_for_user(_user_id: int) -> int:
    """单用户单文件上限：若配置了 per_user_max_upload_mb 则与全局取较小值。"""
    global_b = get_max_upload_bytes()
    try:
        per_mb = int(load_system_settings().get("per_user_max_upload_mb") or 0)
    except (TypeError, ValueError):
        per_mb = 0
    if per_mb <= 0:
        return global_b
    return min(global_b, int(per_mb * 1024 * 1024))


def kb_disabled_storage_key(user_id: int, category: str) -> str:
    return f"{int(user_id)}||{str(category or '').strip()}"


def is_kb_disabled_for_user(user_id: int, category: str) -> bool:
    raw = load_system_settings().get("kb_disabled")
    if not isinstance(raw, dict):
        return False
    k = kb_disabled_storage_key(user_id, category)
    return bool(raw.get(k))


def set_kb_disabled_for_user(user_id: int, category: str, disabled: bool) -> None:
    cur = load_system_settings()
    d = dict(cur.get("kb_disabled") or {}) if isinstance(cur.get("kb_disabled"), dict) else {}
    key = kb_disabled_storage_key(user_id, category)
    if disabled:
        d[key] = True
    else:
        d.pop(key, None)
    save_system_settings({"kb_disabled": d})


def get_allowed_extensions() -> List[str]:
    exts = load_system_settings().get("allowed_extensions") or list(_DEFAULT_EXT)
    return [str(x).lstrip(".").lower() for x in exts]


def is_registration_enabled() -> bool:
    return bool(load_system_settings().get("registration_enabled", True))


def get_rag_defaults_dict() -> Dict[str, Any]:
    s = load_system_settings()
    rd = s.get("rag_defaults") or dict(_RAG_DEFAULTS)
    k = int(rd.get("default_retrieval_k", _RAG_DEFAULTS["default_retrieval_k"]))
    k = max(3, min(k, 30))
    sm = str(rd.get("default_search_mode", "vector") or "vector").strip().lower()
    if sm not in ("vector", "hybrid"):
        sm = "vector"
    st = str(rd.get("default_response_style", "balanced") or "balanced").strip().lower()
    if st not in ("precise", "balanced", "verbose"):
        st = "balanced"
    temp = float(rd.get("default_temperature", 0.0))
    temp = max(0.0, min(temp, 2.0))
    return {
        "default_retrieval_k": k,
        "default_search_mode": sm,
        "default_enable_reranker": bool(rd.get("default_enable_reranker", False)),
        "default_response_style": st,
        "default_temperature": temp,
    }


def get_merged_chunk_levels() -> Dict[str, Dict[str, int]]:
    """供入库分块使用：与内置 CHUNK_CONFIGS 对齐的层级，含管理员覆盖。"""
    s = load_system_settings()
    raw = s.get("chunk_levels") or {}
    out: Dict[str, Dict[str, int]] = {}
    for level, d0 in _CHUNK_LEVEL_DEFAULTS.items():
        sub = raw.get(level) if isinstance(raw, dict) else None
        if isinstance(sub, dict):
            cs = int(sub.get("chunk_size", d0["chunk_size"]))
            co = int(sub.get("chunk_overlap", d0["chunk_overlap"]))
        else:
            cs, co = d0["chunk_size"], d0["chunk_overlap"]
        cs = max(80, min(cs, 32000))
        co = max(0, min(co, max(cs - 1, 0)))
        out[level] = {"chunk_size": cs, "chunk_overlap": co}
    return out


def merge_rag_defaults_patch(partial: Dict[str, Any]) -> Dict[str, Any]:
    """合并管理员提交的 rag_defaults 片段并做边界裁剪。"""
    cur = load_system_settings()
    base: Dict[str, Any] = dict(cur.get("rag_defaults") or _RAG_DEFAULTS)
    for k, v in (partial or {}).items():
        if k not in _RAG_DEFAULTS:
            continue
        base[k] = v
    k = int(base.get("default_retrieval_k", _RAG_DEFAULTS["default_retrieval_k"]))
    base["default_retrieval_k"] = max(3, min(k, 30))
    sm = str(base.get("default_search_mode", "vector") or "vector").strip().lower()
    base["default_search_mode"] = sm if sm in ("vector", "hybrid") else "vector"
    st = str(base.get("default_response_style", "balanced") or "balanced").strip().lower()
    base["default_response_style"] = st if st in ("precise", "balanced", "verbose") else "balanced"
    temp = float(base.get("default_temperature", 0.0))
    base["default_temperature"] = max(0.0, min(temp, 2.0))
    base["default_enable_reranker"] = bool(base.get("default_enable_reranker", False))
    return base


def apply_chunk_levels_update(partial: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """将 partial 中各层级覆盖写入后的完整 chunk_levels（用于保存）。"""
    cur = load_system_settings()
    raw = cur.get("chunk_levels") if isinstance(cur.get("chunk_levels"), dict) else {}
    partial = partial or {}
    out: Dict[str, Dict[str, int]] = {}
    for level, d0 in _CHUNK_LEVEL_DEFAULTS.items():
        sub = {"chunk_size": d0["chunk_size"], "chunk_overlap": d0["chunk_overlap"]}
        r = raw.get(level) if isinstance(raw.get(level), dict) else {}
        for k in ("chunk_size", "chunk_overlap"):
            if k in r:
                sub[k] = int(r[k])
        p = partial.get(level) if isinstance(partial.get(level), dict) else {}
        for k in ("chunk_size", "chunk_overlap"):
            if k in p:
                sub[k] = int(p[k])
        cs = max(80, min(int(sub["chunk_size"]), 32000))
        co = max(0, min(int(sub["chunk_overlap"]), max(cs - 1, 0)))
        out[level] = {"chunk_size": cs, "chunk_overlap": co}
    return out


def get_system_prompt_extra() -> str:
    s = load_system_settings()
    v = s.get("system_prompt_extra")
    return str(v).strip() if isinstance(v, str) else ""


def get_embedding_config() -> Dict[str, Any]:
    """返回嵌入模型运行配置：provider / model / api_key / base_url。

    优先级：MySQL app_settings → 环境变量（SILICONFLOW_API_KEY / SILICONFLOW_BASE_URL）。
    """
    s = load_system_settings()
    provider = str(s.get("embedding_provider") or "local").strip().lower()
    model = str(s.get("embedding_model") or _DEFAULTS["embedding_model"]).strip()
    api_key = (str(s.get("siliconflow_api_key") or "").strip()
               or os.environ.get("SILICONFLOW_API_KEY", "").strip())
    base_url = (str(s.get("siliconflow_base_url") or "").strip()
                or os.environ.get("SILICONFLOW_BASE_URL", "").strip()
                or _DEFAULTS["siliconflow_base_url"])
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


def get_rerank_config() -> Dict[str, Any]:
    """返回重排序模型运行配置：provider / model / api_key / base_url。"""
    s = load_system_settings()
    provider = str(s.get("rerank_provider") or "local").strip().lower()
    model = str(s.get("rerank_model") or _DEFAULTS["rerank_model"]).strip()
    api_key = (str(s.get("siliconflow_api_key") or "").strip()
               or os.environ.get("SILICONFLOW_API_KEY", "").strip())
    base_url = (str(s.get("siliconflow_base_url") or "").strip()
                or os.environ.get("SILICONFLOW_BASE_URL", "").strip()
                or _DEFAULTS["siliconflow_base_url"])
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }


def get_web_search_provider() -> str:
    s = load_system_settings()
    p = str(s.get("web_search_provider") or "bocha").strip().lower()
    return p if p in ("brave", "bocha", "baidu") else "bocha"


def get_bocha_api_key_resolved() -> str:
    """管理端 system_settings → 环境变量 BOCHA_API_KEY → config.BOCHA_API_KEY"""
    k = (load_system_settings().get("bocha_api_key") or "").strip()
    if k:
        return k
    k = (os.environ.get("BOCHA_API_KEY") or "").strip()
    if k:
        return k
    try:
        import config as c

        return (getattr(c, "BOCHA_API_KEY", None) or "").strip()
    except Exception:
        return ""


def get_qianfan_api_key_resolved() -> str:
    """管理端 qianfan_api_key → 环境变量 QIANFAN_API_KEY → config.QIANFAN_API_KEY"""
    k = (load_system_settings().get("qianfan_api_key") or "").strip()
    if k:
        return k
    k = (os.environ.get("QIANFAN_API_KEY") or "").strip()
    if k:
        return k
    try:
        import config as c

        return (getattr(c, "QIANFAN_API_KEY", None) or "").strip()
    except Exception:
        return ""


def get_brave_api_key_resolved() -> str:
    """管理端 brave_api_key_server → 环境变量 → config（与 augment 原逻辑一致）"""
    k = (load_system_settings().get("brave_api_key_server") or "").strip()
    if k:
        return k
    k = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
    if k:
        return k
    try:
        import config as c

        return (getattr(c, "BRAVE_SEARCH_API_KEY", None) or "").strip()
    except Exception:
        return ""


def admin_settings_response() -> Dict[str, Any]:
    """管理端 GET/PUT 返回：脱敏联网搜索密钥，仅提示是否已配置。"""
    s = load_system_settings()
    out = dict(s)
    out["bocha_api_key_configured"] = bool((out.get("bocha_api_key") or "").strip())
    out["brave_api_key_server_configured"] = bool((out.get("brave_api_key_server") or "").strip())
    out["qianfan_api_key_configured"] = bool((out.get("qianfan_api_key") or "").strip())
    out.pop("bocha_api_key", None)
    out.pop("brave_api_key_server", None)
    out.pop("qianfan_api_key", None)
    out["siliconflow_api_key_configured"] = bool((out.get("siliconflow_api_key") or "").strip())
    out.pop("siliconflow_api_key", None)
    lp = out.get("llm_api_presets")
    if isinstance(lp, dict):
        safe_lp: Dict[str, Any] = {}
        for k, v in lp.items():
            if not isinstance(v, dict):
                continue
            d = {**v}
            d.pop("api_key", None)
            d["has_api_key"] = bool((v.get("api_key") or "").strip())
            safe_lp[str(k)] = d
        out["llm_api_presets"] = safe_lp
    return out


def public_settings_dict() -> Dict[str, Any]:
    s = load_system_settings()
    return {
        "registration_enabled": bool(s.get("registration_enabled", True)),
        "guest_mode_enabled": bool(s.get("guest_mode_enabled", False)),
        "maintenance_mode_enabled": bool(s.get("maintenance_mode_enabled", False)),
        "rate_limit_qpm_per_user": int(s.get("rate_limit_qpm_per_user", 60)),
        "max_upload_mb": int(s.get("max_upload_mb", 50)),
        "max_docs_per_user": int(s.get("max_docs_per_user", 500)),
        "allowed_extensions": get_allowed_extensions(),
        "rag_defaults": get_rag_defaults_dict(),
        "rag_show_web_search_ui": bool(s.get("rag_show_web_search_ui", True)),
        "instant_show_web_search_ui": bool(s.get("instant_show_web_search_ui", True)),
    }


def is_rag_web_search_ui_enabled() -> bool:
    """管理端可关：关则前台隐藏智能问答页「联网」且接口强制不按联网处理。"""
    return bool(load_system_settings().get("rag_show_web_search_ui", True))


def is_instant_web_search_ui_enabled() -> bool:
    """管理端可关：关则前台隐藏即时文档页「联网」且接口强制不按联网处理。"""
    return bool(load_system_settings().get("instant_show_web_search_ui", True))


def is_maintenance_mode() -> bool:
    return bool(load_system_settings().get("maintenance_mode_enabled", False))


def is_guest_mode_enabled() -> bool:
    return bool(load_system_settings().get("guest_mode_enabled", False))


def get_rate_limit_qpm_per_user() -> int:
    v = int(load_system_settings().get("rate_limit_qpm_per_user", 60))
    return max(1, min(v, 6000))


def get_max_docs_per_user() -> int:
    v = int(load_system_settings().get("max_docs_per_user", 500))
    return max(1, min(v, 100000))
