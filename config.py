# config.py — 路径规划：Streamlit 本地一套库，Web 多用户每人一套库 + 全局 server 配置
import os

# 加载项目根目录的 .env（若存在），使密钥等敏感项脱离代码、仅走环境变量
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# —— Streamlit 本地个人部署：独立知识库（与线上用户完全分离）——
STREAMLIT_KB_DIR = os.path.join(PROJECT_ROOT, "data", "streamlit", "knowledge_db")

# —— Web 线上：每用户 knowledge_db ——
WEB_USERS_ROOT = os.path.join(PROJECT_ROOT, "data", "web", "users")

# —— Web 线上：server 目录（遗留 json 迁移等；LLM 多预设主存 MySQL app_settings）——
WEB_SERVER_DIR = os.path.join(PROJECT_ROOT, "data", "web", "server")

# —— 认证（仅 Web）：MySQL（需 pip install pymysql，并先创建库）——
# 优先读环境变量；未设置时用下方默认值。
#
# PowerShell 示例：
#   $env:MYSQL_HOST = "127.0.0.1"
#   $env:MYSQL_PORT = "3306"
#   $env:MYSQL_USER = "root"
#   $env:MYSQL_PASSWORD = "你的密码"
#   $env:MYSQL_DATABASE = "rag_auth"
#   $env:RAG_SESSION_DAYS = "7"
#
_DEFAULT_MYSQL_HOST = "127.0.0.1"
_DEFAULT_MYSQL_PORT = 3306
_DEFAULT_MYSQL_USER = "root"
_DEFAULT_MYSQL_PASSWORD = ""  # 请通过 .env 的 MYSQL_PASSWORD 或环境变量提供
_DEFAULT_MYSQL_DATABASE = "rag_auth"
_DEFAULT_SESSION_DAYS = 7

MYSQL_HOST = (os.environ.get("MYSQL_HOST") or _DEFAULT_MYSQL_HOST).strip()
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", str(_DEFAULT_MYSQL_PORT)))
MYSQL_USER = (os.environ.get("MYSQL_USER") or _DEFAULT_MYSQL_USER).strip()
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD") or _DEFAULT_MYSQL_PASSWORD or ""
MYSQL_DATABASE = (os.environ.get("MYSQL_DATABASE") or _DEFAULT_MYSQL_DATABASE).strip()
SESSION_DAYS = int(os.environ.get("RAG_SESSION_DAYS", str(_DEFAULT_SESSION_DAYS)))

# 兼容旧代码：未设置 path_context 时默认 Streamlit 知识库
DB_DIR = STREAMLIT_KB_DIR

# 请通过 .env 的 API_KEY / BASE_URL 或环境变量提供
API_KEY = (os.environ.get("API_KEY") or "").strip()
BASE_URL = (os.environ.get("BASE_URL") or "https://api.openai.com/v1").strip()

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"
LLM_MODEL = "deepseek-v4-flash"

# Brave 联网检索：优先环境变量（.env / 系统），不再在代码中留明文密钥。
BRAVE_SEARCH_API_KEY = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
# 博查（Streamlit 或未配管理端密钥时）：环境变量 BOCHA_API_KEY
BOCHA_API_KEY = (os.environ.get("BOCHA_API_KEY") or "").strip()
# 国内直连 api.search.brave.com 常超时：可设 BRAVE_HTTPS_PROXY（仅 Brave 请求）或系统 HTTPS_PROXY
BRAVE_HTTPS_PROXY = (os.environ.get("BRAVE_HTTPS_PROXY") or "").strip()
try:
    BRAVE_SEARCH_TIMEOUT = float(os.environ.get("BRAVE_SEARCH_TIMEOUT", "30"))
except ValueError:
    BRAVE_SEARCH_TIMEOUT = 30.0

# 百度千帆 AI 搜索 web_search：环境变量 QIANFAN_API_KEY
QIANFAN_API_KEY = (os.environ.get("QIANFAN_API_KEY") or "").strip()

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# —— 检索管线的可调超参（集中管理，便于调参；部分可被 Web 管理端 rag_defaults 覆盖）——
# 相似度阈值：低于该分值的检索结果视为低质量，回退取前若干条
SIMILARITY_THRESHOLD = 0.3
# 绝对下限：最高分低于此值视为「无相关内容」，返回空而非硬凑低分结果
# （依据 2026-08-15 评测：正样本最高分 0.62~0.68，负样本 0.41~0.47，取 0.5 可区分）
ABSOLUTE_MIN_SCORE = 0.5
# 送入 LLM 的上下文最大字符数（超出则截断）
MAX_CONTEXT_LENGTH = 4000
# 最终进入上下文的召回片段数量
CONTEXT_TOP_K = 5
# 低质量结果回退时保留的最大条数
LOW_QUALITY_FALLBACK_K = 3

