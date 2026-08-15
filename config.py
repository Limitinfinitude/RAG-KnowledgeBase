# config.py — 路径规划：Streamlit 本地一套库，Web 多用户每人一套库 + 全局 server 配置
import os

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
_DEFAULT_MYSQL_PASSWORD = "your_password_here"  # 在此填写数据库密码
_DEFAULT_MYSQL_DATABASE = "rag_auth"
_DEFAULT_SESSION_DAYS = 7

MYSQL_HOST = (os.environ.get("MYSQL_HOST") or _DEFAULT_MYSQL_HOST).strip()
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", str(_DEFAULT_MYSQL_PORT)))
MYSQL_USER = (os.environ.get("MYSQL_USER") or _DEFAULT_MYSQL_USER).strip()
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", _DEFAULT_MYSQL_PASSWORD) or ""
MYSQL_DATABASE = (os.environ.get("MYSQL_DATABASE") or _DEFAULT_MYSQL_DATABASE).strip()
SESSION_DAYS = int(os.environ.get("RAG_SESSION_DAYS", str(_DEFAULT_SESSION_DAYS)))

# 兼容旧代码：未设置 path_context 时默认 Streamlit 知识库
DB_DIR = STREAMLIT_KB_DIR

API_KEY = "sk-xxx"  # 在此填写 OpenAI 兼容 API Key
BASE_URL = "https://api.openai-proxy.org/v1"

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"
LLM_MODEL = "gpt-4o-mini"

# Brave 联网检索：优先环境变量；未设置时可用 _BRAVE_KEY_IN_FILE（仅本地、勿提交真实密钥）。
_BRAVE_KEY_IN_FILE = ""  # 在此填写 Brave Search API Key（可选）
BRAVE_SEARCH_API_KEY = (
    (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip() or str(_BRAVE_KEY_IN_FILE or "").strip()
)
# 博查（Streamlit 或未配管理端密钥时）：环境变量 BOCHA_API_KEY 或下方留空
_BOCHA_KEY_IN_FILE = ""  # 在此填写博查 API Key（可选）
BOCHA_API_KEY = (os.environ.get("BOCHA_API_KEY") or "").strip() or str(_BOCHA_KEY_IN_FILE or "").strip()
# 国内直连 api.search.brave.com 常超时：可设 BRAVE_HTTPS_PROXY（仅 Brave 请求）或系统 HTTPS_PROXY
BRAVE_HTTPS_PROXY = (os.environ.get("BRAVE_HTTPS_PROXY") or "").strip()
try:
    BRAVE_SEARCH_TIMEOUT = float(os.environ.get("BRAVE_SEARCH_TIMEOUT", "30"))
except ValueError:
    BRAVE_SEARCH_TIMEOUT = 30.0

# 百度千帆 AI 搜索 web_search：环境变量 QIANFAN_API_KEY 或下方本地项（与 Brave/Bocha 配置方式一致）
_QIANFAN_KEY_IN_FILE = ""  # 在此填写百度千帆 API Key（可选）
QIANFAN_API_KEY = (os.environ.get("QIANFAN_API_KEY") or "").strip() or str(_QIANFAN_KEY_IN_FILE or "").strip()

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
