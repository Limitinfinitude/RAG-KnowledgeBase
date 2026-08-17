# utils/metadata_manager.py
"""
文档元数据管理系统
用于存储和管理文档的分类、信息、上传时间等元数据
"""
import logging
import os
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from utils.path_context import get_current_web_user_id, get_kb_dir
from utils.web_system_settings import is_kb_disabled_for_user

logger = logging.getLogger(__name__)

# 元数据读缓存（path -> (mtime, data)）：一次检索会多次全量读 documents_metadata.json，
# 写入经 save_metadata 后 mtime 变化自动失效；按 path 隔离，多用户安全
_meta_cache: Dict[str, Tuple[float, Dict]] = {}
_meta_cache_lock = threading.Lock()

MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024  # 50MB


def _metadata_file() -> str:
    return os.path.join(get_kb_dir(), "documents_metadata.json")


def load_metadata() -> Dict:
    """加载文档元数据（mtime 缓存）"""
    path = _metadata_file()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {"documents": {}, "categories": ["默认知识库"]}
    with _meta_cache_lock:
        hit = _meta_cache.get(path)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("加载元数据失败: %s", e)
        return {"documents": {}, "categories": ["默认知识库"]}
    if not isinstance(data, dict):
        data = {"documents": {}, "categories": ["默认知识库"]}
    with _meta_cache_lock:
        _meta_cache[path] = (mtime, data)
    return data


def save_metadata(metadata: Dict):
    """保存文档元数据"""
    kb = get_kb_dir()
    os.makedirs(kb, exist_ok=True)
    with open(_metadata_file(), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def add_document_metadata(file_name: str, file_size: int, file_type: str, 
                         category: str = "默认知识库", description: str = ""):
    """添加文档元数据"""
    metadata = load_metadata()
    if "documents" not in metadata:
        metadata["documents"] = {}
    
    metadata["documents"][file_name] = {
        "file_name": file_name,
        "file_size": file_size,
        "file_size_mb": round(file_size / (1024 * 1024), 2),
        "file_type": file_type,
        "category": category,
        "description": description,
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "chunks_count": 0
    }
    
    # 确保分类存在
    if "categories" not in metadata:
        metadata["categories"] = ["默认知识库"]
    if category not in metadata["categories"]:
        metadata["categories"].append(category)
    
    save_metadata(metadata)


def update_document_metadata(file_name: str, **kwargs):
    """更新文档元数据"""
    metadata = load_metadata()
    if file_name in metadata.get("documents", {}):
        metadata["documents"][file_name].update(kwargs)
        metadata["documents"][file_name]["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_metadata(metadata)
        return True
    return False


def get_document_metadata(file_name: str) -> Optional[Dict]:
    """获取文档元数据"""
    metadata = load_metadata()
    return metadata.get("documents", {}).get(file_name)


def delete_document_metadata(file_name: str):
    """删除文档元数据"""
    metadata = load_metadata()
    if file_name in metadata.get("documents", {}):
        del metadata["documents"][file_name]
        save_metadata(metadata)
        return True
    return False


def get_all_documents(include_deleted: bool = False) -> List[Dict]:
    """获取所有文档元数据列表"""
    metadata = load_metadata()
    docs = list(metadata.get("documents", {}).values())
    if not include_deleted:
        docs = [d for d in docs if not bool(d.get("is_deleted"))]
    uid = get_current_web_user_id()
    if uid is not None:
        docs = [
            d
            for d in docs
            if not is_kb_disabled_for_user(uid, str(d.get("category") or "默认知识库"))
        ]
    return docs


def get_categories() -> List[str]:
    """获取所有分类（Web 多用户下排除被管理员禁用的知识库名）。"""
    metadata = load_metadata()
    cats = list(metadata.get("categories", ["默认知识库"]))
    uid = get_current_web_user_id()
    if uid is None:
        return cats
    return [c for c in cats if not is_kb_disabled_for_user(uid, c)]


def add_category(category: str):
    """添加分类"""
    metadata = load_metadata()
    if "categories" not in metadata:
        metadata["categories"] = []
    if category not in metadata["categories"]:
        metadata["categories"].append(category)
        save_metadata(metadata)
        return True
    return False


def delete_category(category: str, move_to: str = "默认知识库"):
    """删除分类，并将该分类下的文档移动到指定分类"""
    metadata = load_metadata()
    if category in metadata.get("categories", []):
        metadata["categories"].remove(category)
        # 将该分类下的文档移动到新分类
        for doc_name, doc_info in metadata.get("documents", {}).items():
            if doc_info.get("category") == category:
                doc_info["category"] = move_to
        save_metadata(metadata)
        return True
    return False


def get_documents_by_category(category: str, include_deleted: bool = False) -> List[Dict]:
    """获取指定分类下的所有文档"""
    uid = get_current_web_user_id()
    if uid is not None and is_kb_disabled_for_user(uid, category):
        return []
    metadata = load_metadata()
    docs = [
        doc for doc in metadata.get("documents", {}).values()
        if doc.get("category") == category
    ]
    if include_deleted:
        return docs
    return [d for d in docs if not bool(d.get("is_deleted"))]


def update_chunks_count(file_name: str, count: int):
    """更新文档的分块数量"""
    update_document_metadata(file_name, chunks_count=count)

