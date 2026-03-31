from __future__ import annotations
import re, unicodedata
from hashlib import sha1
from typing import Dict, Iterable, List

_GENERIC_WORDS = {"trend", "trends", "aesthetic", "core", "style", "styling"}

COLOR_LABEL_TO_KEY = {
    "Spring Warm": "spring_warm",
    "Summer Cool": "summer_cool",
    "Autumn Warm": "autumn_warm",
    "Winter Cool": "winter_cool",
}

COLOR_KEY_TO_LABEL = {v: k for k, v in COLOR_LABEL_TO_KEY.items()}

def normalize_color_season_label(label: str) -> str:
    """
    Converts UI / profile label → schema-safe key.
    Defaults defensively.
    """
    return COLOR_LABEL_TO_KEY.get(label, "summer_cool")


def denormalize_color_season_key(key: str) -> str:
    """
    Converts schema-safe key → human-readable label.
    """
    return COLOR_KEY_TO_LABEL.get(key, key)

def normalize_trend_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[''\"`]", "", s)
    s = re.sub(r"[^a-z0-9\s\-]", " ", s)
    s = re.sub(r"[\-_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split(" ") if t and t not in _GENERIC_WORDS]
    return " ".join(tokens).strip()

def apply_alias(canonical: str, alias_map: Dict[str, str]) -> str:
    return alias_map.get(canonical, canonical)

def compute_trend_key(season: str, trend_type: str, canonical: str) -> str:
    base = f"{season.lower().strip()}:{trend_type.lower().strip()}:{canonical}"
    digest = sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"{base}:{digest}"

def dedupe_list(items: Iterable[str], cap: int) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if not x:
            continue
        k = normalize_trend_name(str(x))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(str(x).strip())
        if len(out) >= cap:
            break
    return out
