from core.config import Config
from core.schemas import RefinementAnalysis
import json

class RefinementAgent:
    def __init__(self, client):
        self.client = client

    def analyze_feedback(self, current_outfit: dict, user_input: str):
        """
        Translates raw user feedback into structured style adjustments.
        """
        system_prompt = """
        You are an expert fashion interpreter.
        Your goal is to translate user feedback on an outfit into structured editing instructions.
        
        # INPUT DATA
        1. Current Outfit Context (JSON)
        2. User Feedback (Natural Language)
        
        # YOUR TASK
        Analyze the user's intent and categorize it into the schema:
        - make_more: Vibe shifts (e.g. "make it darker", "more casual").
        - make_less: Vibe reductions (e.g. "too formal", "less colorful").
        - swap_out: Specific items to remove/change (e.g. "I hate the boots", "Can I wear sneakers instead?").
        - emotional_goal: New target feeling (e.g. "I want to feel powerful").
        SWAP vs ATTRIBUTE CORRECTION (CRITICAL)

        If the user is correcting details of an item (color, texture, hardware, silhouette) but still wants the same item type,
        DO NOT use swap_out. Use attribute_corrections instead.

        Use swap_out ONLY when the user explicitly wants a different item/category/type
        (e.g., "replace the shoes", "no Uggs", "swap the boots for sneakers", "change pants").

        Examples:
        User: "my Uggs aren't furry"
        => attribute_corrections: [{target_category:"Shoes", must_avoid:["furry","shearling"], must_include:["smooth exterior"]}]
        => swap_out: []

        User: "I don't want Uggs, give me Chelsea boots"
        => swap_out: ["Shoes"]
        => attribute_corrections: []

        attribute_corrections must be a list of objects, each with:
        - target_category
        - must_include (list of strings)
        - must_avoid (list of strings)
        - note (optional)
        Example:
        User: "my Chelsea boots are brown"
        => swap_out: []
        => attribute_corrections: [
        { "target_category": "Shoes", "must_include": ["brown chelsea boots"], "must_avoid": ["black"] }
        ]


        # CRITICAL RULES
        - If the user suggests a REPLACEMENT (e.g. "wear jeans instead"), put the OLD category in 'swap_out' (e.g. "Pants").
        - Do NOT hallucinate items that aren't there.
        CRITICAL: OWNED ITEM CLARIFICATIONS ARE NOT SWAPS
        If the user says "my ___ is/are ___" about an item (color, texture, hardware),
        they are clarifying their owned item. This is NOT a swap.

        - Do NOT put that category in swap_out.
        - Use attribute_corrections with target_category and must_include/must_avoid.

        """
        
        # 1. Format Context safely
        # We act defensively in case the outfit data is empty or malformed
        outfit_context = "No specific outfit context."
        if current_outfit and 'outfit_options' in current_outfit:
            try:
                # We show the agent what the user is currently looking at
                items = current_outfit['outfit_options'][0]['items']
                item_list = ", ".join([f"{i.get('item_name')} ({i.get('category')})" for i in items])
                outfit_context = f"Current Items: {item_list}"
            except Exception:
                outfit_context = "Outfit data malformed."

        # 2. Call the API
        try:
            result = self.client.call_api(
                model=Config.OPENAI_MODEL_FAST, # Fast model is perfect for this translation task
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context: {outfit_context}\n\nUser Feedback: {user_input}"}
                ],
                response_model=RefinementAnalysis
            )
            return result.model_dump(exclude_none=True)
            
        except Exception as e:
            print(f"❌ Refiner Error: {e}")
            return {
                "make_more": [],
                "make_less": [],
                "swap_out": [],
                "emotional_goal": None,
                "expressed_likes": [],
                "expressed_dislikes": []
            }