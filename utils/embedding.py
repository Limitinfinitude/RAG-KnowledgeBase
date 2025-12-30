# utils/embedding.py
import os
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder, SentenceTransformer

# ------------------- get_embeddings：自动下载 + 本地优先 -------------------
def get_embeddings():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    # 本地模型路径（你原来的结构）
    local_model_path = os.path.join(
        project_root,
        "models",
        "models--BAAI--bge-small-zh-v1.5",
        "snapshots",
        "7999e1d3359715c523056ef9478215996d62a620"  # 你的 commit hash
    )

    # 保存的自定义路径（更友好，别人运行时会下载到这里）
    custom_save_path = os.path.join(project_root, "models", "bge-small-zh-v1.5_local")

    device = 'cuda' if os.environ.get('CUDA_VISIBLE_DEVICES') is not None else 'cpu'

    # 优先尝试本地路径
    if os.path.exists(local_model_path):
        print(f"[Embedding] 使用本地模型: {local_model_path}")
        return HuggingFaceEmbeddings(
            model_name=local_model_path,
            model_kwargs={"device": device, "local_files_only": True}
        )
    elif os.path.exists(custom_save_path):
        print(f"[Embedding] 使用本地缓存模型: {custom_save_path}")
        return HuggingFaceEmbeddings(
            model_name=custom_save_path,
            model_kwargs={"device": device, "local_files_only": True}
        )
    else:
        # 本地没有，自动下载
        print("[Embedding] 本地模型不存在，正在从 Hugging Face 下载 BAAI/bge-small-zh-v1.5 ...")
        print("（约 400MB，第一次运行较慢，后续离线使用）")

        # 使用 SentenceTransformer 下载并保存
        model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
        os.makedirs(custom_save_path, exist_ok=True)
        model.save(custom_save_path)
        print(f"[Embedding] 下载完成，已保存到: {custom_save_path}")

        return HuggingFaceEmbeddings(
            model_name=custom_save_path,
            model_kwargs={"device": device}
        )

# ------------------- get_reranker：自动下载 + 本地优先 -------------------
def get_reranker():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    local_reranker_path = os.path.join(project_root, "models", "bge-reranker-base_local")

    device = 'cuda' if os.environ.get('CUDA_VISIBLE_DEVICES') is not None else 'cpu'

    if os.path.exists(local_reranker_path):
        print(f"[Reranker] 使用本地 reranker: {local_reranker_path}")
        return CrossEncoder(local_reranker_path, device=device)
    else:
        print("[Reranker] 本地 reranker 不存在，正在从 Hugging Face 下载 BAAI/bge-reranker-base ...")
        print("（约 1GB，第一次运行较慢，后续离线使用）")

        model = CrossEncoder("BAAI/bge-reranker-base")
        os.makedirs(local_reranker_path, exist_ok=True)
        model.save(local_reranker_path)
        print(f"[Reranker] 下载完成，已保存到: {local_reranker_path}")

        return CrossEncoder(local_reranker_path, device=device)