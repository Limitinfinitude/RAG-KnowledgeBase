"""
已迁移：请从项目根目录运行

  streamlit run streamlit_app/app.py

线上 Web（多用户）：

  uvicorn web_app.backend.app:app --host 0.0.0.0 --port 8765

  双端口（用户 8000 + 管理 8001，单进程）：

  python -m web_app.backend.dual_app
"""
raise SystemExit(
    "请使用: streamlit run streamlit_app/app.py\n"
    "或 Web: uvicorn web_app.backend.app:app --reload --port 8765\n"
    "或双端口: python -m web_app.backend.dual_app"
)
