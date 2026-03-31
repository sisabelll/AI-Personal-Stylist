import json
from core.config import Config
from core.schemas import OutfitRecommendation, OutfitCritique
from services.client import OpenAIClient


def _safe_dump(x):
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return x


class EditorAgent:
    def __init__(self, client: OpenAIClient):
        self.client = client

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

        # Reuse trend context already fetched and ranked by the manager — no extra DB call.
        trend_context = situational_signals.get("trend_context") or {}

        system_prompt = f"""
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
        {json.dumps(trend_context, ensure_ascii=False)}

        USER PROFILE:
        {json.dumps({
        "color_season": user_profile.get("color_season") or user_profile.get("personal_color"),
        "body_essence": user_profile.get("body_style_essence"),
        "preferences": (user_profile.get("preferences") or {}),
        }, ensure_ascii=False)}

        SITUATIONAL SIGNALS:
        {json.dumps(situational_signals, ensure_ascii=False)}
        """.strip()

        return self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": outfit.model_dump_json()},
            ],
            temperature=0.2,
            response_model=OutfitCritique,
        )