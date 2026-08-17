# config.py — 路径规划 + 密钥/模型配置统一入口
# 密钥与模型默认配置统一存 config.json（启动读一次）；环境变量（.env）优先级最高。
import json
import os

# 加载项目根目录的 .env（若存在），使环境变量可覆盖 config.json
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:
    pass

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_CONFIG_JSON_PATH = os.path.join(PROJECT_ROOT, "config.json")


def _load_config_json() -> dict:
    """启动时读一次 config.json，作为密钥/模型的默认来源。"""
    try:
        with open(_CONFIG_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_CONFIG = _load_config_json()


def _pick(env_key: str, *json_keys: str, default: str = "") -> str:
    """配置取值优先级：环境变量 > config.json 嵌套键 > 默认值。"""
    v = os.environ.get(env_key)
    if v is not None and str(v).strip():
        return str(v).strip()
    cur = _CONFIG
    for k in json_keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            cur = None
            break
    if cur is not None and str(cur).strip():
        return str(cur).strip()
    return default


# —— 路径规划：Streamlit 本地一套库，Web 多用户每人一套库 + 全局 server 配置 ——
STREAMLIT_KB_DIR = os.path.join(PROJECT_ROOT, "data", "streamlit", "knowledge_db")
WEB_USERS_ROOT = os.path.join(PROJECT_ROOT, "data", "web", "users")
WEB_SERVER_DIR = os.path.join(PROJECT_ROOT, "data", "web", "server")

# —— MySQL 认证库连接（环境变量 > config.json.mysql > 默认）——
MYSQL_HOST = _pick("MYSQL_HOST", "mysql", "host", default="127.0.0.1")
try:
    MYSQL_PORT = int(_pick("MYSQL_PORT", "mysql", "port", default="3306") or 3306)
except (TypeError, ValueError):
    MYSQL_PORT = 3306
MYSQL_USER = _pick("MYSQL_USER", "mysql", "user", default="root")
MYSQL_PASSWORD = _pick("MYSQL_PASSWORD", "mysql", "password", default="")
MYSQL_DATABASE = _pick("MYSQL_DATABASE", "mysql", "database", default="rag_auth")
try:
    SESSION_DAYS = int(_pick("RAG_SESSION_DAYS", "mysql", "session_days", default="7") or 7)
except (TypeError, ValueError):
    SESSION_DAYS = 7

# 兼容旧代码：未设置 path_context 时默认 Streamlit 知识库
DB_DIR = STREAMLIT_KB_DIR

# —— LLM（OpenAI 兼容）——
API_KEY = _pick("API_KEY", "llm", "api_key", default="")
BASE_URL = _pick("BASE_URL", "llm", "base_url", default="https://api.openai.com/v1")

# —— DeepSeek 官方（供 LLM 预设模板与默认值）——
DEEPSEEK_API_KEY = _pick("DEEPSEEK_API_KEY", "deepseek", "api_key", default="")
DEEPSEEK_BASE_URL = _pick("DEEPSEEK_BASE_URL", "deepseek", "base_url", default="https://api.deepseek.com")
DEEPSEEK_MODEL = _pick("DEEPSEEK_MODEL", "deepseek", "model", default="deepseek-chat")

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"
LLM_MODEL = "deepseek-v4-flash"

# —— 嵌入 / 重排序 provider 默认（Web 管理端 MySQL 配置优先级更高）——
EMBEDDING_PROVIDER = _pick("EMBEDDING_PROVIDER", "embedding", "provider", default="local")
RERANK_PROVIDER = _pick("RERANK_PROVIDER", "rerank", "provider", default="local")

# —— 硅基流动（SiliconFlow）云端嵌入/重排序 ——
SILICONFLOW_API_KEY = _pick("SILICONFLOW_API_KEY", "siliconflow", "api_key", default="")
SILICONFLOW_BASE_URL = _pick("SILICONFLOW_BASE_URL", "siliconflow", "base_url", default="https://api.siliconflow.cn")

# —— 联网检索 ——
BRAVE_SEARCH_API_KEY = _pick("BRAVE_SEARCH_API_KEY", "search", "brave", default="")
BOCHA_API_KEY = _pick("BOCHA_API_KEY", "search", "bocha", default="")
QIANFAN_API_KEY = _pick("QIANFAN_API_KEY", "search", "qianfan", default="")
BRAVE_HTTPS_PROXY = (os.environ.get("BRAVE_HTTPS_PROXY") or "").strip()
try:
    BRAVE_SEARCH_TIMEOUT = float(os.environ.get("BRAVE_SEARCH_TIMEOUT", "30"))
except ValueError:
    BRAVE_SEARCH_TIMEOUT = 30.0

# —— Tesseract OCR 路径（跨平台解析；OCR 仅扫描版 PDF / 图片入库时用到）——
# 优先级：环境变量 TESSERACT_CMD > config.json ocr.tesseract_cmd > PATH 中的 tesseract
# > 常见安装路径。找不到时为 None，OCR 调用方会按「未安装 Tesseract」给出明确报错。
def _resolve_tesseract_cmd() -> "str | None":
    v = _pick("TESSERACT_CMD", "ocr", "tesseract_cmd")
    if v:
        return v
    import shutil

    found = shutil.which("tesseract")
    if found:
        return found
    for p in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ):
        if os.path.isfile(p):
            return p
    return None


TESSERACT_CMD = _resolve_tesseract_cmd()

# —— 检索管线的可调超参（集中管理，便于调参；部分可被 Web 管理端 rag_defaults 覆盖）——
# 相似度阈值：低于该分值的检索结果视为低质量，回退取前若干条
# （2026-08-17 标定：作用在重排概率上时，正样本 p25=0.851、负样本绝大多数 <0.25，0.3 有效；
#   注意向量相似度分数与该阈值不可比，最终防线应依赖重排，详见 docs/2026-08-17-修复与升级记录.md）
SIMILARITY_THRESHOLD = 0.3
# 绝对下限：最高分低于此值视为「无相关内容」，返回空而非硬凑低分结果
# （2026-08-17 重标定：bge-m3 下正样本 top1 0.520~0.833 与负样本 0.500~0.607 重叠，
#   0.5 只能当廉价预过滤，不能作为最终判别——维持现值，勿调高）
ABSOLUTE_MIN_SCORE = 0.5
# 送入 LLM 的上下文最大字符数（超出则截断）
# （2026-08-17：4000→10000，父块扩展去重与 k 生效后旧值会频繁截断不同来源）
MAX_CONTEXT_LENGTH = 10000
# 最终进入上下文的召回片段数量下限（实际取 max(调用方 k, 本值)）
CONTEXT_TOP_K = 8
# 低质量结果回退时保留的最大条数
LOW_QUALITY_FALLBACK_K = 3
