import json
from typing import Optional, List

from core.config import Config
from core.client import OpenAIClient
from core.schemas import OutfitRecommendation, RefinementAnalysis

class StyleStylist:
    def __init__(self, client: OpenAIClient):
        self.client = client

    def recommend(self, constraints: dict, situational_signals: dict, user_query: str, current_outfit: list = None):
        """
        Generates the outfit recommendation. 
        """
        
        # 1. PREPARE CONTEXT VARIABLES
        wear_category = constraints.get('wear_preference', 'Unisex')
        body_type = constraints.get('body_style_essence', 'General')
        color_season = constraints.get('personal_color', 'General')
        
        inspo_data = situational_signals.get('external_inspiration', {})
        inspo_vibe = inspo_data.get('vibe', '')
        
        event_raw = constraints.get('event_type', '') or situational_signals.get('event_type', '')
        season = constraints.get('season', 'General') 

        # Calculate formality for the Logic Switch
        formal_keywords = ['wedding', 'formal', 'gala', 'interview', 'business', 'upscale', 'cocktail', 'party']
        is_formal = any(k in event_raw.lower() for k in formal_keywords)

        # 2. CONSTRUCT THE PROMPT
        system_prompt = f"""
        You are an expert personal fashion stylist.

        # ROLE
        Create a cohesive, stylish outfit that matches the user's request.
        """
        
        # TODO: Refine outfit categories. For example, is outerwear necessary in all contexts? 
        if current_outfit:
            prev_items_str = "\n".join([f"- {item['category']}: {item['item_name']}" for item in current_outfit])
            system_prompt += f"""
            **CONTEXT: THE USER IS EDITING THIS EXISTING OUTFIT:**
            {prev_items_str}

            **CRITICAL STYLING RULE:** Any NEW items you generate MUST aesthetically match the UNCHANGED items listed above. 
            (e.g., If keeping 'Sneakers', do not recommend a 'Formal Gown'.)

            **STRICT REFINEMENT RULES:**
            1. **PARTIAL EDITS ONLY:** If the user says "Change the pants", you MUST KEEP the Top, Shoes, and Accessories EXACTLY the same. 
            2. **COPY DATA:** For unchanged items, copy their 'item_name' and 'search_query' verbatim. Do not "re-imagine" them.
            3. **ONLY** change items if:
               - The user explicitly asked to swap them.
               - They structurally clash (see Physics Rules below).
            """
        else:
            system_prompt += "\n**CONTEXT:** Creating a brand new outfit from scratch.\n"

        system_prompt += f"""
        You MUST provide a complete outfit with at least 4 items, following one of these templates:
        **RULE: USER-OWNED ITEMS (VISUAL PLACEHOLDERS)**
        - IF the user wants to wear a specific item they own (e.g., "Use my brown pants", "I'm wearing my leather jacket"):
        - **CRITICAL:** Set the 'reason' field to start with: "[OWNED] ..." 
        - Example: "[OWNED] Using your request for dark brown pants."
        - **ACTION:** You MUST include this item in the outfit list under its correct category (Top, Bottom, Shoes, Outerwear, etc.).
        - **DO NOT SKIP IT.** We need it for the visual moodboard.
        - **SEARCH QUERY:** Create a generic visual query describing the item.
        - BAD: "My brown pants" (No results)
        - GOOD: "Dark brown wide leg trousers fabric texture" (Visual Match)
        
        **TEMPLATE A (Standard):**
        - 1 Top
        - 1 Bottom
        - 1 Shoes
        - 1 [Outerwear OR Accessory] (Pick whichever suits the weather/vibe best - or both!)

        **TEMPLATE B (One-Piece):**
        - 1 [Dress, Jumpsuit, or Romper]
        - 1 Shoes
        - 1 [Outerwear OR Accessory]
        - 1 Additional Accessory (Bag, Jewelry, etc.)

        # CATEGORY PHYSICS (STRICT RULES)
        You must enforce these rules to prevent "impossible" outfits:

        1. **THE "ONE-PIECE" DOMINANCE**
           - IF you recommend a [Dress, Gown, Jumpsuit, Romper, Overalls]:
           - **ACTION:** YOU MUST DELETE ALL 'Tops' AND 'Bottoms'.
           - REASON: You cannot wear jeans under a jumpsuit.

        2. **THE "OPEN-TOE" PROTOCOL**
           - IF Shoes are [Sandals, Slides, Flip-Flops, Strappy Heels, Peep-toe]:
           - **ACTION:** DELETE 'Socks' or 'Hosiery'.
           - EXCEPTION: Unless the vibe is explicitly 'Quirky' or 'High Fashion'.

        3. **SEASONAL OUTERWEAR LOGIC**
           - Current Season: {season}
           - IF Season is 'Summer': **BAN** [Puffer Jackets, Heavy Wool Coats, Trenches].
           - ALLOW ONLY: [Light Cardigan, Denim Jacket, Linen Blazer, Kimono, Shawl].

        4. **ACCESSORY CLUTTER**
           - DO NOT recommend [Scarf] + [Statement Necklace] together (Too busy).
           - DO NOT recommend [Belt] if the Top is 'Untucked' or 'Oversized'.

        # VISUALIZATION (SEARCH QUERIES)
        - **DO NOT** type gender (e.g., "Women's", "Men's") in the search query. My system handles that.
        - **FOCUS ON VIBE:** Describe the visual details that matter.
        - BAD: "Women's pants"
        - GOOD: "High-waisted wide leg linen trousers beige pleats"
        
        # STYLING STRATEGY
        1. **VIBE:** {inspo_vibe}
        2. **FORMALITY:** {'ELEVATED/FORMAL - Use Statement Pieces' if is_formal else 'CASUAL/RELAXED - Stick to Staples'} ({event_raw})
        3. **BODY TYPE:** Honor {body_type} lines.
        4. **COLOR:** Prioritize {color_season} palette.
        """

        # 3. CALL THE WRAPPER
        try:
            response_data = self.client.call_api(
                model=Config.OPENAI_MODEL_SMART,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"User Query: {user_query}. \nSignals: {situational_signals}"}
                ],
                temperature=0.7,
                response_model=OutfitRecommendation 
            )

            if current_outfit and response_data.get('outfit_options'):
                # Extract what the user wanted to swap (e.g., ['Oversized Knit Cardigan', 'Top'])
                swap_requests = situational_signals.get('feedback', {}).get('swap_out', [])
                
                # Run the stabilizer
                stabilized_items = self._stabilize_outfit(
                    new_items=response_data['outfit_options'][0]['items'],
                    old_items=current_outfit,
                    swap_requests=swap_requests
                )
                response_data['outfit_options'][0]['items'] = stabilized_items
            
            if response_data and 'outfit_options' in response_data:
                for option in response_data['outfit_options']:
                    for item in option['items']:
                        raw_query = item.get('search_query', '')

                        clean_query = raw_query.lower() \
                            .replace("men's", "") \
                            .replace("women's", "") \
                            .replace("mens", "") \
                            .replace("womens", "") \
                            .replace(" my ", " ") \
                            .replace(" i ", " ") # Remove "I want" artifacts
                        
                        clean_query = clean_query.strip()
                        # A. SKIP CHECK: 
                        # If the Stabilizer put back an old item that is already perfect, 
                        # don't touch it. (Prevents "Women's Women's shirt -men -men")
                        if "-men" in raw_query or "-women" in raw_query or "unisex" in raw_query:
                            continue 

                        # B. CLEAN UP: Remove confusing prefixes so we start fresh
                        # (e.g. "Men's Scarf" -> "Scarf")
                        clean_query = raw_query.replace("Men's", "").replace("Women's", "").replace("Mens", "").replace("Womens", "")
                        clean_query = clean_query.strip()
                        
                        # C. APPLY SMART OPERATORS
                        # Normalize inputs to handle "Women" or "Womenswear"
                        target_gender = wear_category.lower()

                        if 'women' in target_gender:
                            # Force "Women's" at start, BAN "Men" at end
                            item['search_query'] = f"Women's {clean_query} -men -mens -male"
                            
                        elif 'men' in target_gender and 'women' not in target_gender: 
                            # (The 'and' prevents 'women' matching inside 'men')
                            item['search_query'] = f"Men's {clean_query} -women -womens -female"
                            
                        else: # UNISEX LOGIC
                            item['search_query'] = f"{clean_query} unisex gender-neutral boxy-fit"

                        print(f"🔍 Smart Query: {item['search_query']}")
                            
            return response_data
            
        except Exception as e:
            print(f"❌ Stylist Error: {e}")
            return self._fallback_error()
        
    def _stabilize_outfit(self, new_items: list, old_items: list, swap_requests: list) -> list:
        """
        Merges New items with Old items.
        If a category was NOT requested to change, we FORCE the old item back in.
        """
        print(f"🔐 Stabilizing Outfit. Swap Requests: {swap_requests}")
        
        # 1. Map Old Items by Category for easy lookup
        old_map = {item['category']: item for item in old_items}
        
        # 2. Identify "Dirty" Categories (Must Change)
        categories_to_change = set()
        
        # Standardize categories from swap_requests
        for req in swap_requests:
            req_lower = req.lower()
            # Check against standard keys
            if req_lower in ['top', 'bottom', 'shoes', 'outerwear', 'accessory', 'accessories']:
                categories_to_change.add(req_lower.capitalize())
                if req_lower == 'accessories': categories_to_change.add('Accessory')
            else:
                # Check against specific item names
                for old_item in old_items:
                    if req_lower in old_item.get('item_name', '').lower():
                        categories_to_change.add(old_item['category'])
        
        print(f"⚠️ Categories unlocked for change: {categories_to_change}")

        # 3. Build Final List
        final_list = []
        for new_item in new_items:
            cat = new_item.get('category')
            
            # CHECK: Should we revert this item?
            # Rule: If we have an old version, AND the user didn't ask to change this category...
            if cat in old_map and cat not in categories_to_change:
                # FORCE REVERT
                print(f"↩️ Reverting {cat} to original state.")
                final_list.append(old_map[cat]) # Use the exact old JSON
            else:
                # Keep the new version (It's either a requested change OR a new category)
                final_list.append(new_item)
                
        return final_list
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
        1. Answer the specific question, doubt, or comment honestly (e.g., "Is this too fancy?").
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