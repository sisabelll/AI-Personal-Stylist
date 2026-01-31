import json
from typing import Any, Dict, Optional, List, Iterable

from core.config import Config
from services.client import OpenAIClient
from core.schemas import OutfitRecommendation, RefinementAnalysis, canon_category
from core.style_program_schemas import StyleProgram


Category = str  # keep simple here; your Pydantic uses Literals


class StyleStylist:
    """
    Clean invariants:
      - All internal category keys are TitleCase: Top/Bottom/Shoes/Outerwear/Accessory/OnePiece/Outfit/Unknown
      - Stabilization works on category keys only (no mixing "bottom" and "Bottom")
      - Owned anchors deterministically force the category item (replace or insert)
      - One item per category (after each major step)
    """

    ORDER: List[Category] = ["Top", "Bottom", "OnePiece", "Shoes", "Outerwear", "Accessory"]

    def __init__(self, client: OpenAIClient):
        self.client = client

    # ----------------------------
    # Canonicalization
    # ----------------------------
    def _canon_items_inplace(self, items: List[dict]) -> None:
        for it in items:
            it["category"] = canon_category(it.get("category"))

    def _dedupe_one_per_category(self, items: List[dict]) -> List[dict]:
        """
        Enforce one item per category. If duplicates occur, keep the LAST one (newest override).
        """
        by_cat: Dict[Category, dict] = {}
        for it in items:
            cat = canon_category(it.get("category"))
            if cat == "Unknown":
                continue
            it["category"] = cat
            by_cat[cat] = it  # last wins

        out: List[dict] = []
        for cat in self.ORDER:
            if cat in by_cat:
                out.append(by_cat[cat])

        # any other categories (rare)
        for cat, it in by_cat.items():
            if cat not in self.ORDER:
                out.append(it)

        return out

    # ----------------------------
    # Public API
    # ----------------------------
    def recommend(
        self,
        constraints: dict,
        situational_signals: dict,
        user_query: str,
        current_outfit: List[dict] = None,
        style_program=None,
    ) -> OutfitRecommendation:

        wear_category = constraints.get("wear_preference", "Unisex")
        body_type = constraints.get("body_style_essence", "General")
        color_season = constraints.get("color_season") or constraints.get("personal_color") or "General"
        season = constraints.get("season", "General")

        hard_constraints = situational_signals.get("hard_constraints") or {}
        event_raw = str(
            situational_signals.get("event_type")
            or hard_constraints.get("event_type")
            or constraints.get("event_type")
            or "General Day"
        )

        interp = situational_signals.get("style_interpretation") or {}
        formality_level = interp.get("formality_level")
        social_tone = interp.get("social_tone")
        aesthetic_bias = interp.get("aesthetic_bias")
        vibe_modifiers = interp.get("vibe_modifiers", [])

        # external inspiration
        inspo = situational_signals.get("external_inspiration") or {}
        inspo_name = inspo.get("name") or ""
        inspo_vibe = inspo.get("vibe") or ""
        inspo_staples = inspo.get("wardrobe_staples") or []
        inspo_statements = inspo.get("statement_pieces") or []
        inspo_fabrics = inspo.get("fabric_preferences") or []
        inspo_palette = inspo.get("color_palette") or []

        # feedback/edit signals
        feedback = situational_signals.get("feedback") or {}
        if hasattr(feedback, "model_dump"):
            feedback = feedback.model_dump()

        swap_requests_raw = self._get_swap_requests_raw(feedback)
        items_to_remove = situational_signals.get("items_to_remove") or []
        attribute_corrections = situational_signals.get("attribute_corrections", []) or []
        owned_anchors = situational_signals.get("owned_anchors") or []

        # --- formality text ---
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

        style_program_obj = self._coerce_style_program(style_program)

        # ----------------------------
        # Prompt assembly
        # ----------------------------
        base_block = """
        You are an expert personal fashion stylist with strong editorial judgment.
        You think like a real stylist: intentional, selective, and aware of tradeoffs.
        You do NOT generate generic outfits or replace items unless explicitly asked.

        You must return STRICT JSON that matches the OutfitRecommendation schema.
        Do NOT include any extra keys or commentary outside the schema.
        """.strip()

        program_block = ""
        if style_program_obj:
            program_block = f"""
            STYLE PROGRAM (HIGH PRIORITY)
            - Editorial brief: {style_program_obj.style_brief}
            - Hero rule: {style_program_obj.hero_strategy}
            - Trend budget: max {style_program_obj.trend_budget} trend-forward element(s)
            - Editorial NOs: {", ".join(style_program_obj.editorial_nos) if style_program_obj.editorial_nos else "avoid anything dated, costume-y, or cheap-looking"}
            NON-NEGOTIABLES:
            {chr(10).join(style_program_obj.constraints_summary or [])}
            """.strip()

        inspiration_block = ""
        if any([inspo_name, inspo_vibe, inspo_staples, inspo_statements, inspo_fabrics, inspo_palette]):
            inspiration_block = f"""
            EXTERNAL INSPIRATION (GUIDANCE, DO NOT COSPLAY)
            Translate the essence, not the exact outfit.
            - Reference: {inspo_name or "N/A"}
            - Vibe: {inspo_vibe or "N/A"}
            - Staples to borrow (pick 1–2 max): {", ".join(inspo_staples[:6]) if inspo_staples else "N/A"}
            - Statement direction (pick 0–1): {", ".join(inspo_statements[:5]) if inspo_statements else "N/A"}
            - Fabrics to prefer: {", ".join(inspo_fabrics[:6]) if inspo_fabrics else "N/A"}
            - Palette reminder: must respect user's color season ({color_season})
            """.strip()

        context_block = f"""
        CONTEXT
        - Season: {season}
        - Event: {event_raw}
        - Formality: {formality_text}
        - Social tone: {social_tone or "N/A"}
        - Aesthetic bias: {aesthetic_bias or "N/A"}
        - Vibe modifiers: {", ".join(vibe_modifiers) if vibe_modifiers else "N/A"}
        - Body lines: honor {body_type} with silhouette/proportions/structure
        - Color: prioritize {color_season}; if deviating, acknowledge and justify
        - Items to avoid/remove: {", ".join(items_to_remove) if items_to_remove else "N/A"}
        """.strip()

        # Canonical swap_out for prompt (TitleCase)
        swap_requests = sorted({canon_category(x) for x in swap_requests_raw if canon_category(x) != "Unknown"})
        # If you want anchor_owned to *always* be included, treat it as forcing the category unlocked:
        forced_from_anchors = sorted({canon_category(a.get("target_category")) for a in (owned_anchors or []) if canon_category(a.get("target_category")) != "Unknown"})
        swap_requests_for_prompt = sorted(set(swap_requests) | set(forced_from_anchors))

        edit_block = ""
        if current_outfit:
            # Ensure current_outfit categories are canonical too
            current_outfit_canon = []
            for it in current_outfit:
                it2 = dict(it)
                it2["category"] = canon_category(it2.get("category"))
                current_outfit_canon.append(it2)

            prev_items_str = "\n".join(
                [f"- {i['category']}: {i['item_name']} | {i.get('search_query','')}" for i in current_outfit_canon]
            )
            edit_block = f"""
            EDIT MODE (STRICT PARTIAL UPDATE)
            You are editing an existing outfit. Most items must stay unchanged.

            CURRENT OUTFIT (LOCKED BY DEFAULT):
            {prev_items_str}

            ONLY ALLOWED CATEGORY CHANGES:
            swap_out = {json.dumps(swap_requests_for_prompt, ensure_ascii=False)}
            Only categories listed in swap_out may change item identity.

            ATTRIBUTE CORRECTIONS (DO NOT CHANGE CATEGORY):
            {json.dumps(attribute_corrections, ensure_ascii=False)}

            RULES:
            1) If a category is NOT in swap_out, you MUST copy its item_name and search_query verbatim.
            2) Attribute corrections DO NOT unlock swaps; they only adjust descriptors for the SAME category/type.
            3) Clothing physics applies (OnePiece cannot coexist with Top+Bottom).
            """.strip()
        else:
            edit_block = "NEW OUTFIT MODE: Create a brand new outfit from scratch."

        physics_block = """
        OUTFIT STRUCTURE
        Use ONE template:

        Template A (Separates):
        - Top
        - Bottom
        - Shoes
        - Outerwear OR Accessory
        (+ optional extra accessory if justified)

        Template B (One-Piece):
        - OnePiece
        - Shoes
        - Outerwear OR Accessory
        - Additional accessory

        CLOTHING PHYSICS (STRICT)
        1) One-piece dominance: If OnePiece exists, do not include Top or Bottom.
        2) Avoid accessory clutter; keep it edited.
        3) Formality coherence: high formality => avoid athletic sneakers, distressed denim, nylon backpack vibes.

        OWNED ITEM RULE
        Only mark owned=true IF the user explicitly said it’s theirs (“my”, “I own”, “in my closet”).
        If owned=true, reason MUST start with “[OWNED]”.
        """.strip()

        system_prompt = "\n\n".join(
            [base_block, program_block, inspiration_block, context_block, edit_block, physics_block]
        ).strip()

        editor_plan = situational_signals.get("editor_plan")
        if editor_plan:
            system_prompt += f"\n\nEDITOR REVISION REQUEST (HIGH PRIORITY)\n{json.dumps(editor_plan, ensure_ascii=False)}"

        # ----------------------------
        # Call model
        # ----------------------------
        response_obj = self.client.call_api(
            model=Config.OPENAI_MODEL_SMART,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Query: {user_query}\nSignals: {json.dumps(situational_signals, ensure_ascii=False)}"},
            ],
            temperature=0.7,
            response_model=OutfitRecommendation,
        )

        option0 = response_obj.outfit_options[0] if response_obj.outfit_options else None
        if not option0 or not option0.items:
            return response_obj
        return response_obj

    # ----------------------------
    # Helpers
    # ----------------------------
    def _coerce_style_program(self, style_program) -> Optional[StyleProgram]:
        if style_program is None:
            return None
        if isinstance(style_program, StyleProgram):
            return style_program
        if hasattr(style_program, "model_dump"):
            return StyleProgram(**style_program.model_dump())
        if isinstance(style_program, dict):
            return StyleProgram(**style_program)
        raise TypeError(f"style_program must be dict or StyleProgram, got {type(style_program)}")

    def _enforce_one_piece_physics(self, items: List[dict]) -> List[dict]:
        """
        If OnePiece exists, remove Top/Bottom.
        If both Top+Bottom exist, remove OnePiece.
        """
        cats = {canon_category(it.get("category")) for it in items}
        has_top = "Top" in cats
        has_bottom = "Bottom" in cats
        has_onepiece = "OnePiece" in cats

        if has_onepiece and (has_top or has_bottom):
            # Prefer separates unless OnePiece was explicitly requested upstream.
            return [it for it in items if canon_category(it.get("category")) != "OnePiece"]

        return items

    def _get_swap_requests_raw(self, feedback: dict) -> List[str]:
        if not feedback:
            return []
        raw = feedback.get("swap_out_raw")
        if raw:
            return raw
        return feedback.get("swap_out") or []

    def _stabilize_outfit(
        self,
        new_items: List[dict],
        old_items: List[dict],
        swap_requests: List[Category],
    ) -> List[dict]:
        """
        Lock categories not in swap_requests to their old item (item_name + search_query).
        swap_requests is already canonical TitleCase.
        """
        raw_swaps = [canon_category(x) for x in (swap_requests or []) if canon_category(x) != "Unknown"]
        swap_set = set(raw_swaps)
        onepiece_requested = "OnePiece" in raw_swaps

        old_cats = {canon_category(it.get("category")) for it in (old_items or [])}

        # If old outfit is OnePiece and user wants Top/Bottom, we must allow OnePiece to change too.
        if (("Top" in swap_set) or ("Bottom" in swap_set)) and (("OnePiece" in old_cats)):
            swap_set |= {"OnePiece"}

        # Your existing rule (good): if OnePiece is being swapped, allow Top/Bottom too.
        if onepiece_requested:
            swap_set |= {"Top", "Bottom"}

        old_cats = {canon_category(it.get("category")) for it in (old_items or [])}
        print(f"🔁 Swap debug — old categories: {sorted(old_cats)}")
        print(f"🔁 Swap debug — new requested category: {sorted(raw_swaps)}")
        print(f"🔁 Swap debug — new categories proposed to change: {sorted(swap_set)}")
        print(f"🔐 Stabilizing Outfit. Swap Requests (canonical): {sorted(swap_set)}")

        # Canonicalize old items and index by category
        old_map: Dict[Category, dict] = {}
        for it in (old_items or []):
            it2 = dict(it)
            it2["category"] = canon_category(it2.get("category"))
            cat = it2["category"]
            if cat != "Unknown":
                old_map[cat] = it2

        # Build final map; if locked, revert to old
        final_by_cat: Dict[Category, dict] = {}
        for it in (new_items or []):
            cat = canon_category(it.get("category"))
            if cat == "Unknown":
                continue

            if (cat in old_map) and (cat not in swap_set):
                final_by_cat[cat] = old_map[cat]
            else:
                it["category"] = cat
                final_by_cat[cat] = it

        # Ensure locked categories aren't dropped
        for cat, old_it in old_map.items():
            if (cat not in final_by_cat) and (cat not in swap_set):
                final_by_cat[cat] = old_it

        # If switching from OnePiece to separates, never keep the OnePiece.
        if "OnePiece" in final_by_cat and "OnePiece" in old_cats and (("Top" in swap_set) or ("Bottom" in swap_set)):
            final_by_cat.pop("OnePiece", None)

        onepiece_locked = ("OnePiece" in old_map) and ("OnePiece" not in swap_set)

        # Swap-aware one-piece rule:
        # - If OnePiece is explicitly requested, drop Top/Bottom.
        # - If OnePiece is NOT requested, do not allow it to coexist with Top/Bottom.
        if onepiece_requested:
            final_by_cat.pop("Top", None)
            final_by_cat.pop("Bottom", None)
        elif "OnePiece" in final_by_cat and (("Top" in final_by_cat) or ("Bottom" in final_by_cat)):
            if onepiece_locked:
                final_by_cat.pop("Top", None)
                final_by_cat.pop("Bottom", None)
            else:
                final_by_cat.pop("OnePiece", None)

        # If switching from OnePiece to separates, ensure both Top + Bottom exist.
        if ("OnePiece" in old_cats) and (("Top" in swap_set) or ("Bottom" in swap_set)) and ("OnePiece" not in final_by_cat) and (not onepiece_requested):
            if "Top" not in final_by_cat:
                final_by_cat["Top"] = {
                    "category": "Top",
                    "item_name": "Core top",
                    "search_query": "women's core top",
                    "reason": "Added to complete separates after removing a one-piece.",
                }
            if "Bottom" not in final_by_cat:
                final_by_cat["Bottom"] = {
                    "category": "Bottom",
                    "item_name": "Core bottom",
                    "search_query": "women's core bottom",
                    "reason": "Added to complete separates after removing a one-piece.",
                }

        # Return in stable order
        out: List[dict] = []
        for cat in self.ORDER:
            if cat in final_by_cat:
                out.append(final_by_cat[cat])
        return out

    def _apply_owned_anchors(self, items: List[dict], owned_anchors: List[dict]) -> List[dict]:
        """
        Owned anchors are "user truth": force an item for that category.
        This will replace any existing item in that category.
        """
        if not owned_anchors:
            return items

        by_cat = {canon_category(it.get("category")): it for it in items if canon_category(it.get("category")) != "Unknown"}

        for a in owned_anchors:
            cat = canon_category(a.get("target_category"))
            if cat == "Unknown":
                continue

            must_list = [x for x in (a.get("must_include") or []) if x]
            avoid_list = [x for x in (a.get("must_avoid") or []) if x]

            item_name = (a.get("item_name") or "").strip()
            if not item_name and must_list:
                item_name = must_list[0].strip()

            # Make sure item_name is included as a phrase in must_list (stronger query)
            if item_name and item_name not in must_list:
                must_list = [item_name] + must_list

            must = " ".join(must_list).strip()
            neg = " ".join([f"-{x.strip().replace(' ', '-')}" for x in avoid_list if x.strip()]).strip()

            forced = {
                "category": cat,
                "item_name": item_name or "Owned item",
                "search_query": " ".join([must, neg]).strip(),
                "owned": True,
                "reason": f"[OWNED] User wants to wear their {item_name or cat}.",
            }

            by_cat[cat] = {**by_cat.get(cat, {}), **forced}

        # rebuild list (order later handled by dedupe/order)
        out = list(by_cat.values())
        return out

    def _apply_attribute_corrections(
        self,
        outfit_items: List[dict],
        attribute_corrections: List[dict],
        allowed_swap_categories: List[Category] = None,
    ) -> List[dict]:
        """
        Apply attribute constraints to search_query (and lightly to item_name),
        but ONLY when:
          - category is unlocked for change, OR
          - item is owned=true
        """
        if not attribute_corrections:
            return outfit_items

        allowed = {canon_category(x) for x in (allowed_swap_categories or []) if canon_category(x) != "Unknown"}

        by_cat: Dict[Category, List[dict]] = {}
        for c in attribute_corrections:
            cat = canon_category(c.get("target_category"))
            if cat != "Unknown":
                by_cat.setdefault(cat, []).append(c)

        for item in outfit_items:
            cat = canon_category(item.get("category"))
            if cat not in by_cat:
                continue

            owned = bool(item.get("owned", False))
            if (cat not in allowed) and (not owned):
                continue

            must_include: List[str] = []
            must_avoid: List[str] = []
            for c in by_cat[cat]:
                must_include += [x for x in (c.get("must_include") or []) if x]
                must_avoid += [x for x in (c.get("must_avoid") or []) if x]

            sq = (item.get("search_query") or "").strip()
            if must_include:
                sq = f"{sq} " + " ".join(must_include)
            if must_avoid:
                neg = " ".join([f"-{x.strip().replace(' ', '-')}" for x in must_avoid if x.strip()])
                sq = f"{sq} {neg}".strip()

            item["search_query"] = " ".join(sq.split())

            # Optional: lightly scrub item_name of forbidden tokens
            name = (item.get("item_name") or "")
            lowered = name.lower()
            for bad in must_avoid:
                if bad.lower() in lowered:
                    lowered = lowered.replace(bad.lower(), " ").strip()
            item["item_name"] = " ".join(lowered.split()).title() if lowered else name

        return outfit_items

    def _apply_gender_query_postprocess(self, rec: OutfitRecommendation, wear_category: str) -> None:
        negatives = "-clipart -vector -aliexpress -ebay -amazon -walmart -costume -drawing -lowres -canvas"
        target_gender = (wear_category or "unisex").lower()

        for option in rec.outfit_options:
            for item in option.items:
                raw_query = item.search_query or ""
                if any(t in raw_query.lower() for t in ["-men", "-women", "unisex", "gender-neutral"]):
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

    # ----------------------------
    # Keep your consult / merge utils as-is (optional)
    # ----------------------------
    def consult(self, current_outfit_context: dict, user_question: str) -> str:
        system_prompt = f"""
        You are a collaborative Personal Stylist.
        The user has a question or comment about the current outfit recommendation.

        CONTEXT (The current outfit):
        {json.dumps(current_outfit_context, indent=2)}

        YOUR GOAL:
        1) Answer the specific question honestly.
        2) Explain styling logic if needed.
        3) End with a helpful "Next Step" question.

        Keep it conversational, warm, and concise. Do NOT generate JSON.
        """.strip()

        return self.client.call_api(
            model=Config.OPENAI_MODEL_FAST,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_question},
            ],
            temperature=0.7,
        )

    def merge_conversation_state(self, current_state, new_refinement_delta):
        if "refinement_signals" not in current_state:
            current_state["refinement_signals"] = {}
        target_dict = current_state["refinement_signals"]
        self._smart_update(target_dict, new_refinement_delta)
        return current_state

    def _safe_merge(self, list_a, list_b):
        unique_items = list(list_a)
        for item in list_b:
            if item not in unique_items:
                unique_items.append(item)
        return unique_items

    def _smart_update(self, current_data, new_data):
        for key, new_val in new_data.items():
            if key not in current_data:
                current_data[key] = new_val
                continue
            old_val = current_data[key]
            if isinstance(old_val, list) and isinstance(new_val, list):
                current_data[key] = self._safe_merge(old_val, new_val)
            elif isinstance(old_val, dict) and isinstance(new_val, dict):
                self._smart_update(old_val, new_val)
            else:
                current_data[key] = new_val
        return current_data
