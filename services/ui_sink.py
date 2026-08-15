from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class RetrievalUISink:
    """检索过程中的 UI 反馈（Streamlit 页面传入 st.caption 等；单测可用空实现）。"""

    caption: Callable[[str], None]
    warning: Callable[[str], None]
    error: Callable[[str], None]
    spinner: Callable[[str], Any]

    @classmethod
    def noop(cls) -> "RetrievalUISink":
        return cls(
            caption=lambda *_: None,
            warning=lambda *_: None,
            error=lambda *_: None,
            spinner=lambda _text: nullcontext(),
        )

    @classmethod
    def streamlit(cls, st_module: Any) -> "RetrievalUISink":
        return cls(
            caption=st_module.caption,
            warning=st_module.warning,
            error=st_module.error,
            spinner=st_module.spinner,
        )
