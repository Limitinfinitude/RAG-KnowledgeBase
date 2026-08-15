"""管理员 Token 统计响应体（供多个路由复用，避免重复逻辑）。"""
from __future__ import annotations

from typing import Any, Dict

from utils.logger import get_recent_logs, get_statistics


def build_admin_token_stats_payload() -> Dict[str, Any]:
    stats = get_statistics() or {}
    recent = list(reversed(get_recent_logs(category="token_usage", limit=80)))
    return {
        "totals": {
            "prompt_tokens": int(stats.get("total_prompt_tokens") or 0),
            "completion_tokens": int(stats.get("total_completion_tokens") or 0),
            "total_tokens": int(stats.get("total_tokens") or 0),
            "calls": int(stats.get("token_usage_calls") or 0),
            "estimated_cost_cny": float(stats.get("estimated_cost") or 0),
        },
        "by_model": stats.get("model_token_stats") or {},
        "by_user": stats.get("user_token_stats") or {},
        "recent": recent,
    }
