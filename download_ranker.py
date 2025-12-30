from sentence_transformers import CrossEncoder

# 这行会自动下载 bge-reranker-base 到默认缓存目录（通常是 C:\Users\你的用户名\.cache\huggingface\hub\）
model = CrossEncoder('BAAI/bge-reranker-base')
model.save("./models/bge-reranker-base_local")  # 保存到一个你项目里的文件夹