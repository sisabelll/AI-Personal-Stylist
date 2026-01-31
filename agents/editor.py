import json
from core.config import Config
from core.schemas import OutfitRecommendation, OutfitCritique
from services.client import OpenAIClient

class EditorAgent:
    def __init__(self, client: OpenAIClient):
        self.client = client

    def critique(self, outfit: OutfitRecommendation, user_profile: dict, situational_signals: dict) -> OutfitCritique:
        fb = situational_signals.get("feedback") or {}
        if hasattr(fb, "model_dump"):
            fb = fb.model_dump()

        edit_mode = bool(situational_signals.get("edit_mode"))
        swap_out = fb.get("swap_out") or []
        # canonicalize if your pipeline sometimes sends lowercase
        swap_out = [s for s in swap_out if s]

        edit_scope = "single_swap" if (edit_mode and len(swap_out) <= 1) else "normal"

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
        - If mid-calf boots/Uggs are involved, require a hem/proportion strategy (only if Shoes or Bottom are allowed swaps).

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
    
# class OutfitCritic:
#     def __init__(self, client):
#         self.client = client

#     def evaluate(self, program, recommendation: dict, current_outfit=None) -> dict:
#         prompt = f"""
#         You are an editorial fashion director. Be decisive and picky.
#         Your job is to upgrade taste: cohesion, proportion, fabric realism, and modernity.

#         STYLE PROGRAM:
#         {program.model_dump()}

#         CURRENT_OUTFIT_LOCK (if any):
#         {json.dumps(current_outfit or [], indent=2)}

#         OUTFIT RECOMMENDATION JSON:
#         {json.dumps(recommendation, indent=2)}

#         Score each outfit_option (0-5 each):
#         cohesion, proportion, fabric_quality, formality_alignment, palette_discipline,
#         trend_selectivity, styling_finesse, non_generic

#         Then:
#         - choose best_option_name
#         - verdict: pass if total>=threshold and minima met; else revise if fixable with <=2 swaps; else fail
#         - top_issues: max 3, with concrete fixes
#         - short_fix_brief: <= 80 tokens
#         - surgical_edit_plan: max 2 swaps. If editing, DO NOT touch locked items.

#         Return STRICT JSON with keys:
#         best_option_name, verdict, total_score, category_scores, top_issues, short_fix_brief, surgical_edit_plan
#         """
#         return self.client.call_api(
#             model=Config.OPENAI_MODEL_SMART,
#             messages=[{"role": "system", "content": prompt}],
#             temperature=0.2,
#         )

class OutfitSurgeon:
    def __init__(self, client):
        self.client = client

    def revise(self, program, recommendation: dict, critique: dict, current_outfit=None, allowed_swap_categories=None) -> OutfitRecommendation:
        allowed_swap_categories = allowed_swap_categories or []

        prompt = f"""
        You are an outfit surgeon. Apply minimal edits for maximum taste.

        OUTPUT: Return UPDATED OutfitRecommendation JSON only. No extra text.

        ALLOWED SWAPS (ONLY these categories may change): {json.dumps(allowed_swap_categories, ensure_ascii=False)}
        - If a category is NOT in ALLOWED SWAPS, you MUST copy item_name + search_query verbatim from LOCKED CURRENT OUTFIT.

        STYLE PROGRAM:
        {json.dumps(program.model_dump(), ensure_ascii=False, indent=2)}

        CRITIQUE:
        {json.dumps(critique, ensure_ascii=False, indent=2)}

        LOCKED CURRENT OUTFIT (if any):
        {json.dumps(current_outfit or [], ensure_ascii=False, indent=2)}

        CURRENT RECOMMENDATION:
        {json.dumps(recommendation, ensure_ascii=False, indent=2)}

        RULES
        - Preserve id/occasion/season fields.
        - Keep outfit_options structure. Prefer editing ONLY option 0.
        - MAX swaps:
        - If len(ALLOWED SWAPS)==1: MAX 1 swap total.
        - Else: MAX 2 swaps total.
        - Improve: cohesion, fabric realism, modernity ONLY within allowed swaps.

        Return UPDATED OutfitRecommendation JSON only.
        """.strip()

        return self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.2,
            response_model=OutfitRecommendation,
        )
