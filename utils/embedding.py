# utils/embedding.py
import logging
import os
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder, SentenceTransformer

logger = logging.getLogger(__name__)

# ------------------- get_embeddings：provider 选择（siliconflow 云端 / 本地） -------------------
def get_embeddings():
    from utils.web_system_settings import get_embedding_config

    cfg = get_embedding_config()
    if cfg["provider"] == "siliconflow":
        from utils.siliconflow_client import SiliconFlowEmbeddings

        logger.info("[Embedding] 使用硅基流动云端嵌入模型: %s", cfg["model"])
        return SiliconFlowEmbeddings(api_key=cfg["api_key"], model=cfg["model"], base_url=cfg["base_url"])

    # 本地模型
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_model_path = os.path.join(
        project_root,
        "models",
        "models--BAAI--bge-small-zh-v1.5",
        "snapshots",
        "7999e1d3359715c523056ef9478215996d62a620"  # commit hash
    )
    custom_save_path = os.path.join(project_root, "models", "bge-small-zh-v1.5_local")
    device = 'cuda' if os.environ.get('CUDA_VISIBLE_DEVICES') is not None else 'cpu'

    if os.path.exists(local_model_path):
        logger.info("[Embedding] 使用本地模型: %s", local_model_path)
        return HuggingFaceEmbeddings(
            model_name=local_model_path,
            model_kwargs={"device": device, "local_files_only": True}
        )
    elif os.path.exists(custom_save_path):
        logger.info("[Embedding] 使用本地缓存模型: %s", custom_save_path)
        return HuggingFaceEmbeddings(
            model_name=custom_save_path,
            model_kwargs={"device": device, "local_files_only": True}
        )
    else:
        logger.info("[Embedding] 本地模型不存在，正在从 Hugging Face 下载 BAAI/bge-small-zh-v1.5 ...")
        model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        os.makedirs(custom_save_path, exist_ok=True)
        model.save(custom_save_path)
        logger.info("[Embedding] 下载完成，已保存到: %s", custom_save_path)
        return HuggingFaceEmbeddings(
            model_name=custom_save_path,
            model_kwargs={"device": device}
        )


# ------------------- get_reranker：provider 选择（siliconflow 云端 / 本地） -------------------
def get_reranker():
    from utils.web_system_settings import get_rerank_config

    cfg = get_rerank_config()
    if cfg["provider"] == "siliconflow":
        from utils.siliconflow_client import SiliconFlowReranker

        logger.info("[Reranker] 使用硅基流动云端重排序模型: %s", cfg["model"])
        return SiliconFlowReranker(api_key=cfg["api_key"], model=cfg["model"], base_url=cfg["base_url"])

    # 本地 CrossEncoder
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_reranker_path = os.path.join(project_root, "models", "bge-reranker-base_local")
    device = 'cuda' if os.environ.get('CUDA_VISIBLE_DEVICES') is not None else 'cpu'

    if os.path.exists(local_reranker_path):
        logger.info("[Reranker] 使用本地 reranker: %s", local_reranker_path)
        return CrossEncoder(local_reranker_path, device=device)
    else:
        logger.info("[Reranker] 本地 reranker 不存在，正在从 Hugging Face 下载 BAAI/bge-reranker-base ...")
        model = CrossEncoder("BAAI/bge-reranker-base")
        os.makedirs(local_reranker_path, exist_ok=True)
        model.save(local_reranker_path)
        logger.info("[Reranker] 下载完成，已保存到: %s", local_reranker_path)
        return CrossEncoder(local_reranker_path, device=device)