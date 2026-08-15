# utils/api_config.py
"""
LLM API 多预设：存 MySQL app_settings.payload.llm_api_presets（经 web_system_settings 归一化）。
遗留 api_config.json 由 load_system_settings 首次迁移并改名为 .migrated。
"""
from __future__ import annotations

import os
from typing import Any, Dict

from utils.web_system_settings import (
    get_llm_preset_templates,
    load_system_settings,
    save_system_settings,
)


def _templates() -> Dict[str, Dict[str, str]]:
    return get_llm_preset_templates()


def load_api_config() -> Dict[str, Dict[str, str]]:
    s = load_system_settings()
    lp = s.get("llm_api_presets")
    if not isinstance(lp, dict):
        return dict(_templates())
    return {str(k): dict(v) for k, v in lp.items() if isinstance(v, dict)}


def save_api_config(configs: Any) -> None:
    if not isinstance(configs, dict):
        return
    save_system_settings({"llm_api_presets": dict(configs)})


def _resolve_active_config_name() -> str:
    env_name = os.environ.get("RAG_API_CONFIG_NAME", "").strip()
    if env_name:
        return env_name
    try:
        import streamlit as st

        return st.session_state.get("current_api_config", "DeepSeek")
    except Exception:
        return "DeepSeek"


def get_active_preset_name() -> str:
    return _resolve_active_config_name()


def get_api_config_for(config_name: str | None) -> dict:
    configs = load_api_config()
    tmpl = _templates()
    name = config_name if config_name else _resolve_active_config_name()
    if name in configs:
        return dict(configs[name])
    return dict(tmpl.get(name) or tmpl.get("DeepSeek") or _blank_custom())


def get_current_config() -> dict:
    return get_api_config_for(None)


def update_config(config_name: str, base_url: str, api_key: str, model: str) -> Dict[str, Dict[str, str]]:
    configs = load_api_config()
    cn = (config_name or "").strip()
    if not cn:
        return configs
    if cn not in configs:
        configs[cn] = dict(_templates().get("自定义", _blank_custom()))
    cur = dict(configs[cn])
    cur["base_url"] = base_url
    cur["api_key"] = api_key
    cur["model"] = model
    if "provider" not in cur or not str(cur.get("provider") or "").strip():
        cur["provider"] = "custom"
    configs[cn] = cur
    save_api_config(configs)
    return configs


def _blank_custom() -> Dict[str, str]:
    return {"base_url": "", "api_key": "", "model": "", "provider": "custom"}
