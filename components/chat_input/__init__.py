import os
from typing import Optional
import streamlit.components.v1 as components

_frontend = os.path.join(os.path.dirname(__file__), "frontend")
_component = components.declare_component("chat_input", path=_frontend)


def chat_input_custom(
    placeholder: str = "Ask your stylist…",
    mode: str = "inline",
    user_name: str = "",
    color_season: str = "",
    body_type: str = "",
    key: Optional[str] = None,
) -> Optional[str]:
    """
    Editorial chat input — returns the submitted text or None.
    mode: 'hero'   → first-load, centered layout with quick-start chips
          'inline' → compact bottom bar for ongoing conversation
    user_name, color_season, body_type populate the hero greeting dynamically.
    Deduplication must be handled on the Python side.
    """
    return _component(
        placeholder=placeholder,
        mode=mode,
        user_name=user_name,
        color_season=color_season,
        body_type=body_type,
        key=key,
        default=None,
    )
