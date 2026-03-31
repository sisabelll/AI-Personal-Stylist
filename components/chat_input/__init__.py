import os
from typing import Optional
import streamlit.components.v1 as components

_frontend = os.path.join(os.path.dirname(__file__), "frontend")
_component = components.declare_component("chat_input", path=_frontend)


def chat_input_custom(placeholder: str = "Ask your stylist…", key: Optional[str] = None) -> Optional[str]:
    """
    Editorial chat input — returns the submitted text or None.
    Deduplication must be handled on the Python side (component value persists
    in Streamlit session state until a new value is submitted).
    """
    return _component(placeholder=placeholder, key=key, default=None)
