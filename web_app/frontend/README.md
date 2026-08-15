# 前端目录说明

| 目录 | 访问前缀 | 内容 |
|------|-----------|------|
| `shared/` | `/static/` | 共用静态资源：`style.css`、`app.js`、`upload-sw.js`、认证页样式、`assets/` |
| `user/` | `/` | 用户端页面：`index.html`（首页）、`kb.html`、`settings.html`、`login.html`、`register.html` |
| `admin/` | `/admin/` | 管理端页面：`users.html`、`docs.html`、`trash.html`、`settings.html` 等；`index.html` 跳转用户管理 |

Service Worker 仍通过根路径 **`GET /upload-sw.js`** 提供（由后端映射到 `shared/upload-sw.js`），以保证默认作用域为整站。

旧书签（如 `/admin.html`）由后端 **307 重定向** 到新路径。

维护脚本（在仓库根目录执行）：

- `python web_app/scripts/repair_html_utf8.py` — 修复 HTML UTF-8 截断
- `python web_app/scripts/rebuild_chat_pages.py` — 从侧栏模板再生 `user/index.html` 与 `admin/index.html`（慎用，先备份）
