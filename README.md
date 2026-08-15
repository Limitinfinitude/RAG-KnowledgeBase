<div align="center">

# 🤖 RAG-KnowledgeBase

**基于 LangChain + FAISS 的智能检索与问答知识库系统**

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-%2300A3E0.svg?logo=langchain&logoColor=white)
![FAISS](https://img.shields.io/badge/FAISS-%23FF6F61.svg?logo=facebook&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B.svg?logo=streamlit&logoColor=white)

*文档上传 · 语义检索 · 多轮对话 · 来源溯源 · 双端部署 · 完全离线*

</div>

---

## ✨ 项目简介

RAG-KnowledgeBase 是一个功能完整的 **RAG（检索增强生成）知识库问答系统**。它能够将你的 PDF、Word、TXT、Markdown 等文档构建为可语义检索的知识库，并通过大语言模型给出**带来源溯源的精准回答**。

系统提供**两套运行形态**，共享同一套核心检索与对话引擎：

| 形态 | 入口 | 适用场景 |
|------|------|----------|
| 🖥️ **Streamlit 单机版** | `streamlit run streamlit_app/app.py` | 本地个人知识库、快速体验 |
| 🌐 **Web 多用户版** | `python -m web_app.backend.dual_app` | 多账号、按用户隔离知识库、带管理后台 |

> 核心亮点：**完全支持本地离线运行**，模型首次下载后缓存至本地，之后无需网络即可使用（仅 LLM 调用需配置 API 或本地 Ollama）。

---

## 🌟 主要功能

### 核心能力

- 📄 **多格式文档上传**：PDF（图片型自动 OCR）、DOCX、TXT、MD、XLSX
- 🔍 **智能混合检索**：bge-small-zh-v1.5 向量嵌入 + BM25 混合检索 + RRF 融合
- 🏆 **重排序优化**：bge-reranker CrossEncoder 交叉编码重排，显著提升召回精度
- 🧩 **智能分块**：多层级分块（Small/Medium/Large）+ 父块扩展 + 边界修复
- 💬 **多对话管理**：新建、重命名、删除、置顶、折叠，会话云端同步
- 📊 **来源溯源**：回答标注 `[来源 n]` + 原文片段高亮，杜绝无据幻觉
- 🧭 **意图识别**：智能区分闲聊与文档问答，默认走 RAG，避免误判

### 双模型支持

- ☁️ **OpenAI 兼容 API**：任意 OpenAI 风格 Base URL + API Key + 模型名
- 🦙 **本地 Ollama**：完全离线的本地大模型推理
- 🔄 管理端可维护多套 LLM 预设，无缝切换

### Web 端专有能力

- 👥 **多用户体系**：注册登录、JWT 会话、按用户隔离知识库目录
- 🛡️ **管理后台**：用户管理、文档总览、监控审计、功能开关、向量维护、系统设置
- 📈 **联网检索**：可选 Brave / 博查 / 百度千帆联网搜索，补充实时信息
- ⚡ **大文件后台上传**：Service Worker + 入库队列，页面关闭不中断

---

## 🖼️ 界面预览

### 智能问答

<div align="center">

**知识库问答（多对话 + 检索范围切换 + 来源溯源）**

<img src="screenshots/test1.png" alt="知识库问答" width="90%"/>

**即时文档问答（上传即问，无需入库）**

<img src="screenshots/test2.png" alt="即时文档问答" width="90%"/>

</div>

### 知识库与文档管理

<div align="center">

| 知识库管理 | 文档库管理 |
|:---:|:---:|
| <img src="screenshots/Knowledge_base_management.png" alt="知识库管理" width="400"/> | <img src="screenshots/Library_Management.png" alt="文档库管理" width="400"/> |

</div>

### 管理后台

<div align="center">

**管理端首页**  
<img src="screenshots/manage.png" alt="管理端" width="70%"/>

</div>

### 模型与参数配置

<div align="center">

| 模型设置 | 参数设置 |
|:---:|:---:|
| <img src="screenshots/model_setting.png" alt="模型设置" width="400"/> | <img src="screenshots/Parameter_settings.png" alt="参数设置" width="400"/> |

</div>

### 个性化与功能开关

<div align="center">

| 个性化设置 | 功能开关 |
|:---:|:---:|
| <img src="screenshots/Personalization_settings.png" alt="个性化设置" width="400"/> | <img src="screenshots/Function_switch.png" alt="功能开关" width="400"/> |

</div>

### 运维监控

<div align="center">

| 系统日志 | 向量维护 |
|:---:|:---:|
| <img src="screenshots/logs.png" alt="系统日志" width="400"/> | <img src="screenshots/Vector_maintenance.png" alt="向量维护" width="400"/> |

</div>

---

## 🚀 快速开始

### 环境要求

- **Python 3.10+**（推荐 3.11）
- **Tesseract OCR**（可选，用于图片型 PDF 识别）

### 1. 克隆仓库

```bash
git clone https://github.com/Limitinfinitude/RAG-KnowledgeBase.git
cd RAG-KnowledgeBase
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置密钥（环境变量）

> 出于安全考虑，所有密钥均通过环境变量配置，不再硬编码。

```powershell
# PowerShell 示例（仅按需设置）
$env:API_KEY = "sk-你的OpenAI兼容密钥"
$env:BASE_URL = "https://你的API代理地址/v1"
$env:MYSQL_PASSWORD = "你的数据库密码"    # 仅 Web 版 MySQL 模式需要
$env:BRAVE_SEARCH_API_KEY = "你的Brave密钥"  # 可选，联网检索
```

### 4. 启动

**方式 A：Streamlit 单机版**

```bash
streamlit run streamlit_app/app.py
```

浏览器访问 `http://localhost:8501`，享受本地个人知识库。

**方式 B：Web 多用户版（双端口）**

```bash
python -m web_app.backend.dual_app
```

| 站点 | 地址 |
|------|------|
| 用户站 | http://127.0.0.1:4010/ |
| 管理站 | http://127.0.0.1:4011/ |

> 默认端口可通过环境变量 `RAG_USER_PORT` / `RAG_ADMIN_PORT` 覆盖。

---

## 🗂️ 项目结构

```
RAG-KnowledgeBase/
├── streamlit_app/          # Streamlit 单机应用（5 个页面）
│   ├── app.py              # 入口
│   ├── pages/              # 知识库问答 / 文档问答 / 知识库管理 / 监控台 / 模型设置
│   └── components/         # 侧栏组件
│
├── web_app/                # Web 多用户应用（FastAPI + 静态前端）
│   ├── backend/            # 后端：路由、鉴权中间件、入库队列、向量缓存
│   │   └── routers/        # auth / admin / rag / public 接口分包
│   └── frontend/           # 前端：user / admin / shared 分离
│
├── services/               # 核心业务编排（双端复用）
│   ├── retrieval.py        # RAG 检索管线
│   ├── chat_turn.py        # 对话编排
│   ├── ingest.py           # 文档入库
│   └── llm_factory.py      # LLM 构造
│
├── utils/                  # 工具与领域模块
│   ├── hybrid_search.py    # BM25 + 向量 + RRF 混合检索
│   ├── reranker.py         # CrossEncoder 重排序
│   ├── smart_chunker.py    # 智能多层级分块
│   ├── path_context.py     # 多用户知识库路径隔离
│   └── ...
│
├── models/                 # 本地模型缓存（gitignored）
├── data/                   # 运行时数据（gitignored）
├── config.py               # 全局配置（密钥走环境变量）
└── requirements.txt
```

---

## 🧠 技术栈

| 层级 | 技术 |
|------|------|
| **Web 框架** | FastAPI · Uvicorn · Starlette |
| **单机 UI** | Streamlit |
| **LLM 编排** | LangChain（ChatOpenAI / Ollama） |
| **向量库** | FAISS |
| **嵌入模型** | BAAI/bge-small-zh-v1.5 |
| **重排序模型** | BAAI/bge-reranker-base |
| **混合检索** | rank-bm25 + jieba + RRF |
| **认证** | SQLite / MySQL + JWT Bearer Token |

---

## 🔍 检索流程

```
用户输入
  → 意图识别（闲聊 / RAG）
  → 查询类型分类 + 查询重写
  → 混合检索（BM25 + 向量 + RRF）
  → 重排序（CrossEncoder）
  → 父块扩展（Parent-Document Retrieval）
  → 上下文拼装 → LLM 生成
  → 来源溯源与展示
```

---

## 📄 开源与贡献

欢迎 Star ⭐、Fork 与 PR，一起完善这个项目！如有问题或建议，请提交 [Issue](https://github.com/Limitinfinitude/RAG-KnowledgeBase/issues)。

---

<div align="center">

**如果这个项目对你有帮助，请给一个 Star ⭐ 支持一下！**

</div>
