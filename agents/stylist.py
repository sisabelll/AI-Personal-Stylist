import json
from typing import Dict, Optional, List

from core.config import Config, get_logger

logger = get_logger(__name__)
from services.client import OpenAIClient
from core.schemas import OutfitRecommendation, canon_category
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

        body_type = constraints.get("body_style_essence", "General")
        color_season = constraints.get("color_season") or constraints.get("personal_color") or "General"
        season = constraints.get("season", "General")

        color_guidelines = constraints.get("color_guidelines") or {}
        body_guidelines = constraints.get("body_guidelines") or {}

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
        inspo_fabrics = inspo.get("fabric_preferences") or []
        inspo_palette = inspo.get("color_palette") or []

        # Filter staples to wearable everyday items — exclude anything clearly formal/costume/statement
        # (e.g. couture gowns, fur coats, see-through tops for a casual dinner).
        # For high formality events, allow the full list; for casual/medium, keep only grounded items.
        _FORMAL_NOISE = {"gown", "couture", "fur", "see-through", "sheer", "vintage t-shirt", "album cover", "parachute"}
        raw_staples = inspo.get("wardrobe_staples") or []
        raw_statements = inspo.get("statement_pieces") or []
        if formality_level == "high":
            inspo_staples = raw_staples[:5]
            inspo_statements = raw_statements[:2]
        else:
            inspo_staples = [s for s in raw_staples if not any(noise in s.lower() for noise in _FORMAL_NOISE)][:4]
            # For casual/medium events, statements are too loud — pass none to avoid noise
            inspo_statements = []

        # feedback/edit signals
        feedback = situational_signals.get("feedback") or {}
        if hasattr(feedback, "model_dump"):
            feedback = feedback.model_dump()

        swap_requests_raw = self._get_swap_requests_raw(feedback)
        items_to_remove = situational_signals.get("items_to_remove") or []
        attribute_corrections = situational_signals.get("attribute_corrections", []) or []
        owned_anchors = situational_signals.get("owned_anchors") or []
        swap_constraints = situational_signals.get("swap_constraints") or {}

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

        EDITORIAL STANDARD (NON-NEGOTIABLE):
        Every outfit must have one clear HERO piece — the single item that makes the look memorable and intentional.
        A flat, forgettable outfit (e.g. plain jeans + plain tee + plain sneakers with no point of view) is ALWAYS wrong.
        Reject safe and predictable. Every recommendation must feel deliberate, stylish, and screenshot-worthy.
        If you cannot identify a hero, the outfit is not good enough — revise your choices before outputting.

        You must return STRICT JSON that matches the OutfitRecommendation schema.
        For each item:
            - why_short: ONE sentence (max 110 characters). Must be specific (fit/color/hero/trend).
            - reason: optional. If present, 1-3 short bullets max. No paragraphs.

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

        # Inspiration knowledge graph — omit if user explicitly says to ignore it
        inspo_ctx = situational_signals.get("inspiration_context") or {}
        _ignore_inspo_phrases = ("ignore my inspiration", "don't use my inspiration", "without inspiration", "fresh start")
        _ignore_inspo = any(p in (user_query or "").lower() for p in _ignore_inspo_phrases)
        taste_block = ""
        if inspo_ctx and not _ignore_inspo:
            icons_line = ", ".join(inspo_ctx.get("seed_icons") or []) or "N/A"
            similar_line = ", ".join(inspo_ctx.get("similar_icons") or []) or "N/A"
            brands_line = ", ".join(inspo_ctx.get("seed_brands") or []) or "N/A"
            motifs_line = "\n".join(
                f"  - {m}" for m in (inspo_ctx.get("top_motifs") or [])
            ) or "  N/A"
            taste_block = f"""
            TASTE INTELLIGENCE (from user's inspiration board — always active unless user says to ignore)
            Use this to infer aesthetic lane and make choices feel personally resonant, even when the user
            hasn't named a specific reference. Do NOT cosplay these icons — translate their essence.

            Style icons the user resonates with: {icons_line}
            Similar icons with aligned taste: {similar_line}
            Brands they gravitate toward: {brands_line}
            Recurring styling motifs (prioritize these silhouettes/moves when relevant):
{motifs_line}
            """.strip()

        trend_context = situational_signals.get("trend_context") or {}
        trend_block = ""
        trend_cards = trend_context.get("trend_cards") or []
        if trend_cards:
            trend_block = f"""
            TREND CONTEXT (USE SPARINGLY)
            - Trend budget: 1 trend-forward element max unless user explicitly asks for "very trendy".
            - Only use trends if they improve taste AND fit the user's color season/body lines.
            - Prefer subtle, modern updates (silhouette/texture/finishing) over gimmicks.
            - If a card has "for_your_body_essence" or "for_your_color_season", prioritize those versions.

            {json.dumps(trend_cards, ensure_ascii=False)}
            """.strip()

        context_block = f"""
        CONTEXT
        - Season: {season}
        - Event: {event_raw}
        - Formality: {formality_text}
        - Social tone: {social_tone or "N/A"}
        - Aesthetic bias: {aesthetic_bias or "N/A"}
        - Vibe modifiers: {", ".join(vibe_modifiers) if vibe_modifiers else "N/A"}
        - Body lines: see BODY ESSENCE RULES below — apply to every silhouette and fabric choice
        - Color: see COLOR SEASON RULES below — apply to every item
        - Items to avoid/remove: {", ".join(items_to_remove) if items_to_remove else "N/A"}
        """.strip()

        # Build color season rules block from full guidelines
        color_rules_block = ""
        if color_guidelines:
            sub_types = color_guidelines.get("sub_types") or {}
            all_prefer, all_avoid, all_strategies, all_fabric_tips = [], [], [], []
            for st in sub_types.values():
                all_prefer.extend(st.get("prefer") or [])
                all_avoid.extend(st.get("avoid") or [])
                if st.get("styling_strategy"):
                    all_strategies.append(st["styling_strategy"])
                if st.get("fabric_pattern_tips"):
                    all_fabric_tips.append(st["fabric_pattern_tips"])
            # Deduplicate while preserving order
            all_prefer = list(dict.fromkeys(all_prefer))
            all_avoid = list(dict.fromkeys(all_avoid))
            color_rules_block = f"""
COLOR SEASON RULES — {color_season} ({color_guidelines.get("overall_type", "")}) — MANDATORY
Characteristic: {color_guidelines.get("main_characteristic", "")}
PREFERRED COLORS: {", ".join(all_prefer) if all_prefer else "N/A"}
COLORS TO AVOID: {", ".join(all_avoid) if all_avoid else "N/A"}
STYLING STRATEGIES:
{chr(10).join(f"  - {s}" for s in all_strategies if s)}
FABRIC & HARDWARE TIPS:
{chr(10).join(f"  - {f}" for f in all_fabric_tips if f)}
RULE: Every item's color must align with {color_season}. Any deviation requires explicit justification in the item's reason field.
            """.strip()

        # Build body essence rules block from full guidelines
        body_rules_block = ""
        if body_guidelines:
            pref = body_guidelines.get("preferred_elements") or {}
            avoid_el = body_guidelines.get("avoid_elements") or {}
            body_rules_block = f"""
BODY ESSENCE RULES — {body_type} ({body_guidelines.get("type_name", "")}) — MANDATORY
Styling Principle: {body_guidelines.get("styling_principle", "")}
Silhouette Intent: {body_guidelines.get("silhouette_intent", "")}
PREFERRED:
  - Fabrics: {pref.get("fabric_and_texture", "N/A")}
  - Silhouette/Fit: {pref.get("fit_and_silhouette", "N/A")}
  - Details: {pref.get("details_and_accessories", "N/A")}
AVOID:
  - Fabrics: {avoid_el.get("fabric_and_texture", "N/A")}
  - Silhouette/Fit: {avoid_el.get("fit_and_silhouette", "N/A")}
  - Details: {avoid_el.get("details_and_accessories", "N/A")}
RULE: Every silhouette and fabric choice must reflect {body_type} principles. Items that violate these rules must be replaced.
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

            SWAP ITEM REQUIREMENTS (user specified exact item type — you MUST honor these):
            {json.dumps(swap_constraints, ensure_ascii=False) if swap_constraints else "none"}
            When a category has a swap requirement, the new item MUST be that specific type (e.g. if Bottom requires "skirt", generate a skirt — NOT leggings, pants, or shorts).

            ATTRIBUTE CORRECTIONS (DO NOT CHANGE CATEGORY):
            {json.dumps(attribute_corrections, ensure_ascii=False)}

            RULES:
            1) If a category is NOT in swap_out, you MUST copy its item_name and search_query verbatim.
            2) Swap requirements override your styling judgment — honor the exact item type the user asked for.
            3) Attribute corrections DO NOT unlock swaps; they only adjust descriptors for the SAME category/type.
            4) Clothing physics applies (OnePiece cannot coexist with Top+Bottom).
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
        Only mark owned=true IF the user explicitly said it's theirs (“my”, “I own”, “in my closet”).
        If owned=true, reason MUST start with “[OWNED]”.'
        """.strip()

        system_prompt = "\n\n".join(
            filter(bool, [base_block, program_block, taste_block, inspiration_block, trend_block, context_block, color_rules_block, body_rules_block, edit_block, physics_block])
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
            temperature=0.45,
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

    def _enforce_one_piece_physics(self, items: List[dict], onepiece_requested: bool = False) -> List[dict]:
        """
        Enforce OnePiece/separates mutual exclusion.
        - onepiece_requested=True  → keep OnePiece, remove Top/Bottom
        - onepiece_requested=False → keep separates, remove OnePiece
        """
        cats = {canon_category(it.get("category")) for it in items}
        has_top = "Top" in cats
        has_bottom = "Bottom" in cats
        has_onepiece = "OnePiece" in cats

        if has_onepiece and (has_top or has_bottom):
            if onepiece_requested:
                return [it for it in items if canon_category(it.get("category")) not in {"Top", "Bottom"}]
            return [it for it in items if canon_category(it.get("category")) != "OnePiece"]

        return items

    def _get_swap_requests_raw(self, feedback: dict) -> List[str]:
        if not feedback:
            return []
        # Use the expanded swap_out so the LLM prompt shows all unlocked categories
        # (e.g. OnePiece swap → show ["Bottom", "OnePiece", "Top"] so there's no
        # contradiction between the "Top is locked" edit rule and physics).
        return feedback.get("swap_out") or []

    def _stabilize_outfit(
        self,
        new_items: List[dict],
        old_items: List[dict],
        swap_requests: List[Category],
        onepiece_requested: bool = False,
    ) -> List[dict]:
        """
        Lock categories not in swap_requests to their old item (item_name + search_query).
        swap_requests is the expanded unlock set (may include OnePiece added for removal).
        onepiece_requested must be passed explicitly — derived from swap_out_raw, not the
        expanded swap_requests, so "I want pants" (which auto-adds OnePiece to unlock it)
        doesn't mistakenly treat the request as a OnePiece swap.
        """
        raw_swaps = [canon_category(x) for x in (swap_requests or []) if canon_category(x) != "Unknown"]
        swap_set = set(raw_swaps)

        old_cats = {canon_category(it.get("category")) for it in (old_items or [])}

        # If old outfit is OnePiece and user wants Top/Bottom, we must allow OnePiece to change too.
        if (("Top" in swap_set) or ("Bottom" in swap_set)) and (("OnePiece" in old_cats)):
            swap_set |= {"OnePiece"}

        # Your existing rule (good): if OnePiece is being swapped, allow Top/Bottom too.
        if onepiece_requested:
            swap_set |= {"Top", "Bottom"}

        old_cats = {canon_category(it.get("category")) for it in (old_items or [])}
        logger.debug("Stabilize | old=%s requested=%s swap_set=%s", sorted(old_cats), sorted(raw_swaps), sorted(swap_set))

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
        # Keep negatives tight — domain restriction handles quality, not keyword stuffing.
        # Do NOT add editorial/lookbook terms: they attract blog listicles and roundup articles
        # instead of actual product images on restricted fashion retailer domains.
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
                logger.debug("Gender query: %s", item.search_query)

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

