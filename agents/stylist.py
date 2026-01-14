import json
from typing import Optional, List

from core.client import OpenAIClient
from core.schemas import StylistRecommendation, RefinementAnalysis

class StyleStylist:
    def __init__(self, client: OpenAIClient):
        self.client = client

    def recommend(self, user_constraints: dict, situational_signals: dict, user_query: str, closet_items: Optional[List] = None) -> str:
        wear_category = user_constraints['wear_category']
        inspiration_data = situational_signals.get('external_style_inspiration', {})
        is_formal = user_constraints.get('polish_level') == 'evening' or user_constraints.get('formality_level') == 'high'
        
        system_prompt = f"""
        You are an expert personal stylist with refined taste and professional discipline.

        # ROLE
        Your role is to recommend outfits that are appropriate to the situation, aligned with the client's constraints, and feel confident and intentional.
        You are a working stylist, not an inspiration engine.

        # CONTEXT PROCESSING (PRIORITY)
        You will receive "SITUATIONAL STYLE SIGNALS". Process them logically:
        1. "vibe_modifiers": Shift your suggestion towards these traits immediately.
        2. "emotional_target": Prioritize this goal feeling over generic logic.
        3. "session_avoids" & "avoid_vibes": TEMPORARY HARD STOPS. Do not recommend these.
        4. "requested_items": MANDATORY. Build the outfit around these specific items. Do not replace them.

        # CRITICAL RULES (NON-NEGOTIABLE)
        - You MUST NOT recommend any item listed in 'Hard Avoids' or 'session_avoids'.
        - You MUST respect body structure and color harmony implicitly.
        - Gender Constraint: The client strictly adheres to the '{wear_category}' category.
        - Menswear: Trousers, suits, structured jackets. No skirts/dresses unless asked.
        - Womenswear: Standard range.
        - Unisex: Avoid overtly gendered detailing.

        # STYLING DIRECTION
        1. CHECK SIGNALS: Review refinements (make_more, swap_out).
        2. ADJUST POLISH: Calibrate formality based on the event.
        3. SILHOUETTE: Strictly follow body line constraints.
        4. CONFLICT RESOLUTION: If a cultural event conflicts with Color Season, find the seasonal variation (e.g., 'Cool Berry' instead of 'Bright Red').

        # DYNAMIC RESEARCH
        The user wants to channel the vibe: "{inspiration_data.get('vibe')}".
        - Staples: {inspiration_data.get('wardrobe_staples')}
        - Statement Pieces: {inspiration_data.get('statement_pieces')}
        - LOGIC: {'Use Statement Pieces to elevate.' if is_formal else 'Stick to Staples unless outerwear is needed.'}

        # RESPONSE GUIDELINES
        - Speak directly to the client in the descriptions.
        - In the 'reason' field for each item, explicitly mention which Style Rule (Body Type, Color Season) triggered that choice.
        - Do NOT output markdown or conversational filler. Just the data.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]
        result = self.client.call_api(model='gpt-4o-2024-08-06', messages=messages, temperature=0.1, response_model=StylistRecommendation)        
        return result

    def interpret_refinement(self, user_followup: str, conversation_state: dict) -> dict:
        print(f"🔧 Interpreting Refinement: '{user_followup}'")
        prompt = f"""
        You are a Style Refinement Analyzer.
        The user is reacting to a previous outfit recommendation.
        
        YOUR TASK:
        Extract refinement signals from the user's follow-up.
        Map their intent into the structured categories provided.
        
        CONTEXT - PREVIOUS OUTFIT STATE:
        {json.dumps(conversation_state.get('current_recommendation', {}), indent=2)}
        
        USER FOLLOW-UP:
        "{user_followup}"
        """

        messages = [{"role": "system", "content": prompt}]
        result = self.client.call_api(
            model='gpt-4o-mini', 
            messages=messages, 
            temperature=0.5, # Slightly higher temp helps with inferring vague feedback
            response_model=RefinementAnalysis
        )

        # If the helper returns {} (error), return your specific default structure
        if not result:
            return {
                "make_more": [],
                "make_less": [],
                "swap_out": [],
                "emotional_goal": None,
                "expressed_likes": [],
                "expressed_dislikes": []
            }
            
        return result

    def consult(self, current_outfit_context: dict, user_question: str) -> str:
        """
        Pure conversational mode. Answers the user's doubts using the current outfit as context.
        """

        system_prompt = f"""
        You are a collaborative Personal Stylist.
        The user has a question or comment about the current outfit recommendation.
        
        CONTEXT (The current outfit):
        {json.dumps(current_outfit_context, indent=2)}
        
        YOUR GOAL:
        1. Answer the specific question honestly (e.g., "Is this too fancy?").
        2. Explain your styling logic if needed.
        3. End with a helpful "Next Step" question (e.g., "Would you prefer to swap it for X?").
        
        Keep it conversational, warm, and concise. Do NOT generate JSON. Just text.
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question}
        ]
        
        return self.client.call_api(
            model='gpt-4o-mini',
            messages=messages,
            temperature=0.7 
        )
    
    def merge_conversation_state(self, current_state, new_refinement_delta):
        """
        Merges new refinements into the existing state using Smart Update.
        """
        # 1. Ensure the target dictionary exists
        if 'refinement_signals' not in current_state:
            current_state['refinement_signals'] = {}
            
        # 2. TARGET: We only want to update the 'refinement_signals' sub-dictionary
        target_dict = current_state['refinement_signals']
        
        # 3. EXECUTE: Smart Update does all the work (Lists vs Strings)
        # It updates 'target_dict' in place, which updates 'current_state'
        self._smart_update(target_dict, new_refinement_delta)

        return current_state
    
    def _safe_merge(self, list_a, list_b):
        """
        Merges two lists and removes duplicates. 
        Works for both simple strings AND complex dictionaries.
        """
        # Start with a copy of list_a
        unique_items = list(list_a)
        
        # Add items from list_b only if they aren't already there
        for item in list_b:
            if item not in unique_items:
                unique_items.append(item)
                
        return unique_items
    
    def _smart_update(self, current_data, new_data):
        """Helper: Recursively merges dictionaries."""
        for key, new_val in new_data.items():
            if key not in current_data:
                current_data[key] = new_val
                continue
            
            old_val = current_data[key]
            
            # CASE 1: Lists -> Append & Deduplicate
            if isinstance(old_val, list) and isinstance(new_val, list):
                current_data[key] = self._safe_merge(old_val, new_val)
                
            # CASE 2: Dicts -> Dive Deeper
            elif isinstance(old_val, dict) and isinstance(new_val, dict):
                self._smart_update(old_val, new_val)
                
            # CASE 3: Others -> Overwrite
            else:
                current_data[key] = new_val
        return current_data