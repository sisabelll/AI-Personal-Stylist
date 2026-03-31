import os
from typing import Optional
import streamlit.components.v1 as components

_frontend = os.path.join(os.path.dirname(__file__), "frontend")
_component = components.declare_component("chat_status", path=_frontend)


def chat_status(label: str = "", visible: bool = True, key: Optional[str] = None):
    """
    Minimal animated status bar for the chat interface.
    Shows a shimmering line + uppercase label while the AI is working.
    Set visible=False (or call st.empty()) to hide it.
    """
    return _component(label=label, visible=visible, key=key, default=None)
