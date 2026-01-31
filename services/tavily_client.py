from __future__ import annotations

import os
from typing import Dict, List
from core.config import Config

import requests


class TavilyClient:
    """
    Batched Tavily Extract client.
    - POST https://api.tavily.com/extract
    - Authorization: Bearer <TAVILY_API_KEY>
    - Body: { "urls": [..], ... }

    Returns a mapping: {url: extracted_text}
    """

    def __init__(self):
        self.api_key = Config.TAVILY_API_KEY
        if not self.api_key:
            raise RuntimeError("Missing TAVILY_API_KEY")
        self.base_url = "https://api.tavily.com"

    def extract_batch(
        self,
        urls: List[str],
        *,
        extract_depth: str = "basic",   # "basic" or "advanced"
        format: str = "text",           # "text" or "markdown"
        timeout_s: float = 20.0,
        include_usage: bool = False,
    ) -> Dict[str, str]:
        if not urls:
            return {}

        endpoint = f"{self.base_url}/extract"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "urls": urls,
            "extract_depth": extract_depth,
            "format": format,
            "timeout": min(max(timeout_s, 1.0), 60.0),
            "include_usage": include_usage,
            "include_favicon": False,
            "include_images": False,
        }

        r = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            # Surface server message (super useful while debugging)
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise requests.HTTPError(f"{e} | Tavily response: {detail}") from e

        data = r.json()
        results = data.get("results") or []

        out: Dict[str, str] = {}
        for item in results:
            url = item.get("url")
            raw = item.get("raw_content")
            if isinstance(url, str):
                out[url] = (raw or "").strip()

        # Ensure every requested URL has a key (even if Tavily returned nothing)
        for u in urls:
            out.setdefault(u, "")

        return out
