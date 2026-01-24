import json
from core.config import Config

class OutfitCritic:
    def __init__(self, client):
        self.client = client

    def evaluate(self, program, recommendation: dict, current_outfit=None) -> dict:
        prompt = f"""
        You are an editorial fashion director. Be decisive and picky.
        Your job is to upgrade taste: cohesion, proportion, fabric realism, and modernity.

        STYLE PROGRAM:
        {program.model_dump()}

        CURRENT_OUTFIT_LOCK (if any):
        {json.dumps(current_outfit or [], indent=2)}

        OUTFIT RECOMMENDATION JSON:
        {json.dumps(recommendation, indent=2)}

        Score each outfit_option (0-5 each):
        cohesion, proportion, fabric_quality, formality_alignment, palette_discipline,
        trend_selectivity, styling_finesse, non_generic

        Then:
        - choose best_option_name
        - verdict: pass if total>=threshold and minima met; else revise if fixable with <=2 swaps; else fail
        - top_issues: max 3, with concrete fixes
        - short_fix_brief: <= 80 tokens
        - surgical_edit_plan: max 2 swaps. If editing, DO NOT touch locked items.

        Return STRICT JSON with keys:
        best_option_name, verdict, total_score, category_scores, top_issues, short_fix_brief, surgical_edit_plan
        """
        return self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.2,
        )

class OutfitSurgeon:
    def __init__(self, client):
        self.client = client

    def revise(self, program, recommendation: dict, critique: dict, current_outfit=None) -> dict:
        prompt = f"""
        You are an outfit surgeon. Apply minimal edits for maximum taste.
        MAX 2 swaps total. Keep everything else the same.

        STYLE PROGRAM:
        {program.model_dump()}

        CRITIQUE:
        {json.dumps(critique, indent=2)}

        LOCKED CURRENT OUTFIT (if any):
        {json.dumps(current_outfit or [], indent=2)}

        CURRENT RECOMMENDATION:
        {json.dumps(recommendation, indent=2)}

        Rules:
        - Preserve id/occasion/season fields.
        - Keep outfit_options structure. Prefer editing ONLY the best option.
        - If editing: copy locked items' item_name + search_query verbatim.
        - Improve: modernity (shoe shape, proportions), fabric realism, cohesion, and reduce genericness.

        Return UPDATED OutfitRecommendation JSON only.
        """
        return self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[{"role": "system", "content": prompt}],
            temperature=0.35,
        )
