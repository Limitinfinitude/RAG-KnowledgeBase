# test_ollama_list.py
import requests
import json

# 配置 Ollama 的 API 地址（根据你的环境调整）
OLLAMA_BASE_URL = "http://localhost:11434"  # 如果在 Docker 容器中运行，可以试 http://host.docker.internal:11434


def get_ollama_models(base_url: str) -> list:
    try:
        # 确保 URL 以 / 结尾
        if not base_url.endswith('/'):
            base_url += '/'

        api_url = f"{base_url}api/tags"
        print(f"正在请求: {api_url}")

        response = requests.get(api_url, timeout=5)
        print(f"响应状态码: {response.status_code}")

        if response.status_code != 200:
            print(f"错误: {response.text}")
            return []

        data = response.json()
        models = [model['name'] for model in data.get('models', [])]

        print("\n=== 获取到的模型列表 ===")
        if models:
            for model in models:
                print(f"- {model}")
        else:
            print("未找到任何模型")

        return models

    except requests.exceptions.RequestException as e:
        print(f"连接失败: {str(e)}")
        return []


if __name__ == "__main__":
    print("测试 Ollama 模型列表...")
    models = get_ollama_models(OLLAMA_BASE_URL)
    if models:
        print(f"\n成功获取 {len(models)} 个模型！")
    else:
        print("\n获取失败。")