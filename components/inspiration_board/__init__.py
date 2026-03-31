import base64
import os
from typing import Optional
import streamlit.components.v1 as components

# Vanilla JS component — no build step required.
_frontend = os.path.join(os.path.dirname(__file__), "frontend")
_component = components.declare_component("inspiration_board", path=_frontend)


def inspiration_board(items: list, key: Optional[str] = None) -> Optional[dict]:
    """
    Render the Pinterest-style inspiration board.

    Each item dict should have: id, image_bytes (bytes), page_url, caption, tags, source_name.
    Returns {'action': 'save'|'hide'|'refresh', 'id': str|None} or None.
    """
    component_items = []
    for it in items:
        img_bytes: Optional[bytes] = it.get("image_bytes")
        if img_bytes:
            b64 = base64.b64encode(img_bytes).decode()
            src = f"data:image/jpeg;base64,{b64}"
        else:
            src = it.get("image_url") or ""

        component_items.append({
            "id": it["id"],
            "src": src,
            "page_url": it.get("page_url"),
            "caption": it.get("caption"),
            "tags": it.get("tags") or [],
            "source_name": it.get("source_name"),
        })

    return _component(items=component_items, key=key, default=None)
