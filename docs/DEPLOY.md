# 部署文档 — RAG-KnowledgeBase

本文档说明如何从零部署本系统的 **Web 多用户版**（FastAPI + MySQL + 静态前端）。

---

## 1. 环境要求

| 项 | 要求 |
|----|------|
| Python | 3.10+（推荐 3.11，实测于 `rag_demo` conda 环境） |
| 数据库 | MySQL 5.7+ / 8.0（认证、审计、全局动态配置） |
| 可选 | Tesseract（图片型 PDF OCR） |
| 可选 | 云端模型 API（硅基流动 / OpenAI 兼容 / 其他，用于 embedding/rerank/LLM） |

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

### 2.1 密钥与连接（config.json，启动读一次）

所有密钥与模型默认配置统一存放在 **`config.json`**（启动时读取一次）。复制模板并填写：

```bash
cp config.example.json config.json
```

`config.json` 结构：

```json
{
  "mysql": {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "你的密码",
    "database": "rag_auth"
  },
  "llm": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-xxx",
    "model": "gpt-4o-mini"
  },
  "deepseek": {
    "base_url": "https://api.deepseek.com",
    "api_key": "sk-xxx",
    "model": "deepseek-chat"
  },
  "embedding": { "provider": "local", "model": "BAAI/bge-small-zh-v1.5" },
  "rerank": { "provider": "local", "model": "BAAI/bge-reranker-base" },
  "siliconflow": { "api_key": "", "base_url": "https://api.siliconflow.cn" },
  "search": { "brave": "", "bocha": "", "qianfan": "" }
}
```

> ⚠️ `config.json` 含明文密钥，已被 `.gitignore` 忽略，切勿提交。服务器上建议设文件权限仅运行用户可读。

### 2.2 配置优先级（重要）

密钥/静态配置与动态配置**分层存放**，各司其职：

```
静态配置（密钥、模型默认值，启动读一次）
  ① 环境变量 / .env（临时覆盖，最高）
  ② config.json（密钥唯一持久化来源）
  ③ 硬编码默认值

动态配置（运行时热改，管理端后台，存 MySQL app_settings）
  · LLM 预设、检索参数、chunk 层级、联网密钥、配额、开关、限流
  · 向量模型 provider 清单、当前嵌入/重排 provider 与模型
```

- 「MySQL 连接、模型路径、Tesseract 路径、API 密钥」→ 改 `config.json`（或环境变量）后**重启**；
- 「开关、限流、LLM 预设、provider 选择」→ 管理端**动态改、免重启**。

---

## 3. 向量模型 provider 配置（嵌入 / 重排序）

嵌入与重排序模型支持**本地**与**任意 OpenAI 兼容云端 API**（硅基流动、Jina、Together 等），可增删多个 provider。

**方式一：管理端配置（推荐，动态生效）**

管理站 → 设置 → 模型配置 →「向量模型（嵌入 / 重排）」标签页：

1. 「Provider 管理」卡片点「＋新增 Provider」，填 name / label / type（本地 / OpenAI 兼容）/ Base URL / API Key；
2. 「嵌入模型」「重排序模型」卡片分别选 Provider + 模型名；
3. 「获取模型列表」填 Base URL + API Key 后拉取，填充模型下拉；
4. 保存。

**方式二：config.json 配置（启动读一次）**

```json
{
  "embedding": { "provider": "local", "model": "BAAI/bge-small-zh-v1.5" },
  "rerank": { "provider": "local", "model": "BAAI/bge-reranker-base" },
  "siliconflow": { "api_key": "sk-xxx", "base_url": "https://api.siliconflow.cn" }
}
```

> 常用云端模型（硅基流动）：嵌入 `BAAI/bge-m3`，重排 `BAAI/bge-reranker-v2-m3`。
> ⚠️ 切换嵌入模型后**需重建向量库**（维度可能不同），否则旧索引不兼容。

---

## 4. 初始化数据库

系统首次启动会自动建表（`utils/auth_db_backend.mysql_init_tables`），但需先创建库：

```sql
CREATE DATABASE IF NOT EXISTS rag_auth
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;
```

> 若已有 SQLite 认证数据，可用迁移脚本：
> `python scripts/migrate_auth_sqlite_to_mysql.py`

---

## 5. 启动

### 5.1 双端口模式（推荐：用户站 + 管理站）

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

### 5.2 单端口单体模式

```bash
python -m web_app.backend.run_uvicorn
# 默认 PORT=8765，用户 / + 管理 /admin/
```

### 5.3 管理端初始账号

首次启动后访问管理站 `/admin/register.html` 注册管理员（`POST /api/auth/register-admin`）。

---

## 6. Nginx 反向代理（可选）

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

## 7. 运维要点

| 项 | 说明 |
|----|------|
| 日志 | 文件日志在 `data/streamlit/knowledge_db/logs/system.log`（UTF-8） |
| 向量缓存 | 进程内 LRU（`web_app/backend/vdb_cache.py`），可调 UVICORN 参数 |
| 限流 | 聊天 QPM、登录防爆破 → 管理端配置 |
| 审计 | 管理端「日志/审计」页，含 API 审计、登录审计、token 统计 |
| 检索评测 | `python scripts/eval_retrieval.py --user 98`（见 `docs/eval_report.md`） |

---

## 8. 常见问题

**Q：启动报「无法连接 MySQL」？**
A：确认 `config.json` 里 `mysql.*` 正确，且已 `CREATE DATABASE rag_auth`。

**Q：改了 config.json 里的密钥不生效？**
A：密钥是「启动读一次」，改后需重启服务。管理端后台配置的则动态生效。

**Q：日志中文乱码？**
A：设置 `PYTHONIOENCODING=utf-8` 或使用 UTF-8 终端；文件日志已强制 UTF-8。

**Q：首次入库很慢？**
A：首次使用本地 embedding/reranker 模型会下载（bge-small ~400MB、reranker ~1GB），之后缓存到 `models/`。用云端模型则无此问题。

**Q：切换嵌入模型后检索异常？**
A：嵌入模型维度变化会导致旧 FAISS 索引不兼容，需在管理端「向量维护」重建该用户的向量库。

---

> 更多架构细节见项目内 `paper/` 设计文档与根目录 `README.md`。
