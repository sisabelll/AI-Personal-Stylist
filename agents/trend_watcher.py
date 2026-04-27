from __future__ import annotations
from typing import Tuple
import json
from typing import Dict, List, Any
from urllib.parse import urlencode
import requests
from collections import defaultdict
from urllib.parse import urlparse

from services.storage import StorageService
from services.trends_store import TrendsStore
from services.client import OpenAIClient
from services.tavily_client import TavilyClient
from services.usage_guard import UsageGuard

_QUALITY_ORDER = {"high": 0, "medium": 1, "low": 2}

from core.config import Config
from core.schemas import TrendCard, TrendCardListLLM, SourceTrendNotes, SourceTrendNotesLLM, WearPreference
from core.trends import normalize_trend_name, apply_alias, compute_trend_key
from services.trend_source_cache import TrendSourceCacheStore, canonicalize_url, hash_text
from core.trend_limits import TrendRunLimits

# =========================
# SAFEGUARDS (hard caps)
# =========================
LIMITS = TrendRunLimits()
MAX_EXTRACTS_PER_RUN = LIMITS.max_extracts
MAX_PER_DOMAIN = LIMITS.max_per_domain
CACHE_TTL_DAYS = 30

# Paywall / stub heuristics
MIN_CONTENT_CHARS = 900
PAYWALL_MARKERS = [
    "subscribe", "subscription", "sign in to continue", "to continue reading",
    "enable javascript", "you have reached your limit", "register to read",
    "already a subscriber", "log in", "start your free trial"
]

class GoogleCSEClient:
    def __init__(self):
        self.api_key = Config.GOOGLE_API_KEY
        self.cse_id = Config.GOOGLE_CSE_ID
        if not self.api_key or not self.cse_id:
            raise RuntimeError("Missing GOOGLE_API_KEY or GOOGLE_CSE_ID")

    def search(self, q: str, num: int = 5) -> List[Dict[str, Any]]:
        params = {"key": self.api_key, "cx": self.cse_id, "q": q, "num": num}
        url = "https://www.googleapis.com/customsearch/v1?" + urlencode(params)
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        out = []
        for it in items:
            out.append({
                "title": it.get("title"),
                "link": it.get("link"),
                "snippet": it.get("snippet"),
                "displayLink": it.get("displayLink"),
            })
        return out
    
def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def looks_paywalled_or_stub(text: str) -> bool:
    if not text:
        return True
    t = text.strip().lower()
    if len(t) < MIN_CONTENT_CHARS:
        return True
    # If a lot of paywall markers appear, likely unusable
    hits = sum(1 for m in PAYWALL_MARKERS if m in t)
    return hits >= 2

def infer_wear_scope(
    *,
    url: str,
    title: str,
    snippet: str,
) -> WearPreference:
    text = f"{title} {snippet}".lower()

    # Explicit signals
    if any(k in text for k in ["menswear", "men's", "mens fashion", "pitti uomo"]):
        return "menswear"
    if any(k in text for k in ["womenswear", "women's", "womens fashion"]):
        return "womenswear"

    # Vogue / runway default bias
    if "vogue" in url and "mens" not in text:
        return "womenswear"

    # Streetwear defaults to unisex unless explicitly mens
    if any(k in text for k in ["streetwear", "hypebeast"]):
        return "unisex"

    # Retail editorials (Net-a-Porter, etc.)
    if any(k in url for k in ["net-a-porter", "matchesfashion"]):
        return "womenswear"

    return "unisex"

WearPref = WearPreference  # alias

def notes_for_pref(
    notes_with_scope: List[Tuple[SourceTrendNotes, WearPreference]],
    pref: WearPreference,
) -> List[SourceTrendNotes]:
    """
    womenswear: womenswear + unisex sources
    menswear:   menswear + unisex sources
    unisex:     everything (or change to only {'unisex'} if you prefer)
    """
    if pref == "unisex":
        allowed = {"womenswear", "menswear", "unisex"}
    else:
        allowed = {pref, "unisex"}

    return [n for (n, scope) in notes_with_scope if scope in allowed]

def dedupe_cards_by_key(trends_store: TrendsStore, cards: List[TrendCard]) -> List[TrendCard]:
    """
    Prevent Postgres 21000 by ensuring only one row per trend_key in a single upsert payload.
    If duplicates occur in the same run, merge them.
    """
    by_key: Dict[str, TrendCard] = {}
    for c in cards:
        if c.trend_key in by_key:
            by_key[c.trend_key] = trends_store.merge(by_key[c.trend_key], c)
        else:
            by_key[c.trend_key] = c
    return list(by_key.values())

