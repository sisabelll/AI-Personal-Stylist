import json
from typing import Any, Dict, List

from core.config import Config, get_logger
from core.schemas import RefinementAnalysis, canon_category

logger = get_logger(__name__)


class RefinementAgent:
    def __init__(self, client):
        self.client = client

    # ----------------------------
    # Canonicalization
    # ----------------------------
    # ----------------------------
    # Context builder
    # ----------------------------
    def _build_outfit_context(self, current_outfit: dict) -> Dict[str, Any]:
        """
        Send minimal current outfit context (category + item_name only) to prevent rewriting.
        """
        ctx = {"items": []}
        try:
            if current_outfit and isinstance(current_outfit, dict) and current_outfit.get("outfit_options"):
                items = current_outfit["outfit_options"][0].get("items", [])
                out = []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    out.append({
                        "category": canon_category(it.get("category")),
                        "item_name": it.get("item_name"),
                    })
                ctx["items"] = out
        except Exception:
            ctx = {"items": []}
        return ctx

    # ----------------------------
    # Post-process directives -> legacy fields
    # ----------------------------
    def _repair_anchor_owned(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure anchor_owned has:
          - item_name present
          - must_include contains exact phrase as single element
        """
        must_include = [x for x in (d.get("must_include") or []) if isinstance(x, str) and x.strip()]
        must_avoid = [x for x in (d.get("must_avoid") or []) if isinstance(x, str) and x.strip()]
        item_name = (d.get("item_name") or "").strip()

        # Best-effort fallback if model omitted item_name
        if not item_name and must_include:
            item_name = must_include[0].strip()
            d["item_name"] = item_name

        # Enforce exact phrase in must_include as a single element
        if item_name:
            # put item_name first, and remove duplicates
            rest = [x for x in must_include if x != item_name]
            d["must_include"] = [item_name] + rest
        else:
            d["must_include"] = must_include

        d["must_avoid"] = must_avoid
        return d

    def _derive_legacy_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Derive:
          - swap_out (categories to change)
          - owned_anchors (forced items)
          - attribute_corrections (descriptor changes)
        from item_directives deterministically.
        """
        directives = data.get("item_directives") or []

        swap_out: List[str] = []
        swap_constraints: Dict[str, List[str]] = {}  # category -> must_include for swap_category intents
        owned_anchors: List[Dict[str, Any]] = []
        attribute_corrections: List[Dict[str, Any]] = []

        seen_swap = set()
        seen_anchor_keys = set()
        seen_corr_keys = set()

        for raw in directives:
            d = raw.model_dump(exclude_none=True) if hasattr(raw, "model_dump") else raw
            if not isinstance(d, dict):
                continue

            intent = (d.get("intent") or "").strip()
            target = canon_category(d.get("target_category"))

            if target in {"Unknown", "Outfit"}:
                continue

            must_include = d.get("must_include") or []
            must_avoid = d.get("must_avoid") or []
            note = d.get("note")

            if intent == "swap_category":
                if target not in seen_swap:
                    swap_out.append(target)
                    seen_swap.add(target)
                if must_include:
                    swap_constraints.setdefault(target, [])
                    for term in must_include:
                        if term not in swap_constraints[target]:
                            swap_constraints[target].append(term)

            elif intent == "attribute_update":
                # This does NOT unlock swap_out; it just adjusts descriptors
                key = (target, tuple(must_include), tuple(must_avoid), note or "")
                if key not in seen_corr_keys:
                    attribute_corrections.append({
                        "target_category": target,
                        "must_include": [x for x in must_include if x],
                        "must_avoid": [x for x in must_avoid if x],
                        "note": note,
                    })
                    seen_corr_keys.add(key)

            elif intent == "anchor_owned":
                # Your desired behavior: anchor_owned implies inclusion,
                # therefore it should also add that category to swap_out.
                d = self._repair_anchor_owned(d)

                item_name = (d.get("item_name") or "").strip()
                must_include = d.get("must_include") or []
                must_avoid = d.get("must_avoid") or []
                key = (target, item_name, tuple(must_include), tuple(must_avoid), note or "")

                if key not in seen_anchor_keys:
                    owned_anchors.append({
                        "target_category": target,
                        "item_name": item_name,
                        "must_include": must_include,
                        "must_avoid": must_avoid,
                        "note": note,
                    })
                    seen_anchor_keys.add(key)

                if target not in seen_swap:
                    swap_out.append(target)
                    seen_swap.add(target)

            elif intent == "new_outfit":
                # no legacy fields needed, but keep the directive itself
                pass

        data["swap_out"] = swap_out
        data["swap_constraints"] = swap_constraints
        data["owned_anchors"] = owned_anchors
        data["attribute_corrections"] = attribute_corrections
        return data

    # ----------------------------
    # Main
    # ----------------------------
    def analyze_feedback(self, current_outfit: dict, user_input: str) -> Dict[str, Any]:
        system_prompt = """
        You are an expert fashion editor interpreting user feedback on an outfit.

        You will receive:
        1) Current Outfit Context (JSON)
        2) User Feedback (Natural Language)

        Return STRICT JSON that matches the RefinementAnalysis schema.

        INTENT RULES:

        swap_category — any signal that an item should NOT remain in the outfit (dislike,
        unavailability, preference, removal, substitution, hypothetical swap). If the user
        would not wear this item, replace it.

        attribute_update — user wants to KEEP the item type but change a descriptor only
        (color, fit, material). Use only when they are happy with the category itself.

        anchor_owned — user owns a specific item and wants to build around it
        (“my white sneakers”, “I want to wear my leather jacket”). Requires item_name.

        new_outfit — user asks to start completely over.

        CATEGORY MAPPING (map item names to canonical categories):
        - pants/jeans/trousers/slacks/skirt/shorts → Bottom
        - top/blouse/shirt/tee/sweater/sweatshirt/hoodie → Top
        - dress/gown/jumpsuit/one-piece → OnePiece
        - shoes/boots/sneakers/heels/flats/sandals/loafers → Shoes
        - blazer/jacket/coat/cardigan/vest/trench/bomber → Outerwear
        - bag/jewelry/earrings/necklace/bracelet/belt/hat/scarf → Accessory

        STYLE: must_include/must_avoid are short tokens (1–4 words). No brands unless stated.
        """.strip()

        outfit_context = self._build_outfit_context(current_outfit)

        try:
            result_obj = self.client.call_api(
                model=Config.OPENAI_MODEL_FAST,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps({
                        "current_outfit_context": outfit_context,
                        "user_feedback": user_input,
                    }, ensure_ascii=False)},
                ],
                response_model=RefinementAnalysis,
            )

            data = result_obj.model_dump(exclude_none=True) if hasattr(result_obj, "model_dump") else (result_obj or {})

            # Canonicalize categories inside directives too (defensive)
            directives = data.get("item_directives") or []
            cleaned_directives = []
            for raw in directives:
                d = raw.model_dump(exclude_none=True) if hasattr(raw, "model_dump") else raw
                if not isinstance(d, dict):
                    continue
                if "target_category" in d:
                    d["target_category"] = canon_category(d.get("target_category"))
                cleaned_directives.append(d)
            data["item_directives"] = cleaned_directives

            # Derive legacy fields deterministically
            data = self._derive_legacy_fields(data)

            logger.debug("directives=%s swap_out=%s owned_anchors=%s attribute_corrections=%s",
                         data.get("item_directives"), data.get("swap_out"),
                         data.get("owned_anchors"), data.get("attribute_corrections"))
            return data

        except Exception as e:
            logger.error("Refiner error: %s", e)
            return {
                "make_more": [],
                "make_less": [],
                "swap_out": [],
                "emotional_goal": None,
                "expressed_likes": [],
                "expressed_dislikes": [],
                "item_directives": [],
                "attribute_corrections": [],
                "owned_anchors": [],
            }
