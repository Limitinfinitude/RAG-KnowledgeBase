# utils/embedding.py
import logging
import os
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder, SentenceTransformer

logger = logging.getLogger(__name__)

# ------------------- get_embeddings：provider 选择（云端 OpenAI 兼容 / 本地） -------------------
def get_embeddings():
    from utils.web_system_settings import get_embedding_config

    cfg = get_embedding_config()
    if cfg["provider_type"] != "local":
        from utils.siliconflow_client import SiliconFlowEmbeddings

        logger.info("[Embedding] 使用云端嵌入模型 %s（provider=%s）", cfg["model"], cfg["provider"])
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


# ------------------- get_reranker：统一在 utils/reranker.py（含进程级缓存） -------------------