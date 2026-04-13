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

        color_season = user_profile.get("color_season") or user_profile.get("personal_color")
        body_essence = user_profile.get("body_style_essence")
        color_guidelines = user_profile.get("color_guidelines") or {}

        # Build color rule summary for the hard-violation check
        color_rule_summary = ""
        if color_guidelines:
            sub_types = color_guidelines.get("sub_types") or {}
            all_prefer = list(dict.fromkeys(c for st in sub_types.values() for c in (st.get("prefer") or [])))
            all_avoid = list(dict.fromkeys(c for st in sub_types.values() for c in (st.get("avoid") or [])))
            color_rule_summary = (
                f"{color_season} — {color_guidelines.get('overall_type', '')}. "
                f"Preferred: {', '.join(all_prefer[:10])}. "
                f"Avoid: {', '.join(all_avoid[:10])}."
            )

        formality_level = (situational_signals.get("style_interpretation") or {}).get("formality_level", "medium")
        event_type = situational_signals.get("event_type", "")

        system_prompt = f"""
        You are a structural outfit checker — NOT a taste critic.
        Your ONLY job is to catch hard violations that the stylist cannot self-correct.
        If there are no hard violations, you MUST return verdict="accept".
        Do NOT revise outfits because they are "safe" or "forgettable" — that is the stylist's job.

        Return STRICT JSON matching OutfitCritique. No extra keys.

        CONTEXT
        - edit_mode: {edit_mode}
        - edit_scope: {edit_scope}
        - allowed_swap_categories: {json.dumps(swap_out, ensure_ascii=False)}
        - formality_level: {formality_level}
        - event_type: {event_type}

        HARD VIOLATION CHECKLIST (the ONLY reasons to return verdict="revise"):

        1. PHYSICS — OnePiece coexists with Top or Bottom.
           Fix: remove the conflicting separates.

        2. FORMALITY MISMATCH — A clearly wrong item for the event.
           Examples of actual violations: athletic sneakers at a wedding, a mini skirt at a formal interview.
           NOT a violation: dark jeans at a casual dinner, a blazer at brunch.
           Only flag this if the mismatch is stark and would embarrass a real person.

        3. EGREGIOUS COLOR SEASON BREAK — A single item that is the direct opposite of the user's season.
           {color_rule_summary or f"Season: {color_season}"}
           Examples of actual violations: neon orange on Summer Cool, icy pastels as main color on Deep Winter.
           NOT a violation: a borderline warm neutral, a subtle pattern, an item in the right value range.
           Only flag items that are clearly and obviously wrong — when in doubt, accept.

        4. EXPLICIT USER CONSTRAINT VIOLATED — User said to remove or avoid a specific item/category and it still appears.

        5. EDIT MODE ONLY — A locked category changed when it should not have.
           Only applies when edit_mode=true. Check: allowed_swap_categories list.

        SCORING:
        - If no hard violation: score=9, verdict="accept", main_issue="none", plan with no actions.
        - If 1 hard violation: score=5, verdict="revise", name the violation in main_issue, 1 targeted action.
        - If 2+ hard violations: score=4, verdict="revise", fix the most critical one only (max 1 action).

        HERO: Identify the most interesting or dominant piece and name it. This is informational only —
        do NOT trigger a revision just because you cannot find a hero.

        USER PROFILE:
        {json.dumps({
        "color_season": color_season,
        "body_essence": body_essence,
        }, ensure_ascii=False)}
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