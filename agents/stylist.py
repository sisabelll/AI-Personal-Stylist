import json
from typing import Any, Dict, Optional, List

from core.config import Config
from core.client import OpenAIClient
from core.schemas import OutfitRecommendation, RefinementAnalysis
from core.style_program_schemas import StyleProgram

class StyleStylist:
    def __init__(self, client: OpenAIClient):
        self.client = client

    def recommend(
        self,
        constraints: dict,
        situational_signals: dict,
        user_query: str,
        current_outfit: list = None,
        style_program: Optional[Dict[str, Any]] = None,
    ) -> OutfitRecommendation:
        """
        Returns a validated OutfitRecommendation Pydantic object.
        Convert to dict only at UI/storage boundary.
        """

        # -------------------------
        # 1) CONTEXT
        # -------------------------
        wear_category = constraints.get("wear_preference", "Unisex")
        body_type = constraints.get("body_style_essence", "General")
        color_season = constraints.get("personal_color", "General")
        season = constraints.get("season", "General")

        hard_constraints = situational_signals.get("hard_constraints") or {}
        event_raw = str(
            situational_signals.get("event_type")
            or hard_constraints.get("event_type")
            or constraints.get("event_type")
            or "General Day"
        )

        interp = situational_signals.get("style_interpretation") or {}
        formality_level = interp.get("formality_level")  # low|medium|high|None
        social_tone = interp.get("social_tone")
        aesthetic_bias = interp.get("aesthetic_bias")
        vibe_modifiers = interp.get("vibe_modifiers", [])
        attribute_corrections = situational_signals.get("attribute_corrections", [])

        # External inspiration (prefer rich doc if present)
        inspo = situational_signals.get("external_inspiration") or {}
        inspo_name = inspo.get("name") or ""
        inspo_vibe = inspo.get("vibe") or ""
        inspo_staples = inspo.get("wardrobe_staples") or []
        inspo_statements = inspo.get("statement_pieces") or []
        inspo_fabrics = inspo.get("fabric_preferences") or []
        inspo_palette = inspo.get("color_palette") or []

        # Feedback (edit mode)
        feedback = situational_signals.get("feedback") or {}
        swap_requests = feedback.get("swap_out") or []
        items_to_remove = situational_signals.get("items_to_remove") or []

        # TODO: extract from situational context?
        if formality_level:
            formality_text = {
                "low": "CASUAL/RELAXED — refined staples",
                "medium": "POLISHED — elevated basics, intentional styling",
                "high": "ELEVATED/FORMAL — refined materials, statement restraint",
            }.get(formality_level, "POLISHED — elevated basics")
        else:
            formal_keywords = ["wedding", "formal", "gala", "interview", "business", "upscale", "cocktail", "party"]
            is_formal = any(k in event_raw.lower() for k in formal_keywords)
            formality_text = "ELEVATED/FORMAL — refined materials" if is_formal else "CASUAL/RELAXED — refined staples"

        if style_program is None:
            style_program_obj = None
        elif hasattr(style_program, "model_dump"):
            style_program_obj = style_program
        elif isinstance(style_program, dict):
            style_program_obj = StyleProgram(**style_program)
        else:
            raise TypeError(f"style_program must be dict or StyleProgram, got {type(style_program)}")
        
        # ---------- Prompts ----------
        base_block = f"""
        You are an expert personal fashion stylist with strong editorial judgment.
        You think like a real stylist: intentional, selective, and aware of tradeoffs.
        You do NOT generate generic outfits or replace items unless explicitly asked.

        You must return STRICT JSON that matches the OutfitRecommendation schema.
        Do NOT include any extra keys or commentary outside the schema.
        """.strip()

        program_block = f"""
        STYLE PROGRAM (HIGH PRIORITY)
        - Editorial brief: {style_program_obj.style_brief}
        - Hero rule: {style_program_obj.hero_strategy}
        - Trend budget: max {style_program_obj.trend_budget} trend-forward element(s)
        - Editorial NOs: {", ".join(style_program_obj.editorial_nos) if style_program_obj.editorial_nos else "avoid anything dated, costume-y, or cheap-looking"}
        NON-NEGOTIABLES
        {style_program_obj.constraints_summary}
        """.strip()

        inspiration_block = ""
        if inspo_name or inspo_vibe or inspo_staples or inspo_statements or inspo_fabrics or inspo_palette:
            inspiration_block = f"""
            EXTERNAL INSPIRATION (USE AS GUIDANCE, DO NOT COSPLAY)
            Do NOT cosplay the reference.
            Translate the *essence*, not the exact outfit.
            - Reference: {inspo_name if inspo_name else "N/A"}
            - Vibe: {inspo_vibe if inspo_vibe else "N/A"}
            - Staples to borrow (pick 1–2 max): {", ".join(inspo_staples[:6]) if inspo_staples else "N/A"}
            - Statement direction (pick 0–1): {", ".join(inspo_statements[:5]) if inspo_statements else "N/A"}
            - Fabrics to prefer: {", ".join(inspo_fabrics[:6]) if inspo_fabrics else "N/A"}
            - Palette hints (must still respect user color season): {color_season}
            """.strip()

        context_block = f"""
        CONTEXT
        - Season: {season}
        - Event: {event_raw}
        - Formality: {formality_text}
        - Social tone: {social_tone or "N/A"}
        - Aesthetic bias: {aesthetic_bias or "N/A"}
        - Vibe modifiers: {", ".join(vibe_modifiers) if vibe_modifiers else "N/A"}
        - Body lines: honor {body_type} → Choose silhouettes, proportions, and structure that flatter this body type.
        - Color: prioritize {color_season} → If you intentionally deviate, you MUST acknowledge and justify it.
        - Items to avoid/remove: {", ".join(items_to_remove) if items_to_remove else "N/A"}
        """.strip()

        edit_block = ""
        if current_outfit:
            prev_items_str = "\n".join([f"- {i['category']}: {i['item_name']} | {i['search_query']}" for i in current_outfit])

            swap_requests = (situational_signals.get("feedback") or {}).get("swap_out", [])
            items_to_remove = situational_signals.get("items_to_remove", [])

            edit_block = f"""
            EDIT MODE (STRICT PARTIAL UPDATE)
            You are editing an existing outfit. Most items must stay unchanged.

            CURRENT OUTFIT (LOCKED BY DEFAULT):
            {prev_items_str}

            ONLY ALLOWED CHANGES:
            - Categories/items explicitly requested in swap_out: {json.dumps(swap_requests, ensure_ascii=False)}
            - Items explicitly disliked/removed: {json.dumps(items_to_remove, ensure_ascii=False)}

            ATTRIBUTE CORRECTIONS (DO NOT CHANGE ITEM IDENTITY):
            The user has clarified attributes of an existing item.
            You MUST keep the same item type and category.

            Attribute corrections (Attribute corrections do NOT unlock swaps):
            {attribute_corrections}

            Examples:
            - “not furry” → keep Uggs, but choose smooth / non-shearling versions
            - “less shiny” → same item category, different material
            - “mine are slimmer” → same item type, adjusted silhouette

            RULES:
            1. If a category is NOT in swap_out, you MUST copy its item_name and search_query verbatim.
            2. Attribute corrections NEVER allow replacing the item with a different type.
            3. You may ONLY change additional items if the outfit becomes physically impossible.
            """.strip()
        else:
            edit_block = "NEW OUTFIT MODE: Create a brand new outfit from scratch."

        physics_block = f"""
        OUTFIT STRUCTURE
        Provide at least 4 items using ONE template:

        Template A:
        - Top
        - Bottom
        - Shoes
        - Outerwear OR Accessory
        (+ optional extra accessory if justified)

        Template B (One-Piece):
        - Dress / Jumpsuit / Romper / Overalls
        - Shoes
        - Outerwear OR Accessory
        - Additional accessory

        USER-OWNED ITEMS (VISUAL PLACEHOLDERS):
        If the user wants to wear an item they own:
        - You MUST include it
        - reason MUST start with: “[OWNED] …”
        - search_query must describe the visual appearance (not “my ___”)

        CLOTHING PHYSICS (STRICT)
        1) ONE-PIECE DOMINANCE:
        If Dress/Gown/Jumpsuit/Romper/Overalls => DO NOT include Tops or Bottoms.
        2) FOOTWEAR COMPATIBILITY:
        - If open-toe shoes => no socks/hosiery unless explicitly quirky/high fashion.
        - If weather_safe footwear requested => avoid delicate suede/mesh; prefer leather/rubber soles.
        3) LAYERING COHERENCE:
        - If heavy layering needed => include a real outer layer (coat/jacket) and avoid flimsy summer fabrics.
        - If summer => ban puffer/heavy wool/trench; allow only light layers.
        4) FORMALITY COHERENCE:
        - High formality => avoid athletic sneakers, nylon backpacks, distressed denim.
        5) ACCESSORY CLUTTER:
        Avoid scarf + statement necklace together. Avoid belt with untucked/oversized tops.

        SEARCH QUERY RULES
        - Do NOT include gender terms (system handles it)
        - Be visual and specific: silhouette + material + details + aesthetic keywords

        EXPLANATION REQUIREMENTS (MANDATORY)
        Your explanation MUST explicitly address:

        1. Why the color palette works for the user’s color season.
        2. Why the silhouette and proportions flatter the user's body essence.
        3. How this outfit translates the external inspiration without copying it.
        4. What the hero item is and how the rest of the outfit supports it.
        5. Any tradeoffs (e.g. problem shoes) and how you compensated.

        Populate the styling rationale clearly and honestly.
        """.strip()

        system_prompt = "\n\n".join(
            [base_block, program_block, inspiration_block, context_block, edit_block, physics_block]
        ).strip()

        # TODO: Refine outfit categories. For example, is outerwear necessary in all contexts? 

        # 3. CALL THE WRAPPER
        response_obj = self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Query: {user_query}. \nSignals: {json.dumps(situational_signals, ensure_ascii=False)}"}
            ],
            temperature=0.7,
            response_model=OutfitRecommendation
        )

        # 4. STABILIZE (EDIT MODE ONLY)
        if current_outfit and response_obj.outfit_options:
            # define swap_requests safely
            swap_requests = (situational_signals.get("feedback") or {}).get("swap_out", []) or []

            option0 = response_obj.outfit_options[0]

            # only stabilize if items exist
            if option0.items and len(option0.items) > 0:
                new_items = [it.model_dump() for it in option0.items]
                stabilized_items = self._stabilize_outfit(
                    new_items=new_items,
                    old_items=current_outfit,
                    swap_requests=swap_requests
                )

                item_cls = type(option0.items[0])
                option0.items = [item_cls(**it) for it in stabilized_items]

        attribute_corrections = (situational_signals.get("attribute_corrections") or [])

        if response_obj.outfit_options and response_obj.outfit_options[0].items:
            option0 = response_obj.outfit_options[0]
            items_dicts = [it.model_dump() for it in option0.items]

            patched = self._apply_attribute_corrections(
                outfit_items=items_dicts,
                attribute_corrections=attribute_corrections
            )

            item_cls = type(option0.items[0])
            option0.items = [item_cls(**it) for it in patched]


        # 5. POSTPROCESS QUERIES (ALWAYS)
        self._apply_gender_query_postprocess(response_obj, wear_category)
        return response_obj

    def _apply_gender_query_postprocess(self, rec: OutfitRecommendation, wear_category: str) -> None:
        negatives = "-clipart -vector -aliexpress -ebay -amazon -walmart -costume -drawing -lowres -canvas"
        target_gender = wear_category.lower()

        for option in rec.outfit_options:
            for item in option.items:
                raw_query = item.search_query or ""
                if "-men" in raw_query or "-women" in raw_query or "unisex" in raw_query:
                    continue

                clean_query = (
                    raw_query.lower()
                    .replace("men's", "")
                    .replace("women's", "")
                    .replace("mens", "")
                    .replace("womens", "")
                    .replace(" my ", " ")
                    .replace(" i ", " ")
                    .strip()
                )

                if "women" in target_gender:
                    item.search_query = f"Women's {clean_query} {negatives} -men -mens -male"
                elif "men" in target_gender and "women" not in target_gender:
                    item.search_query = f"Men's {clean_query} {negatives} -women -womens -female"
                else:
                    item.search_query = f"{clean_query} {negatives} unisex gender-neutral"
                print(f"📷 Aesthetic Query: {item.search_query}")
    
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

        # After building final_list, ensure no locked categories were dropped
        final_cats = {it.get("category") for it in final_list}
        for cat, old_item in old_map.items():
            if cat not in final_cats and cat not in categories_to_change:
                final_list.append(old_item)
        return final_list
    
    def _apply_attribute_corrections(self, outfit_items: list, attribute_corrections: list) -> list:
        """
        Mutates item_name/search_query for locked items to match user clarifications,
        WITHOUT changing item identity/category.
        """
        if not attribute_corrections:
            return outfit_items

        # Build corrections by category
        by_cat = {}
        for c in attribute_corrections:
            cat = c.get("target_category")
            if not cat:
                continue
            by_cat.setdefault(cat, []).append(c)

        for item in outfit_items:
            cat = item.get("category")
            if cat not in by_cat:
                continue

            # merge must_include/must_avoid
            must_include = []
            must_avoid = []
            for c in by_cat[cat]:
                must_include += c.get("must_include", [])
                must_avoid += c.get("must_avoid", [])

            # Only adjust the descriptive fields (don’t change category)
            # Prefer editing search_query heavily; item_name lightly.
            sq = item.get("search_query", "")
            name = item.get("item_name", "")

            # Simple heuristic: append includes, add excludes with minus signs
            includes_txt = " ".join([x for x in must_include if x])
            excludes_txt = " ".join([f"-{x.replace(' ', '-')}" for x in must_avoid if x])

            # Update search query (more important than item_name)
            if includes_txt:
                sq = f"{sq} {includes_txt}".strip()
            if excludes_txt:
                sq = f"{sq} {excludes_txt}".strip()

            item["search_query"] = sq

            # Update item_name only when it’s clearly wrong (e.g., “furry” mentioned)
            lowered = name.lower()
            for bad in must_avoid:
                if bad and bad.lower() in lowered:
                    lowered = lowered.replace(bad.lower(), "").strip()
            item["item_name"] = " ".join(lowered.split()).title() if lowered else name

        return outfit_items

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
        result_obj = self.client.call_api(
            model=Config.OPENAI_MODEL_FAST, 
            messages=messages, 
            temperature=0.5, # Slightly higher temp helps with inferring vague feedback
            response_model=RefinementAnalysis
        )

        if not result_obj:
            return {
                "make_more": [],
                "make_less": [],
                "swap_out": [],
                "emotional_goal": None,
                "expressed_likes": [],
                "expressed_dislikes": []
            }
            
        return result_obj.model_dump()

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
            model=Config.OPENAI_MODEL_FAST,
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