def build_rules_pack(style_rules: dict) -> dict:
    ess = style_rules.get("body_style_essence_theory", {})
    css = style_rules.get("personal_color_theory", {})
    aes = style_rules.get("aesthetic_style_summary", {})

    color_pack = {}
    for season_name, season_data in css.items():
        sub_types = season_data.get("sub_types", {}) or {}
        color_pack[season_name] = {
            "overall_type": season_data.get("overall_type"),
            "main_characteristic": season_data.get("main_characteristic"),
            "sub_types": {
                sub_key: {
                    "name": sub_val.get("name"),
                    "dominant_feature": sub_val.get("dominant_feature"),
                    "prefer": sub_val.get("prefer", []),
                    "avoid": sub_val.get("avoid", []),
                    "styling_strategy": sub_val.get("styling_strategy"),
                    "fabric_pattern_tips": sub_val.get("fabric_pattern_tips"),
                }
                for sub_key, sub_val in sub_types.items()
            },
        }

    return {
        "essences": {
            k: {
                "styling_principle": v.get("styling_principle"),
                "silhouette_intent": v.get("silhouette_intent"),
                "preferred_elements": v.get("preferred_elements", {}),
                "avoid_elements": v.get("avoid_elements", {}),
            }
            for k, v in ess.items()
        },
        "color_theory": color_pack,
        "aesthetics": {k: {"keywords": v.get("keywords", []), "vibe": v.get("vibe")} for k, v in aes.items()},
    }


def normalize_and_key(card: TrendCard, *, alias_map: Dict[str, str], season: str) -> TrendCard:
    trend_name = (card.trend_name or "").strip()
    canonical = normalize_trend_name(card.canonical_name or trend_name)
    canonical = apply_alias(canonical, alias_map)
    trend_type = card.trend_type or "micro"
    key = compute_trend_key(season, trend_type, canonical)
    return card.model_copy(update={
        "season": season,
        "trend_name": trend_name,
        "canonical_name": canonical,
        "trend_key": key,
    })

def search_candidate_urls(google: GoogleCSEClient, queries: List[str], per_query: int = 8) -> List[Dict[str, str]]:
    """
    Returns list of {url,title,snippet,publisher} results (deduped by canonical URL).
    """
    seen = set()
    results: List[Dict[str, str]] = []
    for q in queries:
        items = google.search(q, num=per_query)
        for it in items:
            url = it.get("link") or ""
            if not url:
                continue
            cu = canonicalize_url(url)
            if cu in seen:
                continue
            seen.add(cu)
            results.append({
                "url": cu,
                "title": it.get("title") or "",
                "snippet": it.get("snippet") or "",
                "publisher": it.get("displayLink") or domain_of(cu),
                "wear_scope": infer_wear_scope(
                    url=cu,
                    title=it.get("title") or "",
                    snippet=it.get("snippet") or "",
                ),
            })
    return results

def filter_by_wear_preference(
    candidates: List[dict],
    user_pref: WearPreference,
) -> List[dict]:
    if user_pref == "unisex":
        return candidates

    allowed = {user_pref, "unisex"}
    return [c for c in candidates if c.get("wear_scope") in allowed]

_UNEXTRACTABLE_DOMAINS = {"youtube.com", "youtu.be", "reddit.com", "tiktok.com", "instagram.com", "twitter.com", "x.com"}

