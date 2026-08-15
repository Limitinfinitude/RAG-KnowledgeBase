# pages/page_four.py
"""
模型设置页面
"""
import _project_root  # noqa: F401

import streamlit as st
import utils.ui_utils
import utils.styles
from utils.api_config import load_api_config, save_api_config, update_config
from utils.web_system_settings import get_llm_preset_templates

# 加载样式
utils.ui_utils.load_custom_css()
utils.styles.load_all_styles()

st.markdown("# 模型设置")

# 初始化session_state
if "current_api_config" not in st.session_state:
    st.session_state.current_api_config = "DeepSeek"

# 加载配置
api_configs = load_api_config()

# 确保内置模板名在 MySQL 中齐全（load_system_settings 已归一化，此处兜底）
for name, default_config in get_llm_preset_templates().items():
    if name not in api_configs:
        api_configs[name] = default_config.copy()
        save_api_config(api_configs)

# 配置选择
st.markdown("### 选择API提供商")
config_names = list(api_configs.keys())
selected_config_name = st.selectbox(
    "当前使用的配置",
    config_names,
    index=config_names.index(st.session_state.current_api_config) if st.session_state.current_api_config in config_names else 0,
    key="api_config_selector"
)

st.session_state.current_api_config = selected_config_name
current_config = api_configs[selected_config_name]

st.markdown("---")

# 配置编辑
st.markdown("### 配置详情")

col1, col2 = st.columns(2)

with col1:
    base_url = st.text_input(
        "API Base URL",
        value=current_config.get("base_url", ""),
        help="API的基础URL地址",
        key=f"base_url_{selected_config_name}"
    )

with col2:
    api_key = st.text_input(
        "API Key",
        value=current_config.get("api_key", ""),
        type="password",
        help="API密钥（输入后会自动保存）",
        key=f"api_key_{selected_config_name}"
    )

model_name = st.text_input(
    "模型名称",
    value=current_config.get("model", ""),
    help="要使用的模型名称（如：deepseek-chat, gpt-3.5-turbo）",
    key=f"model_{selected_config_name}"
)

provider = st.selectbox(
    "提供商类型",
    ["deepseek", "openai", "custom"],
    index=["deepseek", "openai", "custom"].index(current_config.get("provider", "custom")),
    help="选择API提供商类型",
    key=f"provider_{selected_config_name}"
)

# 保存按钮
col_save, col_test = st.columns(2)

with col_save:
    if st.button("💾 保存配置", type="primary", use_container_width=True):
        api_configs[selected_config_name] = {
            "base_url": base_url,
            "api_key": api_key,
            "model": model_name,
            "provider": provider
        }
        save_api_config(api_configs)
        st.success("✅ 配置已保存！")
        st.rerun()

with col_test:
    if st.button("🧪 测试连接", use_container_width=True):
        if not api_key:
            st.warning("请先输入API Key")
        elif not base_url:
            st.warning("请先输入Base URL")
        elif not model_name:
            st.warning("请先输入模型名称")
        else:
            with st.spinner("测试连接中..."):
                try:
                    from services.llm_factory import build_chat_openai_explicit

                    test_llm = build_chat_openai_explicit(
                        model=model_name,
                        api_key=api_key,
                        base_url=base_url,
                        temperature=0,
                        timeout=10,
                    )
                    # 简单测试
                    response = test_llm.invoke("你好")
                    st.success(f"✅ 连接成功！\n\n回复：{response.content[:100]}")
                except Exception as e:
                    st.error(f"❌ 连接失败：{str(e)}")

st.markdown("---")

# 预设配置说明
st.markdown("### 预设配置说明")

with st.expander("📋 DeepSeek 配置", expanded=False):
    st.markdown("""
    **DeepSeek API 配置**：
    - Base URL: `https://api.deepseek.com`
    - 模型: `deepseek-chat`
    - 获取API Key: https://platform.deepseek.com/api_keys
    """)

with st.expander("📋 OpenAI 配置", expanded=False):
    st.markdown("""
    **OpenAI API 配置**：
    - Base URL: `https://api.openai.com/v1`
    - 模型: `gpt-3.5-turbo` 或 `gpt-4`
    - 获取API Key: https://platform.openai.com/api-keys
    """)

with st.expander("📋 自定义配置", expanded=False):
    st.markdown("""
    **自定义API配置**：
    - 可以配置任何兼容OpenAI格式的API
    - 支持本地部署的模型服务
    - 支持其他API提供商（如：通义千问、文心一言等）
    """)

# 应用配置到当前会话
st.markdown("---")
col_apply, col_back = st.columns(2)

with col_apply:
    if st.button("✅ 应用此配置", type="primary", use_container_width=True):
        st.session_state.current_api_config = selected_config_name
        st.success("配置已应用到当前会话！")
        st.info("💡 提示：配置会在下次调用LLM时生效")

with col_back:
    if st.button("🔙 返回智能问答", use_container_width=True):
        st.switch_page("pages/page_one.py")

