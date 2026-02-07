import json
from core.config import Config
from core.schemas import OutfitRecommendation, OutfitCritique, WearPreference
from services.trends_retriever import TrendsRetriever, simple_rank, build_trend_context_pack
from services.client import OpenAIClient
from services.storage import StorageService 

def _safe_dump(x):
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return x

def _derive_context_terms(user_profile: dict, situational_signals: dict, outfit: OutfitRecommendation) -> list[str]:
    terms = []

    # From profile
    cs = user_profile.get("color_season") or user_profile.get("personal_color")
    be = user_profile.get("body_style_essence")
    if cs: terms.append(str(cs))
    if be: terms.append(str(be))

    # From situational signals
    fb = situational_signals.get("feedback") or {}
    fb = _safe_dump(fb)
    terms += (fb.get("make_more") or [])
    terms += (fb.get("make_less") or [])
    terms += (fb.get("expressed_likes") or [])
    terms += (fb.get("expressed_dislikes") or [])

    # From the outfit itself (cheap keywording)
    try:
        for opt in outfit.outfit_options[:1]:
            for it in opt.items:
                terms.append(it.category)
                terms.append(it.item_name)
    except Exception:
        pass

    # normalize to strings
    return [str(t) for t in terms if t and str(t).strip()]

class EditorAgent:
    def __init__(self, client: OpenAIClient, storage: StorageService = None):
        self.client = client
        self.storage = storage or StorageService()
        self.trends = TrendsRetriever(self.storage)

    def critique(
        self,
        outfit: OutfitRecommendation,
        user_profile: dict,
        situational_signals: dict
    ) -> OutfitCritique:
        fb = situational_signals.get("feedback") or {}
        fb = _safe_dump(fb)

        edit_mode = bool(situational_signals.get("edit_mode"))
        swap_out = fb.get("swap_out") or []
        swap_out = [s for s in swap_out if s]

        edit_scope = "single_swap" if (edit_mode and len(swap_out) <= 1) else "normal"

        # -------------------------
        # ✅ TREND PACK INJECTION
        # -------------------------
        wear_pref: WearPreference = (
            situational_signals.get("wear_preference")
            or (user_profile.get("preferences") or {}).get("wear_preference")
            or "unisex"
        )
        season = getattr(outfit, "season", None) or situational_signals.get("season") or "2026"

        # Pull some recent trends, rank locally, then compress
        all_trends = self.trends.fetch_recent(season=season, wear_pref=wear_pref, limit=50)
        context_terms = _derive_context_terms(user_profile, situational_signals, outfit)
        top = simple_rank(all_trends, context_terms=context_terms, top_k=8)
        trend_pack = build_trend_context_pack(top, max_cards=6)

        trend_context = situational_signals.get("trend_context") or {}
        trend_block = ""
        if trend_context and trend_context.get("selected_trends"):
            trend_block = f"""
            TREND CONTEXT (FOR SCORING)
            Use this to judge whether the outfit has a subtle, current signal (not costume-y).
            If outfit is missing any modern signal, you may request ONE trend-forward upgrade in the edit plan,
            but only within allowed_swap_categories.
            {json.dumps(trend_context, ensure_ascii=False)}
            """.strip()

        base_block = f"""
        You are a ruthless fashion editor.

        Return STRICT JSON matching OutfitCritique. No extra keys.

        CONTEXT
        - edit_mode: {edit_mode}
        - edit_scope: {edit_scope}
        - allowed_swap_categories: {json.dumps(swap_out, ensure_ascii=False)}

        TASTE BENCHMARKS:
        - 7/10: coherent but forgettable.
        - 9/10: one clear hero decision + restraint + finishing.

        CRITICAL RULES ABOUT HERO:
        - If edit_scope == "normal": If you cannot name a hero, verdict MUST be "revise" and score <= 7.
        - If edit_scope == "single_swap": Do NOT force a new hero. You may name the EXISTING hero (even if locked),
        OR say "hero unchanged" and focus critique on whether the swapped category improved taste.

        EDIT-MODE CONSTRAINTS (NON-NEGOTIABLE):
        - If edit_mode is true, your edit plan MUST ONLY include target_category values inside allowed_swap_categories.
        - Propose MAX 2 actions (but for single_swap prefer MAX 1).
        - Prefer the smallest possible changes.
        - Respect the user's color season and body essence.

        TREND CARDS (OPTIONAL GUIDANCE):
        Use at most 1-2 subtle trend touches to improve modernity and finish.
        Do NOT turn the outfit into a trend costume.
        {json.dumps(trend_pack, ensure_ascii=False)}

        USER PROFILE:
        {json.dumps({
        "color_season": user_profile.get("color_season") or user_profile.get("personal_color"),
        "body_essence": user_profile.get("body_style_essence"),
        "preferences": (user_profile.get("preferences") or {}),
        }, ensure_ascii=False)}

        SITUATIONAL SIGNALS:
        {json.dumps(situational_signals, ensure_ascii=False)}
        """.strip()

        system_prompt = "\n\n".join(
            [base_block, trend_block]
        ).strip()

        return self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": outfit.model_dump_json()},
            ],
            temperature=0.2,
            response_model=OutfitCritique,
        )