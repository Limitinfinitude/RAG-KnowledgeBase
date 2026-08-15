"""将管理端各页 <nav class="gpt-sidebar-nav"> 与侧栏常用区块统一（改版后重新运行）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ADMIN = Path(__file__).resolve().parents[1] / "frontend" / "admin"

# 当前页：users | docs | trash | analytics | monitor | logs | flags | advanced | vector | settings
PAGES = {
    "users.html": "users",
    "docs.html": "docs",
    "trash.html": "trash",
    "analytics.html": "analytics",
    "monitor.html": "monitor",
    "logs.html": "logs",
    "flags.html": "flags",
    "advanced.html": "advanced",
    "vector.html": "vector",
    "settings.html": "settings",
}


def cur(active: str, page: str) -> str:
    return ' aria-current="page"' if active == page else ""


def build_nav(active: str) -> str:
    c = lambda p: cur(active, p)  # noqa: E731
    return f"""      <nav class="gpt-sidebar-nav" aria-label="管理功能">
        <a href="/admin/users.html" class="gpt-nav-item"{c("users")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></span><span class="gpt-nav-label">用户管理</span>
        </a>
        <a href="/admin/docs.html" class="gpt-nav-item"{c("docs")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span><span class="gpt-nav-label">知识库与文档</span>
        </a>
        <a href="/admin/trash.html" class="gpt-nav-item"{c("trash")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg></span><span class="gpt-nav-label">文档回收站</span>
        </a>
        <a href="/admin/analytics.html" class="gpt-nav-item"{c("analytics")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 16V8"/><path d="M12 16v-5"/><path d="M17 16V4"/></svg></span><span class="gpt-nav-label">统计与运营</span>
        </a>
        <a href="/admin/monitor.html" class="gpt-nav-item"{c("monitor")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg></span><span class="gpt-nav-label">监控台</span>
        </a>
        <a href="/admin/logs.html" class="gpt-nav-item"{c("logs")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg></span><span class="gpt-nav-label">操作日志</span>
        </a>
        <a href="/admin/flags.html" class="gpt-nav-item"{c("flags")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg></span><span class="gpt-nav-label">功能开关</span>
        </a>
        <a href="/admin/advanced.html" class="gpt-nav-item"{c("advanced")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3h7v7H3z"/><path d="M14 3h7v7h-7z"/><path d="M14 14h7v7h-7z"/><path d="M3 14h7v7H3z"/></svg></span><span class="gpt-nav-label">高级参数</span>
        </a>
        <a href="/admin/vector.html" class="gpt-nav-item"{c("vector")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z"/></svg></span><span class="gpt-nav-label">向量维护</span>
        </a>
        <a href="/admin/settings.html?tab=set-model" class="gpt-nav-item"{c("settings")}>
          <span class="gpt-nav-ico" aria-hidden="true"><svg class="gpt-nav-svg" viewBox="0 0 24 24" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg></span><span class="gpt-nav-label">模型配置</span>
        </a>
      </nav>"""


def patch_sidebar_chrome(text: str) -> str:
    text = re.sub(
        r'<a href="/admin/" class="gpt-btn-newchat"[^>]*>\s*<span class="gpt-icon">[^<]*</span><span class="gpt-sidebar-btn-text">新建对话</span>\s*</a>',
        '<a href="/admin/users.html" class="gpt-btn-newchat" style="text-decoration:none;display:flex;align-items:center;justify-content:center;gap:0.35rem;">'
        '<span class="gpt-icon">⌂</span><span class="gpt-sidebar-btn-text">管理首页</span></a>',
        text,
        count=1,
    )
    text = re.sub(
        r'\s*<section class="gpt-sidebar-history"[^>]*>.*?</section>\s*',
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'<button type="button" class="gpt-dropdown-item" data-menu="appearance"[^>]*>.*?</button>\s*',
        "",
        text,
        count=1,
        flags=re.DOTALL,
    )
    return text


def patch_topbar_back(text: str) -> str:
    return re.sub(
        r'<a href="/admin/"([^>]*>)\s*返回问答\s*</a>',
        r'<a href="/admin/users.html"\1返回管理</a>',
        text,
    )


def patch_file(path: Path, active: str) -> bool:
    text = path.read_text(encoding="utf-8")
    nav = build_nav(active)
    pattern = re.compile(
        r"^\s*<nav class=\"gpt-sidebar-nav\"[^>]*>.*?</nav>\s*$",
        re.MULTILINE | re.DOTALL,
    )
    if not pattern.search(text):
        print(f"skip (no nav match): {path.name}", file=sys.stderr)
        return False
    new_text, n = pattern.subn(nav.rstrip() + "\n", text, count=1)
    if n != 1:
        return False
    new_text = patch_sidebar_chrome(new_text)
    new_text = patch_topbar_back(new_text)
    path.write_text(new_text, encoding="utf-8")
    print(f"ok: {path.name}")
    return True


def main() -> None:
    for name, page in PAGES.items():
        p = ADMIN / name
        if not p.is_file():
            print(f"missing: {p}", file=sys.stderr)
            continue
        patch_file(p, page)


if __name__ == "__main__":
    main()
