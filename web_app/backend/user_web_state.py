"""登录用户 Web 端状态：MySQL 为主（chat_sessions / chat_messages / user_preferences），JSON 文件仅作兼容与故障回退。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

from config import WEB_USERS_ROOT

_MAX_JSON_BYTES = 9 * 1024 * 1024


def _state_path(user_id: int) -> str:
    d = os.path.join(WEB_USERS_ROOT, str(int(user_id)))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "web_ui_state.json")


def _load_from_file(user_id: int) -> Dict[str, Any]:
    p = _state_path(user_id)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def remove_legacy_web_ui_state_file(user_id: int) -> None:
    try:
        p = _state_path(user_id)
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        pass


def load_web_ui_state(user_id: int) -> Dict[str, Any]:
    try:
        from utils.web_ui_state_mysql import (
            load_web_ui_state_from_mysql,
            mysql_has_any_web_state,
            sync_web_ui_payload_to_mysql,
        )

        file_data = _load_from_file(user_id)
        if not mysql_has_any_web_state(user_id):
            if file_data:
                try:
                    sync_web_ui_payload_to_mysql(user_id, file_data)
                    remove_legacy_web_ui_state_file(user_id)
                except Exception:
                    return file_data
            return load_web_ui_state_from_mysql(user_id) or file_data
        out = load_web_ui_state_from_mysql(user_id)
        if not out and file_data:
            return file_data
        return out
    except Exception:
        return _load_from_file(user_id)


def save_web_ui_state(user_id: int, payload: Dict[str, Any]) -> None:
    payload = dict(payload)
    payload["version"] = int(payload.get("version") or 1)
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    if len(raw.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError("同步数据过大，请减少历史对话数量后再试")
    try:
        from utils.web_ui_state_mysql import sync_web_ui_payload_to_mysql

        sync_web_ui_payload_to_mysql(user_id, payload)
        remove_legacy_web_ui_state_file(user_id)
    except Exception:
        p = _state_path(user_id)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp, p)
        raise
