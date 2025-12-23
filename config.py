# config.py
import os

API_KEY = "sk-8CTeK3bUcqjWqfW9WmAtXXkqCeq0UJjNV5V4GdHO601nUR6z"
BASE_URL = "https://api.openai-proxy.org/v1"
DB_DIR = os.path.join(os.path.dirname(__file__), "knowledge_db")

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
RERANKER_MODEL = "BAAI/bge-reranker-base"
LLM_MODEL = "gpt-4o-mini"

TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe'