"""从 HTTP 请求解析客户端 IP（代理场景下尽量取可信前置）。"""
from __future__ import annotations

from fastapi import Request


def get_client_ip(request: Request) -> str:
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip()[:128]
    xri = (request.headers.get("x-real-ip") or "").strip()
    if xri:
        return xri[:128]
    try:
        c = request.client
        if c and c.host:
            return str(c.host)[:128]
    except Exception:
        pass
    return ""
