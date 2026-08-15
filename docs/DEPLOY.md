# 部署文档 — RAG-KnowledgeBase

本文档说明如何从零部署本系统的 **Web 多用户版**（FastAPI + MySQL + 静态前端）。

---

## 1. 环境要求

| 项 | 要求 |
|----|------|
| Python | 3.10+（推荐 3.11，实测于 `rag_demo` conda 环境） |
| 数据库 | MySQL 5.7+ / 8.0（认证与全局配置主存） |
| 可选 | Tesseract（图片型 PDF OCR） |
| 可选 | Ollama（本地大模型推理） |

### 1.1 推荐环境（可复现）

```bash
# conda 用户：直接用导出的环境
conda env create -f environment.yml
conda activate rag_demo

# pip 用户：先装直接依赖（精确版本），再装完整快照
pip install -r requirements.txt
# 或完整传递依赖快照
pip install -r requirements.lock.txt
```

---

## 2. 配置

### 2.1 密钥与连接（.env）

复制模板并填写真实值（`.env` 已被 `.gitignore` 忽略，勿提交）：

```bash
cp .env.example .env
```

`.env` 关键项：

```dotenv
# MySQL 认证库
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=rag_auth

# OpenAI 兼容 LLM
API_KEY=sk-xxx
BASE_URL=https://api.openai.com/v1

# 联网检索（可选，缺省自动禁用）
BRAVE_SEARCH_API_KEY=
BOCHA_API_KEY=
QIANFAN_API_KEY=
```

### 2.2 配置优先级（重要）

系统的**运行时全局配置**主存 MySQL `app_settings` 表，管理端可动态修改、免重启。三层优先级：

```
① MySQL app_settings（管理端热改，最高）
② 环境变量 / .env
③ config.py 默认值（最低，兜底）
```

- 「LLM 预设、检索参数、chunk 层级、联网密钥、配额、开关、限流」等**业务配置** → 管理端动态改；
- 「MySQL 连接、模型路径、Tesseract 路径」等**部署配置** → 改 `.env` 后重启。

---

## 3. 初始化数据库

系统首次启动会自动建表（`utils/auth_db_backend.mysql_init_tables`），但需先创建库：

```sql
CREATE DATABASE IF NOT EXISTS rag_auth
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
```

> 若已有 SQLite 认证数据，可用迁移脚本：
> `python scripts/migrate_auth_sqlite_to_mysql.py`

---

## 4. 启动

### 4.1 双端口模式（推荐：用户站 + 管理站）

```bash
python -m web_app.backend.dual_app
```

| 站点 | 默认地址 |
|------|----------|
| 用户站 | http://127.0.0.1:4010/ |
| 管理站 | http://127.0.0.1:4011/ |

端口可用环境变量覆盖：

```bash
$env:RAG_USER_PORT = "4010"
$env:RAG_ADMIN_PORT = "4011"
$env:RAG_BIND_HOST = "0.0.0.0"
```

### 4.2 单端口单体模式

```bash
python -m web_app.backend.run_uvicorn
# 默认 PORT=8765，用户 / + 管理 /admin/
```

### 4.3 管理端初始账号

首次启动后访问管理站 `/admin/register.html` 注册管理员（`POST /api/auth/register-admin`）。

---

## 5. Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:4010;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;   # LLM 流式响应耗时较长
    }
}
```

> 管理站可同理反代到 4011，或通过 `RAG_ADMIN_PUBLIC_ORIGIN` 配置旧书签跳转。

---

## 6. 运维要点

| 项 | 说明 |
|----|------|
| 日志 | 文件日志在 `data/streamlit/knowledge_db/logs/system.log`（UTF-8） |
| 向量缓存 | 进程内 LRU（`web_app/backend/vdb_cache.py`），可调 UVICORN 参数 |
| 限流 | 聊天 QPM、登录防爆破 → 管理端配置 |
| 审计 | 管理端「日志/审计」页，含 API 审计、登录审计、token 统计 |

---

## 7. 常见问题

**Q：启动报「无法连接 MySQL」？**
A：确认 `.env` 里 `MYSQL_*` 正确，且已 `CREATE DATABASE rag_auth`。

**Q：日志中文乱码？**
A：设置 `PYTHONIOENCODING=utf-8` 或使用 UTF-8 终端；文件日志已强制 UTF-8。

**Q：首次入库很慢？**
A：首次使用 embedding/reranker 模型会下载（bge-small ~400MB、reranker ~1GB），之后缓存到 `models/`。

---

> 更多架构细节见项目内 `paper/` 设计文档与根目录 `README.md`。
