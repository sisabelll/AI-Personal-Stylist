import json
import os
import time
from datetime import datetime
import traceback
from typing import Dict, Any, Optional, List
import re
from collections import Counter

# --- AGENTS & CORE ---
from core.schemas import UserActionType, StyleInterpretation, OutfitCritique, EditPlan, EditAction, canon_category
from core.style_program_schemas import StyleProgram

from agents.interpreter import ContextInterpreter, StyleConstraintBuilder
from agents.stylist import StyleStylist
from agents.style_researcher import StyleResearcherAgent
from agents.refiner import RefinementAgent
from agents.style_program import StyleProgramBuilder
from agents.editor import EditorAgent

# --- SERVICES ---
from services.catalog import CatalogClient
from services.trends_retriever import TrendsRetriever, simple_rank, build_trend_context_pack

class ConversationManager:
    def __init__(self, client, user_profile, style_rules, storage=None, dev_mode=False):
        self.client = client
        self.user_profile = user_profile
        self.storage = storage
        self.dev_mode = dev_mode
        self.ux_callback = None

        # 1. Initialize Static Rules (The "Librarian")
        builder = StyleConstraintBuilder(user_profile, style_rules)
        self.static_constraints = builder.build()

        # 2. Initialize Agents
        self.interpreter = ContextInterpreter(client)
        self.stylist = StyleStylist(client)
        self.researcher = StyleResearcherAgent(client)
        self.refiner_agent = RefinementAgent(client)
        self.catalog = CatalogClient()
        self.style_program_builder = StyleProgramBuilder()
        self.editor = EditorAgent(client)

        # 3. Initialize State
        self.current_context: Dict[str, Any] = {}
        self.conversation_state: Dict[str, Any] = {
            "current_recommendation": None,
            "refinement_signals": {},   # store latest refine signals (for debugging / future use)
            "anchored_items": [],
            "history": [],
            "revisions": [],
            "last_critique": None,
        }

        # 4. Local Snapshot Config (Debugging only)
        self.snapshot_dir = os.path.join(".", "snapshots")
        os.makedirs(self.snapshot_dir, exist_ok=True)

    # ====================================================
    # ✅ SMALL INVARIANTS / HELPERS
    # ====================================================
    def _ux(self, message: str, phase: str = "info"):
        cb = getattr(self, "ux_callback", None)
        if not cb:
            return

        cb({
            "message": message,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
        })

    def _dump(self, x):
        return x.model_dump() if hasattr(x, "model_dump") else x

    def _base_signals(self) -> Dict[str, Any]:
        hard = self.current_context.get("hard_constraints", {}) or {}
        return {
            "external_inspiration": self.current_context.get("external_style_inspiration", {}) or {},
            "event_type": hard.get("event_type") or self.current_context.get("event_type"),
            "weather": hard.get("weather"),
            "location": self.user_profile.get("location_city", "NYC"),
            "aesthetic": self.current_context.get("aesthetic_bias", "clean_chic"),
            # optional passthrough for stylist prompt/debug
            "style_interpretation": self.current_context.get("style_interpretation", {}) or {},
        }

    def _get_current_outfit_items(self) -> List[Dict[str, Any]]:
        rec = self.conversation_state.get("current_recommendation") or {}
        if isinstance(rec, dict) and rec.get("outfit_options"):
            return (rec["outfit_options"][0].get("items") or [])
        return []

    # ====================================================
    # 🚀 SESSION ENTRY POINTS
    # ====================================================
    @property
    def current_outfit(self):
        """Helper to access the current recommendation safely."""
        return self.conversation_state.get("current_recommendation", {}) or {}

    def start_new_session(self, user_request_context, user_query, status_callback=None, use_cache=None):
        """Initializes a session by interpreting the raw request."""
        if use_cache is None:
            use_cache = self.dev_mode

        # 1) CACHE CHECK (Developer Mode)
        if use_cache:
            snapshot_data = self._load_snapshot("debug_session.json")
            if snapshot_data:
                self.current_context = snapshot_data.get("context", {}) or {}
                self.conversation_state = snapshot_data.get("conversation_state", {}) or self.conversation_state
                if status_callback:
                    status_callback("⚡ Loaded cached outfit from snapshot.")
                return self.conversation_state.get("current_recommendation")

        print(f"🚀 Starting new session: '{user_query}'")

        # 2) INTERPRET INPUT (ContextInterpreter belongs here)
        self._ux("🧠 Understanding your request…", phase="intent")

        interpretation: StyleInterpretation = self.interpreter.interpret(user_request_context, user_query)
        new_signals = self._dump(interpretation) or {}
        self.current_context = self._smart_update(self.current_context, new_signals)

        # 3) RESEARCHER (Check for External Inspiration)
        self._check_and_run_research(status_callback)

        # 4) RESET STATE FOR NEW LOOK
        self.conversation_state["current_recommendation"] = None
        self.conversation_state["refinement_signals"] = {}
        self.conversation_state["anchored_items"] = self.current_context.get("requested_items", []) or []
        self.conversation_state["revisions"] = []
        self.conversation_state["last_critique"] = None

        if status_callback:
            status_callback("🎨 Synthesizing outfit recommendation...")

        # 5) GENERATE OUTFIT
        situational_signals = self._base_signals()
        situational_signals["edit_mode"] = False

        trend_context = self._get_trend_context(situational_signals, user_query)
        if trend_context:
            situational_signals["trend_context"] = trend_context
            print(f"📈 Trend context attached: cards={len(trend_context.get('selected_trends', []))} tags={trend_context.get('retrieval_tags')}")
            
        self._log_trend_context(situational_signals)

        final_obj, critique, draft_obj = self._generate_with_editor_pass(
            user_query=user_query,
            situational_signals=situational_signals,
            current_outfit_items=None,
            revise_threshold=8,
            store_threshold=9,
            version="editor_v1",
        )

        self.conversation_state["last_critique"] = self._dump(critique)
        recommendation = self._dump(final_obj)

        # 6) VISUAL SEARCH
        print("🛍️ Searching for products...")
        if recommendation.get("outfit_options"):
            items_to_search = recommendation["outfit_options"][0].get("items", []) or []
            self.catalog.search_products_parallel(items_to_search)

        # 7) SAVE STATE & RETURN
        self._ux("✨ Your look is ready.", phase="finalize")

        self.conversation_state["current_recommendation"] = recommendation
        self.conversation_state["history"].append(
            {"role": "assistant", "content": recommendation.get("reasoning", "Here is your look.")}
        )

        self._save_snapshot()
        return recommendation

    def refine_session(self, user_feedback_text):
        """Routes the user to either 'Action' (Generate) or 'Consultation' (Chat)."""

        print(f"🤔 Classifying intent: '{user_feedback_text}'")
        self._ux("🧠 Reading between the lines…", phase="intent")
        intent_action = self.interpreter.classify_intent(user_feedback_text)
        print(f"🚦 Route Detected: {intent_action}")

        # IMPORTANT SEPARATION:
        # - We do NOT run ContextInterpreter.interpret() here.
        # - RefinementAgent is the only source of swap/anchor/correction directives.

        # --- ROUTE A: CONSULTATION ---
        if intent_action == UserActionType.ASK_QUESTION:
            current_outfit = self.conversation_state.get("current_recommendation", {}) or {}
            advice_text = self.stylist.consult(current_outfit, user_feedback_text)
            self._update_history(user_feedback_text, advice_text)
            return advice_text

        # --- ROUTE B: FINALIZATION ---
        elif intent_action == UserActionType.FINALIZE_OUTFIT:
            success_msg = "🎉 Saved to your history! Have an amazing time."
            self._update_history(user_feedback_text, success_msg)
            return success_msg

        # --- ROUTE C: RESET ---
        elif intent_action == UserActionType.RESET_SESSION:
            return self.start_new_session({}, "Let's start fresh.")

        # --- ROUTE D: NEW OUTFIT ---
        elif intent_action == UserActionType.NEW_OUTFIT:
            print("🧼 NEW_OUTFIT detected -> regenerate from scratch")

            situational_signals = self._base_signals()
            situational_signals["edit_mode"] = False
            situational_signals["force_new_outfit"] = True

            trend_context = self._get_trend_context(situational_signals, user_feedback_text)
            if trend_context:
                situational_signals["trend_context"] = trend_context
                print(f"📈 Trend context attached (refine): cards={len(trend_context.get('selected_trends', []))}")

            self._log_trend_context(situational_signals)

            final_obj, critique, draft_obj = self._generate_with_editor_pass(
                user_query=user_feedback_text,
                situational_signals=situational_signals,
                current_outfit_items=None,
                revise_threshold=8,
                store_threshold=9,
                version="editor_v1",
            )

            self.conversation_state["last_critique"] = self._dump(critique)
            recommendation = self._dump(final_obj)

            self.conversation_state["current_recommendation"] = recommendation
            self._save_snapshot()
            return recommendation

        # --- ROUTE E: MODIFICATION (Standard) ---
        else:
            new_outfit = self._refine_look(user_feedback_text)
            self.conversation_state["current_recommendation"] = new_outfit
            return new_outfit

    # ====================================================
    # 🧠 CORE LOGIC
    # ====================================================
    def build_trend_context_terms(
        self,
        user_profile: dict,
        situational_signals: dict,
        user_query: str,
        outfit_items = None,
        max_terms: int = 12,
    ) -> list[str]:
        terms: list[str] = []

        # Style interpretation
        interp = situational_signals.get("style_interpretation") or {}
        if isinstance(interp, dict):
            if interp.get("aesthetic_bias"):
                terms.append(str(interp["aesthetic_bias"]))
            terms += [str(x) for x in (interp.get("vibe_modifiers") or []) if x]

        # User profile anchor
        cs = user_profile.get("color_season") or user_profile.get("personal_color")
        if cs:
            terms.append(str(cs).replace(" ", "_").lower())

        be = user_profile.get("body_style_essence")
        if be:
            terms.append(str(be).replace(" ", "_").lower())

        # Dedup + cap
        seen = set()
        out = []
        for t in terms:
            t = (t or "").strip().lower()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= max_terms:
                break

        return out


    def _get_trend_context(self, situational_signals: dict, user_query: str) -> dict:
        """
        Pull a SMALL pack of trend notes relevant to this request.
        Returns {} if storage/trends not available.
        """
        if not self.storage:
            return {}

        try:
            wear_pref = (self.user_profile.get("wear_preference") or "unisex").lower()
            # optional: map "Unisex" -> "unisex"
            season = self.current_context.get("season") or self._infer_season()

            current_items = self._get_current_outfit_items() or []

            context_terms = self.build_trend_context_terms(
                user_profile=self.user_profile,
                situational_signals=situational_signals,
                user_query=user_query,
                outfit_items=current_items,
                max_terms=12,
            )

            retriever = TrendsRetriever(self.storage)
            cards = retriever.fetch_recent(season=season, wear_pref=wear_pref, limit=40)

            ranked = simple_rank(cards, context_terms, top_k=8)
            return build_trend_context_pack(ranked, max_cards=6)
        except Exception as e:
            print(f"⚠️ Trend retrieval failed: {e}")
            print(traceback.format_exc())
            return {}

    def _generate_with_editor_pass(
        self,
        user_query: str,
        situational_signals: dict,
        current_outfit_items: list = None,
        revise_threshold: int = 8,
        store_threshold: int = 9,
        store_all: bool = False,
        version: str = "editor_v1",
    ):
        style_program = self._build_style_program(
            situational_signals=situational_signals,
            user_query=user_query,
        )
        signals = dict(situational_signals)

        print("\n🧵 ================= EDITOR PIPELINE =================")

        # 1) Draft
        self._ux("🎨 Balancing silhouette, color, and vibe…", phase="generation")
        draft_obj = self.stylist.recommend(
            constraints=self.user_profile,
            situational_signals=signals,
            user_query=user_query,
            current_outfit=current_outfit_items,
            style_program=style_program,
        )
        draft_obj = self._postprocess_outfit(draft_obj, current_outfit_items, signals)

        try:
            self._qa_physics(draft_obj)
        except Exception as e:
            print(f"⚠️ QA Physics check failed (draft): {e}")

        print("🟡 Draft generated")

        # 1.5) Swap compliance check (edit mode)
        swap_violations = {"missing": [], "forbidden": [], "unchanged": []}
        if signals.get("edit_mode"):
            fb = signals.get("feedback") or {}
            swap_out = fb.get("swap_out") or []
            swap_out_raw = fb.get("swap_out_raw") or swap_out
            swap_violations = self._check_swap_requirements(
                outfit_obj=draft_obj,
                current_outfit_items=current_outfit_items,
                swap_out=swap_out,
                swap_out_raw=swap_out_raw,
            )
            if swap_violations["missing"] or swap_violations["forbidden"] or swap_violations["unchanged"]:
                print(
                    "⚠️ Swap compliance failed (draft). "
                    f"Missing: {swap_violations['missing']} "
                    f"Forbidden: {swap_violations['forbidden']} "
                    f"Unchanged: {swap_violations['unchanged']}"
                )

        # 2) Critique (SAFE)
        try:
            self._ux("✍️ Checking if this outfit reaches editor-level quality…", phase="editor")
            critique = self.editor.critique(
                outfit=draft_obj,
                user_profile=self.user_profile,
                situational_signals=signals,
            )
        except Exception as e:
            print(f"⚠️ Editor critique failed: {e}")
            print(traceback.format_exc())
            critique = OutfitCritique(
                score=7,
                verdict="accept",
                summary="Editor unavailable; returning draft.",
                main_issue="Editor error",
                plan=EditPlan(hero="N/A", actions=[]),
            )

        print("🧠 Editor critique")
        print(f"   Score: {critique.score}/10")
        print(f"   Verdict: {critique.verdict}")
        print(f"   Main issue: {critique.main_issue}")

        # --- Gate editor swaps in edit_mode to only allowed categories ---
        fb = signals.get("feedback") or {}
        swap_out = fb.get("swap_out") or []
        allowed = {canon_category(s) for s in swap_out if s}

        # Force a revision if swap requirements failed
        if signals.get("edit_mode") and (swap_violations["missing"] or swap_violations["forbidden"] or swap_violations["unchanged"]):
            actions = []
            for cat in (swap_violations["missing"] + swap_violations["forbidden"] + swap_violations["unchanged"])[:2]:
                if cat in swap_violations["missing"]:
                    actions.append(
                        {
                            "target_category": cat,
                            "action_type": "swap",
                            "instruction": f"Required by swap request: include a {cat}.",
                        }
                    )
                else:
                    if cat in swap_violations["forbidden"]:
                        actions.append(
                            {
                                "target_category": cat,
                                "action_type": "remove",
                                "instruction": f"Forbidden by swap request: remove {cat}.",
                            }
                        )
                    else:
                        actions.append(
                            {
                                "target_category": cat,
                                "action_type": "swap",
                                "instruction": f"Swap requested but output did not change {cat}. Provide a different item.",
                            }
                        )
            critique = OutfitCritique(
                score=5,
                verdict="revise",
                summary="Swap compliance failed.",
                main_issue="Output did not satisfy swap request categories.",
                plan=EditPlan(hero="swap compliance", actions=[EditAction(**a) for a in actions]),
            )

        if signals.get("edit_mode") and allowed and getattr(critique, "plan", None) and critique.plan.actions:
            planned = {canon_category(a.target_category) for a in critique.plan.actions if getattr(a, "target_category", None)}
            # If editor doesn't touch any allowed category, ignore revision.
            if not (planned & allowed):
                critique.verdict = "accept"

        # 3) Optional revise
        final_obj = draft_obj

        if critique.verdict == "revise" and critique.score <= revise_threshold and critique.plan.actions:
            print("🔁 Revision TRIGGERED")

            self._ux("✍️ Refining the outfit for stronger impact…", phase="editor")

            revised_signals = dict(signals)
            revised_signals["editor_plan"] = self._dump(critique.plan)

            final_obj = self.stylist.recommend(
                constraints=self.user_profile,
                situational_signals=revised_signals,
                user_query=user_query,
                current_outfit=current_outfit_items,
                style_program=style_program,
            )
            final_obj = self._postprocess_outfit(final_obj, current_outfit_items, revised_signals)
            print("✅ Revision applied")
        else:
            self._ux("✍️ Editor approved — locking in the look.", phase="editor")
            print("⏭️ No revision needed")

        # ✅ Check FINAL, not draft again
        try:
            self._qa_physics(final_obj)
        except Exception as e:
            print(f"⚠️ QA Physics check failed (final): {e}")

        # 4) Log revisions (SAFE)
        self.conversation_state.setdefault("revisions", []).append(
            {
                "input": user_query,
                "situational_signals": signals,
                "draft": self._dump(draft_obj),
                "critique": self._dump(critique),
                "final": self._dump(final_obj),
                "final_score": critique.score,
                "accepted": critique.score >= store_threshold,
                "version": version,
            }
        )

        # 5) Store to Supabase (optional)
        accepted = critique.score >= store_threshold
        if self.storage and (store_all or accepted):
            try:
                style_tags, lessons = self._derive_tags_and_lessons(user_query, signals, critique, final_obj)
                row = {
                    "user_id": str(self.user_profile.get("id")),
                    "user_query": user_query,
                    "situational_signals": signals,
                    "draft_outfit": self._dump(draft_obj),
                    "critique": self._dump(critique),
                    "final_outfit": self._dump(final_obj),
                    "final_score": critique.score,
                    "accepted": bool(accepted),
                    "version": version,
                    "style_tags": style_tags,
                    "lessons": lessons,
                }
                self.storage.insert_styling_revision(row)
                print(f"✅ Stored in Supabase (accepted={accepted}, tags={len(style_tags)}, lessons={len(lessons)})")
            except Exception as e:
                print(f"⚠️ Supabase insert failed: {e}")

        print("🧵 =============== END EDITOR PIPELINE ===============\n")
        return final_obj, critique, draft_obj

    def _refine_look(self, user_text: str):
        """The 'Action' function for modification."""
        print(f"🔄 Refining look based on: '{user_text}'")

        current_data = self.conversation_state.get("current_recommendation", {}) or {}
        current_outfit_items = self._get_current_outfit_items() or []

        self._ux("🎛️ Interpreting your edit request…", phase="interpret")

        # 1) Analyze feedback (Refiner = ONLY about edit directives)
        feedback_analysis = self.refiner_agent.analyze_feedback(
            current_outfit=current_data,
            user_input=user_text,
        ) or {}

        self.conversation_state["refinement_signals"] = feedback_analysis

        # 2) Canonicalize swap_out
        swap_raw = feedback_analysis.get("swap_out") or []
        swap_raw_canon = [canon_category(s) for s in swap_raw if canon_category(s) != "Unknown"]
        feedback_analysis["swap_out_raw"] = list(swap_raw_canon)
        swap_set = set(swap_raw_canon)


        # 3) Canonicalize owned anchors
        owned_anchors = feedback_analysis.get("owned_anchors", []) or []
        for a in owned_anchors:
            if a.get("target_category"):
                a["target_category"] = canon_category(a.get("target_category"))
        feedback_analysis["owned_anchors"] = owned_anchors

        # 4) STRUCTURE-AWARE SWAP EXPANSION (template switching)
        old_cats = {canon_category((it.get("category") or "").strip()) for it in current_outfit_items}
        locked_cats = {canon_category(a.get("target_category")) for a in owned_anchors if a.get("target_category")}
        locked_cats.discard("Unknown")
        requested_items = self.current_context.get("requested_items", []) or []
        requested_cats = set()
        for item in requested_items:
            cat = canon_category(item)
            if cat != "Unknown":
                requested_cats.add(cat)
                continue
            for tok in re.split(r"[^a-z0-9]+", (item or "").lower()):
                if not tok:
                    continue
                tok_cat = canon_category(tok)
                if tok_cat != "Unknown":
                    requested_cats.add(tok_cat)
        locked_cats |= requested_cats
        if not swap_set:
            swap_set = {c for c in old_cats if c not in locked_cats and c != "Unknown"}
        swap_set = self._expand_swap_set(old_cats, swap_set)

        feedback_analysis["swap_out"] = sorted(swap_set)

        self._ux(f"🔁 Allowed swaps: {', '.join(feedback_analysis['swap_out']) or 'None'}", phase="generation")

        if owned_anchors:
            self._ux("🔒 Respecting your closet anchors…", phase="generation")

        # 5) Build situational signals for stylist
        situational_signals = self._base_signals()
        situational_signals.update(
            {
                "feedback": feedback_analysis,
                "items_to_remove": self.current_context.get("items_to_remove", []) or [],
                "requested_items": self.current_context.get("requested_items", []) or [],
                "attribute_corrections": feedback_analysis.get("attribute_corrections", []) or [],
                "edit_mode": True,
                "owned_anchors": owned_anchors,
            }
        )
        trend_context = self._get_trend_context(situational_signals, user_text)
        if trend_context:
            situational_signals["trend_context"] = trend_context
            print(f"📈 Trend context attached (refine): cards={len(trend_context.get('selected_trends', []))}")

        # 6) Generate with editor pass
        self._log_trend_context(situational_signals)
        self._ux("🎨 Updating the outfit…", phase="generation")
        final_obj, critique, draft_obj = self._generate_with_editor_pass(
            user_query=user_text,
            situational_signals=situational_signals,
            current_outfit_items=current_outfit_items,
            revise_threshold=8,
            store_threshold=9,
            version="editor_v1",
        )

        self.conversation_state["last_critique"] = self._dump(critique)
        new_recommendation = self._dump(final_obj)

        # 7) Product search (UX-visible)
        if new_recommendation.get("outfit_options"):
            items = new_recommendation["outfit_options"][0].get("items", []) or []

            print("🛍️ refine search items:")
            for it in items:
                print(" -", it.get("category"), "|", it.get("item_name"), "|", it.get("search_query"))

            self._ux("🛍️ Finding matching items…", phase="search")
            self.catalog.search_products_parallel(items)

        self._ux("✨ Done!", phase="finalize")
        self._save_snapshot()
        return new_recommendation

    def _check_and_run_research(self, status_callback=None):
        """Checks if a Style Icon needs to be researched."""
        chat_refs = self.current_context.get("style_references", []) or []

        profile_refs = []
        if "preferences" in self.user_profile:
            profile_refs = self.user_profile["preferences"].get("style_icons", []) or []

        all_refs = self._safe_merge(chat_refs, profile_refs)

        if all_refs:
            icon_name = all_refs[0]
            current_data = self.current_context.get("external_style_inspiration", {}) or {}
            existing_name = current_data.get("name", "") or ""

            if not current_data or (existing_name and existing_name.lower() != icon_name.lower()):
                if status_callback:
                    status_callback(f"🕵️‍♀️ Researching style icon: **{icon_name}**...")

                self._ux(f"🕵️‍♀️ Studying {icon_name}'s style references…", phase="reasoning")

                researched_data = self.researcher.get_profile(icon_name)
                self.current_context["external_style_inspiration"] = researched_data

    def _build_style_program(self, situational_signals: dict, user_query: str) -> StyleProgram:
        color = self.user_profile.get("color_season") or self.user_profile.get("personal_color") or "General"
        body = self.user_profile.get("body_style_essence") or "General"
        prefs = self.user_profile.get("preferences") or {}
        icons = prefs.get("style_icons") or []
        brands = prefs.get("favorite_brands") or []

        aesthetic = self.current_context.get("aesthetic_bias", situational_signals.get("aesthetic", "clean_chic"))
        vibe = (situational_signals.get("external_inspiration") or {}).get("vibe", "")

        constraints_summary = [
            f"Honor color season: {color}.",
            f"Honor body essence lines: {body}.",
        ]
        if aesthetic:
            constraints_summary.append(f"Aesthetic bias: {aesthetic}.")
        if icons:
            constraints_summary.append(f"Inspiration reference(s): {', '.join(icons[:2])}.")
        if brands:
            constraints_summary.append(f"Brand gravity (optional): {', '.join(brands[:3])}.")

        base_editorial_nos = [
            "No generic mall-basic stacks (must have a point of view).",
            "No more than one hero element (silhouette OR texture OR accessory).",
            "Avoid random warm browns near the face if user is Cool/Summer unless justified.",
            "Avoid proportion-breaking hems (esp. with mid-calf boots).",
        ]

        learned = []
        if self.storage:
            try:
                user_id = self.user_profile.get("id") or self.user_profile.get("user_id")
                tags, _ = self._derive_tags_and_lessons(user_query, situational_signals, critique_obj=None, final_obj=None)

                query_tags = self._select_retrieval_tags(tags, k=3)
                print(f"🔎 Retrieval tags: {query_tags}")

                resp = self.storage.fetch_accepted_revisions(user_id=user_id, tags=query_tags, limit=5)
                rows = getattr(resp, "data", None) or (resp.get("data") if isinstance(resp, dict) else []) or []
                print(f"📚 Retrieved {len(rows)} accepted revisions")

                for r in rows:
                    learned += (r.get("lessons") or [])

                deduped = []
                for l in learned:
                    if l and l not in deduped:
                        deduped.append(l)
                learned = deduped

                print(f"🧠 Injecting learned lessons: {learned[:5]}")
            except Exception as e:
                print(f"⚠️ Fetch revisions failed: {e}")
                print(traceback.format_exc())

        editorial_nos = (base_editorial_nos + learned)[:10]
        hero_strategy = "Choose exactly one hero move (proportion OR texture OR accessory) and keep the rest quiet."
        style_brief = (
            f"Create a stylish, intentional look (not generic). "
            f"Translate inspiration vibe ({vibe}) into wearable choices. "
            f"Make the outfit feel curated with one clear hero decision."
        )

        return StyleProgram(
            style_brief=style_brief,
            constraints_summary=constraints_summary,
            editorial_nos=editorial_nos,
            hero_strategy=hero_strategy,
            trend_budget=1,
        )

    def _check_swap_requirements(self, outfit_obj, current_outfit_items: list, swap_out: list, swap_out_raw: Optional[list] = None) -> dict:
        """
        Validate that output matches swap intent. Returns {"missing": [...], "forbidden": [...], "unchanged": [...]}.
        """
        old_cats = {canon_category((it.get("category") or "").strip()) for it in (current_outfit_items or [])}
        swap_set = {canon_category(s) for s in (swap_out or []) if s}
        swap_raw_set = {canon_category(s) for s in (swap_out_raw or []) if s}

        required = set()
        forbidden = set()

        if "OnePiece" in swap_raw_set:
            required |= {"OnePiece"}
            forbidden |= {"Top", "Bottom"}
        elif ("OnePiece" in old_cats) and (swap_raw_set & {"Top", "Bottom"}):
            required |= {"Top", "Bottom"}
            forbidden |= {"OnePiece"}
        else:
            required |= {c for c in swap_raw_set if c not in {"Top", "Bottom", "OnePiece"}}
            if "Top" in swap_raw_set:
                required.add("Top")
            if "Bottom" in swap_raw_set:
                required.add("Bottom")

        outfit_items = []
        try:
            if outfit_obj and getattr(outfit_obj, "outfit_options", None):
                outfit_items = outfit_obj.outfit_options[0].items
            elif isinstance(outfit_obj, dict):
                outfit_items = (outfit_obj.get("outfit_options") or [{}])[0].get("items") or []
        except Exception:
            outfit_items = []

        present = set()
        for it in (outfit_items or []):
            if not it:
                continue
            if hasattr(it, "model_dump"):
                data = it.model_dump()
                present.add(canon_category(data.get("category")))
            elif isinstance(it, dict):
                present.add(canon_category(it.get("category")))
            else:
                present.add(canon_category(getattr(it, "category", None)))

        missing = sorted(required - present)
        forbidden_present = sorted(forbidden & present)

        # Ensure swaps actually changed (item_name/search_query differ from old)
        unchanged = []
        if current_outfit_items and swap_raw_set:
            old_map = {}
            for it in (current_outfit_items or []):
                if not isinstance(it, dict):
                    continue
                cat = canon_category((it.get("category") or "").strip())
                if cat != "Unknown":
                    old_map[cat] = it

            for it in (outfit_items or []):
                data = it.model_dump() if hasattr(it, "model_dump") else (it if isinstance(it, dict) else {})
                cat = canon_category(data.get("category"))
                if cat in swap_raw_set and cat in old_map:
                    old = old_map[cat]
                    if (data.get("item_name") == old.get("item_name")) and (data.get("search_query") == old.get("search_query")):
                        unchanged.append(cat)

        return {"missing": missing, "forbidden": forbidden_present, "unchanged": sorted(set(unchanged))}

    def _expand_swap_set(self, old_cats: set, swap_set: set) -> set:
        """
        Expand swap categories for template switching without mutating caller sets.
        """
        expanded = set(swap_set)

        # A) If current outfit is OnePiece and user wants separates (Top/Bottom), unlock the switch
        if "OnePiece" in old_cats and (expanded & {"Top", "Bottom"}):
            expanded |= {"OnePiece", "Top", "Bottom"}

        # B) If current outfit is separates and user wants OnePiece, unlock Top+Bottom so they can be removed
        if ("Top" in old_cats or "Bottom" in old_cats) and ("OnePiece" in expanded):
            expanded |= {"Top", "Bottom"}

        # C) If user swaps OnePiece explicitly, also unlock Top/Bottom (so physics can settle cleanly)
        if "OnePiece" in expanded:
            expanded |= {"Top", "Bottom"}

        return expanded

    def _postprocess_outfit(self, outfit_obj, current_outfit_items: list, situational_signals: dict):
        """
        Apply deterministic category rules and constraints outside the stylist.
        """
        if not outfit_obj or not getattr(outfit_obj, "outfit_options", None):
            return outfit_obj

        option0 = outfit_obj.outfit_options[0]
        if not option0 or not option0.items:
            return outfit_obj

        item_cls = type(option0.items[0])
        items = [it.model_dump() if hasattr(it, "model_dump") else dict(it) for it in option0.items]
        self.stylist._canon_items_inplace(items)

        feedback = situational_signals.get("feedback") or {}
        owned_anchors = situational_signals.get("owned_anchors") or []
        attribute_corrections = situational_signals.get("attribute_corrections") or []

        swap_requests_raw = feedback.get("swap_out_raw") or feedback.get("swap_out") or []
        swap_requests = sorted({canon_category(x) for x in swap_requests_raw if canon_category(x) != "Unknown"})
        forced_from_anchors = sorted({canon_category(a.get("target_category")) for a in (owned_anchors or []) if canon_category(a.get("target_category")) != "Unknown"})
        swap_requests_for_prompt = sorted(set(swap_requests) | set(forced_from_anchors))

        # 1) Apply owned anchors FIRST (forces the category)
        items = self.stylist._apply_owned_anchors(items, owned_anchors)
        items = self.stylist._dedupe_one_per_category(items)

        # 2) Stabilize (locks)
        if current_outfit_items:
            items = self.stylist._stabilize_outfit(
                new_items=items,
                old_items=current_outfit_items,
                swap_requests=swap_requests_for_prompt,
            )
            items = self.stylist._dedupe_one_per_category(items)

        # 3) Enforce physics
        items = self.stylist._enforce_one_piece_physics(items)
        items = self.stylist._dedupe_one_per_category(items)

        # 4) Stabilize again (reassert locks after physics)
        if current_outfit_items:
            items = self.stylist._stabilize_outfit(
                new_items=items,
                old_items=current_outfit_items,
                swap_requests=swap_requests_for_prompt,
            )
            items = self.stylist._enforce_one_piece_physics(items)
            items = self.stylist._dedupe_one_per_category(items)

        # 5) Apply attribute corrections last (no structure changes)
        items = self.stylist._apply_attribute_corrections(items, attribute_corrections, allowed_swap_categories=swap_requests_for_prompt)

        option0.items = [item_cls(**it) for it in items]

        # Postprocess search queries once after final structure
        wear_category = self.user_profile.get("wear_preference", "Unisex")
        self.stylist._apply_gender_query_postprocess(outfit_obj, wear_category)
        return outfit_obj

    def _derive_tags_and_lessons(
        self,
        user_query: str,
        situational_signals: dict,
        critique_obj=None,
        final_obj=None,
    ) -> tuple[list[str], list[str]]:
        q = (user_query or "").lower()

        STOP = {
            "i","me","my","mine","we","our","you","your","yours",
            "a","an","the","and","or","but","so","to","for","of","in","on","at","with","without",
            "this","that","these","those","it","its","is","are","was","were","be","been","being",
            "want","need","like","love","hate","prefer","make","more","less","change","swap",
            "wear","wearing","use","using","today","tomorrow","yesterday","please","thanks",
            "not","no","dont","don't","cant","can't",
            "outfit","outfits","new","give",
        }

        bad_prefixes = ("give_", "make_", "want_", "need_")
        bad_exact = {"new_outfit", "outfit", "outfits", "give_new_outfit", "new"}

        def norm(s: str) -> str:
            s = (s or "").strip().lower()
            s = re.sub(r"[^a-z0-9\s_-]+", "", s)
            s = re.sub(r"\s+", "_", s).strip("_")
            return s

        def is_ruley(t: str) -> bool:
            return t.startswith(("avoid_", "must_", "no_", "should_", "never_", "always_"))

        def keep_tag(t: str) -> bool:
            if not t or len(t) < 3:
                return False
            if t in STOP or t in bad_exact:
                return False
            if t.startswith(bad_prefixes):
                return False
            if is_ruley(t):
                return False
            if len(t) > 24 or t.count("_") >= 4:
                return False
            return True

        def add_tag(tags: set[str], raw: str):
            t = norm(raw)
            if keep_tag(t):
                tags.add(t)

        def add_compound(tags: set[str], words: list[str]):
            w = []
            for x in words:
                nx = norm(x)
                if nx and nx not in STOP:
                    w.append(nx)
            if 2 <= len(w) <= 3:
                add_tag(tags, "_".join(w))

        tags = set()

        event = (situational_signals.get("event_type") or "").strip()
        add_tag(tags, event)

        aesthetic = (situational_signals.get("aesthetic") or "").strip()
        add_tag(tags, aesthetic)

        fb = situational_signals.get("feedback") or {}
        if hasattr(fb, "model_dump"):
            fb = fb.model_dump()

        for s in (fb.get("swap_out") or []):
            add_tag(tags, s)

        insp = (situational_signals.get("external_inspiration") or {})
        add_tag(tags, insp.get("name", ""))

        vibe = (insp.get("vibe") or "").strip()
        if vibe and len(vibe.split()) <= 3:
            add_tag(tags, vibe)

        prefs = (self.user_profile.get("preferences") or {})
        for icon in (prefs.get("style_icons") or [])[:2]:
            add_tag(tags, icon)
        for brand in (prefs.get("favorite_brands") or [])[:3]:
            add_tag(tags, brand)

        color = (self.user_profile.get("color_season") or self.user_profile.get("personal_color") or "").strip()
        body = (self.user_profile.get("body_style_essence") or "").strip()
        if color:
            add_tag(tags, color.replace(" ", "_"))
        if body:
            add_tag(tags, body.replace(" ", "_"))

        tokens = [t for t in re.split(r"[\s/,.!?:;()]+", q) if t]
        tokens = [re.sub(r"[^a-z0-9_-]+", "", t) for t in tokens]
        tokens = [t for t in tokens if t and t not in STOP and len(t) >= 3]

        for m in re.findall(r'"([^"]+)"', user_query or ""):
            add_tag(tags, m)

        added_ngrams = 0
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                phrase = tokens[i : i + n]
                if any(x in STOP for x in phrase):
                    continue
                before = len(tags)
                add_compound(tags, phrase)
                if len(tags) > before:
                    added_ngrams += 1
                if added_ngrams >= 8:
                    break
            if added_ngrams >= 8:
                break

        freq = Counter(tokens)
        for tok, _ in freq.most_common(5):
            add_tag(tags, tok)

        try:
            if final_obj is not None and hasattr(final_obj, "outfit_options") and final_obj.outfit_options:
                items = final_obj.outfit_options[0].items
                for it in items:
                    add_tag(tags, getattr(it, "category", ""))

                for it in items[:2]:
                    add_tag(tags, getattr(it, "item_name", ""))
        except Exception:
            pass

        lessons = []
        try:
            if critique_obj and getattr(critique_obj, "main_issue", None):
                lessons.append(critique_obj.main_issue.strip())
            if critique_obj and getattr(critique_obj, "plan", None) and critique_obj.plan.actions:
                for a in critique_obj.plan.actions[:2]:
                    lessons.append(f"{a.target_category}: {a.instruction}".strip())
        except Exception:
            pass

        def dedupe_preserve(xs):
            out = []
            for x in xs:
                x = (x or "").strip()
                if x and x not in out:
                    out.append(x)
            return out

        tags_list = sorted(tags)[:20]
        lessons_list = dedupe_preserve(lessons)[:8]

        print(f"🏷️ Derived tags: {tags_list[:10]}")
        return tags_list, lessons_list

    def _select_retrieval_tags(self, tags: list[str], k: int = 2) -> list[str]:
        if not tags:
            return []

        scored = []
        for t in tags:
            score = 0
            parts = t.split("_")

            if len(parts) >= 4:
                score -= 4
            if 2 <= len(parts) <= 3:
                score += 4
            if 8 <= len(t) <= 20:
                score += 2
            elif len(t) > 24:
                score -= 2

            if t in {
                "clean_chic", "quiet_luxury", "romantic", "neutral", "edgy",
                "cool_summer", "summer_cool", "warm_spring",
                "straight", "curvy", "petite", "general"
            }:
                score -= 5

            if "_" not in t and len(t) < 8:
                score -= 1

            scored.append((score, t))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [t for score, t in scored if score > 0][:k]

        print(f"🔎 Retrieval tags: {selected}")
        return selected

    def _qa_physics(self, recommendation_obj):
        rec = self._dump(recommendation_obj) or {}
        items = (rec.get("outfit_options") or [{}])[0].get("items") or []

        cats = {canon_category((it.get("category") or "").strip()) for it in items}

        # ban OnePiece + (Top or Bottom)
        if "OnePiece" in cats and ("Top" in cats or "Bottom" in cats):
            raise ValueError("Physics fail: OnePiece cannot coexist with Top/Bottom.")
        
    def _log_trend_context(self, signals: dict):
        tc = signals.get("trend_context") or {}
        if not tc:
            print("📈 Trend context: (none)")
            return
        cards = tc.get("selected_trends") or []
        print(f"📈 Trend context: cards={len(cards)} tags={tc.get('retrieval_tags')}")
        for c in cards[:3]:
            print(f"   - {c.get('trend_name')} | borrow={c.get('what_to_borrow')} | avoid={c.get('avoid')}")

    # ====================================================
    # 🛠️ UTILITIES & SNAPSHOTS
    # ====================================================
    def _infer_season(self) -> str:
        location_text = self.user_profile.get("location_city", "") or ""

        month = datetime.now().month
        hemisphere = self._infer_hemisphere(location_text)

        north = {
            12: "Winter", 1: "Winter", 2: "Winter",
            3: "Spring", 4: "Spring", 5: "Spring",
            6: "Summer", 7: "Summer", 8: "Summer",
            9: "Fall", 10: "Fall", 11: "Fall",
        }
        south = {
            12: "Summer", 1: "Summer", 2: "Summer",
            3: "Fall", 4: "Fall", 5: "Fall",
            6: "Winter", 7: "Winter", 8: "Winter",
            9: "Spring", 10: "Spring", 11: "Spring",
        }

        return (south if hemisphere == "south" else north).get(month, "General")

    def _infer_hemisphere(self, location_text: str) -> str:
        text = (location_text or "").lower()
        south_markers = (
            "australia", "new zealand", "sydney", "melbourne", "brisbane",
            "perth", "adelaide", "auckland", "wellington", "christchurch",
            "south africa", "cape town", "johannesburg", "durban",
            "argentina", "buenos aires", "chile", "santiago", "uruguay",
            "montevideo", "paraguay", "bolivia", "rio de janeiro", "sao paulo",
        )
        return "south" if any(marker in text for marker in south_markers) else "north"

    def _update_history(self, user_text, assistant_text):
        self.conversation_state["history"].append({"role": "user", "content": user_text})
        self.conversation_state["history"].append({"role": "assistant", "content": assistant_text})

    def _save_snapshot(self, filename="debug_session.json"):
        filepath = os.path.join(self.snapshot_dir, filename)
        data = {
            "timestamp": time.time(),
            "context": self.current_context,
            "conversation_state": self.conversation_state,
        }
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            print(f"📸 Snapshot saved to {filepath}")
        except Exception as e:
            print(f"⚠️ Snapshot failed: {e}")

    def _load_snapshot(self, filename="debug_session.json"):
        filepath = os.path.join(self.snapshot_dir, filename)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def _smart_update(self, current_data, new_data):
        for key, new_val in (new_data or {}).items():
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

    def _safe_merge(self, list_a, list_b):
        combined = (list_a or []) + (list_b or [])
        unique_items = []
        for item in combined:
            if item not in unique_items:
                unique_items.append(item)
        return unique_items
