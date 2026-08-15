"""打包 Web 部署用 zip：web_app、services、utils、config.py + requirements-web.txt + DEPLOY.txt。"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web-deploy.zip"

INCLUDE_DIRS = ("web_app", "services", "utils")
INCLUDE_FILES = ("config.py",)


def skip(p: Path) -> bool:
    if "__pycache__" in p.parts:
        return True
    if p.suffix.lower() in (".pyc", ".pyo"):
        return True
    if p.name == ".DS_Store":
        return True
    return False


def add_tree(zf: zipfile.ZipFile, base: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            fp = Path(dirpath) / fn
            if skip(fp):
                continue
            rel = fp.relative_to(ROOT)
            zf.write(fp, arcname=str(rel).replace("\\", "/"))


def main() -> None:
    req = ROOT / "requirements.txt"
    lines = [
        ln
        for ln in req.read_text(encoding="utf-8").splitlines()
        if not ln.strip().startswith("streamlit")
    ]
    req_web = "\n".join(lines) + "\n"

    deploy = """Web 部署包（不含 Streamlit）
============================

1. Python 3.8+（推荐 3.10）；解压后进入该目录。

2. 安装依赖：
   pip install -r requirements-web.txt

3. 单服务：
   uvicorn web_app.backend.app:app --host 0.0.0.0 --port 8765

4. 双端口（用户 + 管理，单进程）：
   python -m web_app.backend.dual_app
   默认用户 8000、管理 8001；可用 RAG_USER_PORT / RAG_ADMIN_PORT 覆盖。

5. 首次运行会创建 data/web/ 等；Linux 请将 config.py 中 TESSERACT_CMD 设为 /usr/bin/tesseract。

6. 管理端配置 LLM；勿泄露 API Key。
"""

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in INCLUDE_DIRS:
            add_tree(zf, ROOT / d)
        for f in INCLUDE_FILES:
            zf.write(ROOT / f, arcname=f.replace("\\", "/"))
        zf.writestr("requirements-web.txt", req_web.encode("utf-8"))
        zf.writestr("DEPLOY.txt", deploy.encode("utf-8"))

    print("已生成:", OUT)
    print("大小:", OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