def choose_urls_to_extract(storage: StorageService, candidates: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Applies:
    - filters domains Tavily can't extract (video/social)
    - 30 day cache TTL
    - max per domain
    - max extracts per run
    """
    cache = TrendSourceCacheStore(storage)

    candidates = [c for c in candidates if domain_of(c.get("url", "")).replace("www.", "") not in _UNEXTRACTABLE_DOMAINS]
    urls = [c["url"] for c in candidates if c.get("url")]
    decisions = cache.filter_urls_to_fetch(urls, ttl_days=CACHE_TTL_DAYS)
    should_fetch = {d.url for d in decisions if d.should_fetch}

    by_domain = defaultdict(int)
    chosen: List[Dict[str, str]] = []

    for c in candidates:
        url = c["url"]
        if url not in should_fetch:
            continue
        dom = domain_of(url)
        if by_domain[dom] >= MAX_PER_DOMAIN:
            continue
        by_domain[dom] += 1
        chosen.append(c)
        if len(chosen) >= MAX_EXTRACTS_PER_RUN:
            break

    return chosen

def sanitize_source_notes_llm(data: Any) -> Dict[str, Any]:
    """
    Coerce common LLM type mistakes into schema-friendly values.
    Keep it small and deterministic.
    """
    if not isinstance(data, dict):
        return {"trend_phrases": [], "signals": [], "in_out": None, "quality": "low"}

    out: Dict[str, Any] = {}

    # trend_phrases
    tp = data.get("trend_phrases")
    if isinstance(tp, list):
        out["trend_phrases"] = [str(x).strip() for x in tp if str(x).strip()]
    elif isinstance(tp, str):
        out["trend_phrases"] = [s.strip() for s in tp.split(";") if s.strip()]
    else:
        out["trend_phrases"] = []

    # signals
    sig = data.get("signals")
    if isinstance(sig, list):
        out["signals"] = [str(x).strip() for x in sig if str(x).strip()]
    elif isinstance(sig, str):
        out["signals"] = [s.strip() for s in sig.split("\n") if s.strip()]
    else:
        out["signals"] = []

    # in_out must be str or None
    io = data.get("in_out")
    if io is None:
        out["in_out"] = None
    elif isinstance(io, str):
        s = io.strip()
        out["in_out"] = s if s else None
    else:
        # if dict/list/etc, drop it
        out["in_out"] = None

    # quality must be one of high/medium/low
    q = data.get("quality")
    if isinstance(q, str):
        ql = q.strip().lower()
        if ql in ("high", "medium", "low"):
            out["quality"] = ql
        else:
            # heuristic: if it returned a sentence, pick medium unless content is tiny
            out["quality"] = "medium"
    else:
        out["quality"] = "medium"

    # hard fallback: if almost empty, mark low
    if len(out["signals"]) < 2 and len(out["trend_phrases"]) < 2:
        out["quality"] = "low"

    return out


def compress_source_to_notes(
    llm: OpenAIClient,
    *,
    url: str,
    publisher: str,
    title: str,
    snippet: str,
    content: str,
) -> SourceTrendNotes:
    content_trim = content[:LIMITS.max_article_chars]


    system = (
        "You are a fashion editor. Extract only concrete trend signals from the article.\n"
        "Return ONE JSON object with EXACTLY these keys and types:\n"
        '{ "trend_phrases": string[], "signals": string[], "in_out": string|null, "quality": "high"|"medium"|"low" }\n'
        "Rules:\n"
        "- trend_phrases: 3-12 short phrases.\n"
        "- signals: 4-12 bullets; must be concrete (items/materials/silhouettes/styling moves).\n"
        "- in_out: only if the article explicitly says what is in/out; otherwise null.\n"
        "- quality MUST be exactly one of: high, medium, low.\n"
        "- Do not add any other keys.\n"
    )

    user = {
        "title": title,
        "snippet": snippet,
        "article_text": content_trim,
        "constraints": {
            "trend_phrases": "3-12",
            "signals": "4-12 bullets",
            "in_out": "only if explicitly stated",
        },
    }

    raw = llm.call_api(
        model=Config.OPENAI_MODEL_FAST,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ],
        temperature=0.2,
        max_tokens=900,
        json_mode=True,
    )

    data = json.loads(raw) if isinstance(raw, str) else raw
    data = sanitize_source_notes_llm(data)
    llm_notes = SourceTrendNotesLLM.model_validate(data)

    return SourceTrendNotes(
        url=url,
        publisher=publisher,
        title=title,
        trend_phrases=llm_notes.trend_phrases,
        signals=llm_notes.signals,
        in_out=llm_notes.in_out,
        quality=llm_notes.quality,
    )

def coerce_trendcardlist_payload(obj: Any) -> Any:
    """
    Accepts a few common LLM shapes and converts to {"cards": [...]}.
    """
    if not isinstance(obj, dict):
        return obj

    # correct shape
    if "cards" in obj and isinstance(obj["cards"], list):
        return obj

    # wrapped by schema name
    if "TrendCardList" in obj and isinstance(obj["TrendCardList"], list):
        return {"cards": obj["TrendCardList"]}

    # sometimes returns {"output": {"cards": [...]}}
    if "output" in obj and isinstance(obj["output"], dict) and "cards" in obj["output"]:
        return {"cards": obj["output"]["cards"]}

    return obj


def build_discovery_queries(season: str, wear_pref: WearPreference) -> List[str]:
    """
    Returns search queries tuned to the season label and wear preference.
    Prioritizes editorial/trade sources that are typically not paywalled.
    """
    gender = "menswear" if wear_pref == "menswear" else "womenswear"
    queries = [
        f"fashion trends {season} {gender}",
        f"site:vogue.com {season} fashion trends",
        f"site:whowhatwear.com {season} fashion trends",
        f"Lyst Index {season} trend report",
        f"Harper's Bazaar {season} fashion trends {gender}",
        f"Net-a-Porter editorial {season} {gender} trends",
        f"site:refinery29.com {season} fashion trends",
    ]
    if wear_pref in ("menswear", "unisex"):
        queries.append(f"site:hypebeast.com {season} fashion trends")
    return queries


def run(
    cadence: str = "biweekly",
    season: str = "2026",
    wear_pref: WearPreference = "womenswear",
    urls: List[str] | None = None,
) -> None:
    storage = StorageService()
    usage = UsageGuard(storage, daily_budget_usd=0.75)
    trends_store = TrendsStore(storage)
    cache_store = TrendSourceCacheStore(storage)

    google = GoogleCSEClient()
    tavily = TavilyClient()
    llm = OpenAIClient()

    alias_map = trends_store.load_alias_map()

    # --------
    # DISCOVERY
    # --------
    queries = build_discovery_queries(season, wear_pref)

    if urls:
        candidates = [{"url": u, "title": "", "snippet": "", "publisher": "", "wear_scope": wear_pref} for u in urls]
    else:
        candidates = search_candidate_urls(google, queries, per_query=8)

    candidates = filter_by_wear_preference(candidates, wear_pref)

    if urls:
        chosen = candidates
    else:
        chosen = choose_urls_to_extract(storage, candidates)
    print(
        f"TrendWatcher: candidates={len(candidates)} chosen_for_extract={len(chosen)} "
        f"(cap={MAX_EXTRACTS_PER_RUN}, ttl_days={CACHE_TTL_DAYS}, per_domain={MAX_PER_DOMAIN}, wear={wear_pref})"
    )

    if not chosen:
        print("⚠️ TrendWatcher: Nothing to extract after cache/domain caps. Exiting.")
        return

    # --------
    # BATCH EXTRACT
    # --------
    chosen_urls = [c["url"] for c in chosen]
    raw_map = tavily.extract_batch(chosen_urls, extract_depth="basic", format="text")

    # Pre-load any notes already stored for these URLs so we can skip LLM
    # recompression when the article content hasn't changed.
    cached_notes_map = cache_store.load_cached_notes(chosen_urls)

    # --------
    # STAGE 1: compress to notes (reuse cached notes when content unchanged)
    # --------
    notes_with_scope: List[tuple[SourceTrendNotes, str]] = []

    for c in chosen:
        url = c["url"]
        title = c.get("title", "") or ""
        snippet = c.get("snippet", "") or ""
        publisher = c.get("publisher", "") or domain_of(url)
        scope: WearPreference = c.get("wear_scope") or "unisex"

        raw = (raw_map.get(url) or "").strip()
        new_hash = hash_text(raw) if raw else None
        cached = cached_notes_map.get(url)

        # Reuse cached notes when content hash matches — skip LLM call entirely.
        if cached and cached.get("notes_json") and cached.get("content_hash") == new_hash:
            try:
                n = SourceTrendNotes.model_validate(cached["notes_json"])
                notes_with_scope.append((n, scope))
                print(f"♻️ Reused cached notes ({scope}): {publisher} — {url}")
                continue
            except Exception:
                pass  # fall through to re-compress

        if looks_paywalled_or_stub(raw):
            print(f"⚠️ Skip (paywall/stub): {url}")
            continue

        try:
            n = compress_source_to_notes(
                llm,
                url=url,
                publisher=publisher,
                title=title,
                snippet=snippet,
                content=raw,
            )

            if (len(n.signals or []) < 3) and (len(n.trend_phrases or []) < 3):
                print(f"⚠️ Skip (low-signal): {url}")
                continue

            notes_with_scope.append((n, scope))
            cache_store.upsert_fetched(url=url, title=title, content=raw, notes_json=n.model_dump())
            print(f"✅ Notes ({scope}): {publisher} — {url}")

        except Exception as e:
            print(f"❌ Stage1 compress failed for {url}: {e}")
            continue

    if not notes_with_scope:
        print("⚠️ TrendWatcher: No usable sources extracted. Exiting without DB updates.")
        return
    
    ESTIMATED_STAGE2_COST = 0.15  # conservative

    if not usage.can_spend(ESTIMATED_STAGE2_COST):
        print("⚠️ Budget guard: skipping Stage 2 synthesis")
        return

    # --------
    # STAGE 2: synthesize TrendCards
    # --------
    system = (
        "You are a luxury fashion trend analyst.\n"
        "Using ONLY the provided source notes, produce micro-to-mid trends as TrendCards.\n"
        "These must be actionable styling moves (items/materials/silhouettes/styling techniques).\n"
        "Do NOT output macro aesthetics like Minimalist/Boho/Y2K as trends.\n"
        "Every card.sources must ONLY contain URLs that appear in source_notes[].url.\n"
        "Keep it compact:\n"
        "- signals: 4-7\n"
        "- keywords: 5-10\n"
        "- what_to_borrow: 2-4\n"
        "- avoid: 1-3\n"
        "- sources: 1-2\n"
        "- essence_overrides/color_overrides should usually be empty lists unless clearly supported.\n"
        "Return valid JSON only.\n"
    )

    # Only synthesize for the requested wear_pref — synthesizing all 3 triples cost
    # with no benefit when the app only serves one segment at a time.
    counts_by_pref = {
        "womenswear": 7,
        "menswear": 5,
        "unisex": 6,
    }

    for pref in [wear_pref]:
        scoped_notes = notes_for_pref(notes_with_scope, pref)
        # High-quality sources first so the LLM synthesizes from the strongest signals.
        scoped_notes.sort(key=lambda n: _QUALITY_ORDER.get(n.quality, 1))

        print(f"\n🧵 Stage2: wear_pref={pref} scoped_notes={len(scoped_notes)}")
        if len(scoped_notes) < 2:
            print(f"⚠️ Not enough notes for {pref}, skipping.")
            continue

        user = {
            "season": season,
            "cadence": cadence,
            "wear_preference": pref,
            "source_notes": [n.model_dump() for n in scoped_notes],
            "count": counts_by_pref[pref],
            "trend_type": "micro",
        }

        draft = llm.structured(
            model=Config.OPENAI_MODEL_FAST,
            system=system + f"\nProduce exactly {counts_by_pref[pref]} cards.\n",
            user=user,
            response_model=TrendCardListLLM,
            temperature=0.35,
            max_tokens=2500,
        )

        prepared: List[TrendCard] = []
        for c_llm in draft.cards:
            if not (c_llm.trend_name or "").strip():
                print(f"⚠️ Skip (empty trend_name): {c_llm}")
                continue

            c_full = TrendCard(
                trend_key="__tmp__",
                season=season,
                canonical_name="__tmp__",

                trend_name=c_llm.trend_name,
                trend_type=c_llm.trend_type,
                wear_scope=pref,  # force to this branch

                signals=c_llm.signals,
                keywords=c_llm.keywords,
                what_to_borrow=c_llm.what_to_borrow,
                avoid=c_llm.avoid,
                confidence=float(c_llm.confidence) / 5.0,
                shelf_life_weeks=c_llm.shelf_life_weeks,
                sources=c_llm.sources,
                essence_overrides=c_llm.essence_overrides,
                color_overrides=c_llm.color_overrides,
            )

            c_full = normalize_and_key(c_full, alias_map=alias_map, season=season)
            prepared.append(c_full)

        # ✅ Dedupe within this branch (prevents Postgres 21000)
        prepared = dedupe_cards_by_key(trends_store, prepared)

        existing = trends_store.fetch_by_keys([c.trend_key for c in prepared])

        merged: List[TrendCard] = []
        for c in prepared:
            ex = existing.get(c.trend_key)
            merged.append(trends_store.merge(ex, c) if ex else c)

        # extra safety
        merged = dedupe_cards_by_key(trends_store, merged)

        trends_store.upsert(merged)
        print(f"✅ TrendWatcher: upserted {len(merged)} cards for season={season} cadence={cadence}")
        usage.record_spend(ESTIMATED_STAGE2_COST)
    
if __name__ == "__main__":
    storage = StorageService()
    usage = UsageGuard(storage, daily_budget_usd=0.75)  # ~ $22/month max
    run(
        cadence="biweekly",
        season="2026",
        wear_pref="womenswear",
        # urls=["https://www.marieclaire.com/fashion/fashion-trends-2026/"]
    )
