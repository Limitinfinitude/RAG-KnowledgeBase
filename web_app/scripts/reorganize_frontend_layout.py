# -*- coding: utf-8 -*-
"""
将 web_app/frontend 整理为：
  shared/  共用静态资源（css、js、upload-sw、assets）
  user/    用户端页面（根路径 / 下访问）
  admin/   管理端页面（前缀 /admin/ 下访问）

在仓库根目录执行: python web_app/scripts/reorganize_frontend_layout.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FR = ROOT / "web_app" / "frontend"
SHARED = FR / "shared"
USER = FR / "user"
ADMIN = FR / "admin"


def fix_static_paths(s: str) -> str:
    s = s.replace('href="/style.css', 'href="/static/style.css')
    s = s.replace('href="/app.js', 'href="/static/app.js')
    s = s.replace('src="/app.js', 'src="/static/app.js')
    s = s.replace('href="/auth-pages.css', 'href="/static/auth-pages.css')
    s = s.replace('href="/auth-admin.css', 'href="/static/auth-admin.css')
    return s


def fix_user_html(s: str) -> str:
    s = fix_static_paths(s)
    s = s.replace('href="/admin-login.html', 'href="/admin/login.html')
    s = s.replace('href="/admin-register.html', 'href="/admin/register.html')
    return s


def fix_admin_html(s: str) -> str:
    s = fix_static_paths(s)
    # 长的先替换，避免残留
    pairs = [
        ("/admin-settings.html", "/admin/settings.html"),
        ("/admin-console.html", "/admin/users.html"),
        ("/admin-register.html", "/admin/register.html"),
        ("/admin-login.html", "/admin/login.html"),
        ("/admin-advanced.html", "/admin/advanced.html"),
        ("/admin-monitor.html", "/admin/monitor.html"),
        ("/admin-vector.html", "/admin/vector.html"),
        ("/admin-users.html", "/admin/users.html"),
        ("/admin-docs.html", "/admin/docs.html"),
        ("/admin-flags.html", "/admin/flags.html"),
        ("/admin-kb.html", "/admin/docs.html"),
        ('"/admin.html"', '"/admin/"'),
        ("'/admin.html'", "'/admin/'"),
        ("/admin.html?", "/admin/?"),
        ("/admin.html#", "/admin/#"),
        ("/admin.html\"", "/admin/\""),
        ("/admin.html'", "/admin/'"),
        ("/admin.html>", "/admin/>"),
        ("/admin.html ", "/admin/ "),
        ("/admin.html\n", "/admin/\n"),
        ("/admin.html\r", "/admin/\r"),
        ("/admin.html", "/admin/"),
    ]
    for a, b in pairs:
        s = s.replace(a, b)
    return s


def main() -> None:
    if not FR.is_dir():
        print("Missing", FR)
        sys.exit(1)

    SHARED.mkdir(parents=True, exist_ok=True)
    USER.mkdir(parents=True, exist_ok=True)
    ADMIN.mkdir(parents=True, exist_ok=True)

    for name in ("style.css", "app.js", "upload-sw.js", "auth-pages.css", "auth-admin.css"):
        src = FR / name
        if src.is_file():
            shutil.move(str(src), str(SHARED / name))

    assets_src = FR / "assets"
    if assets_src.is_dir():
        dest = SHARED / "assets"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(assets_src), str(dest))

    user_files = ["index.html", "kb.html", "settings.html", "login.html", "register.html"]
    for n in user_files:
        src = FR / n
        if src.is_file():
            shutil.move(str(src), str(USER / n))
            text = (USER / n).read_text(encoding="utf-8")
            (USER / n).write_text(fix_user_html(text), encoding="utf-8")

    admin_moves = [
        ("admin.html", "index.html"),
        ("admin-kb.html", "kb.html"),
        ("admin-settings.html", "settings.html"),
        # 历史 admin-console.html 已废弃；链接在 fix_admin_html 中改为 /admin/users.html
        ("admin-users.html", "users.html"),
        ("admin-docs.html", "docs.html"),
        ("admin-monitor.html", "monitor.html"),
        ("admin-flags.html", "flags.html"),
        ("admin-advanced.html", "advanced.html"),
        ("admin-vector.html", "vector.html"),
        ("admin-login.html", "login.html"),
        ("admin-register.html", "register.html"),
    ]
    for old, new in admin_moves:
        src = FR / old
        if not src.is_file():
            continue
        dest = ADMIN / new
        shutil.move(str(src), str(dest))
        text = dest.read_text(encoding="utf-8")
        dest.write_text(fix_admin_html(text), encoding="utf-8")

    # 管理端登录页脚本里的默认 next
    adm_login = ADMIN / "login.html"
    if adm_login.is_file():
        t = adm_login.read_text(encoding="utf-8")
        t = t.replace('|| "/admin.html"', '|| "/admin/"')
        t = t.replace("/admin.html", "/admin/")
        adm_login.write_text(t, encoding="utf-8")

    adm_reg = ADMIN / "register.html"
    if adm_reg.is_file():
        t = adm_reg.read_text(encoding="utf-8")
        t = t.replace("/admin-login.html", "/admin/login.html")
        adm_reg.write_text(t, encoding="utf-8")

    print("Done. Remaining in frontend root (manual cleanup if any):", list(FR.iterdir()))


if __name__ == "__main__":
    main()
