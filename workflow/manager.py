import json
import os
import time
from datetime import datetime
import traceback
from typing import Dict, Any

# --- AGENTS & CORE ---
from core.schemas import UserActionType, StyleInterpretation, OutfitCritique, EditPlan
from core.style_program_schemas import StyleProgram

from agents.interpreter import ContextInterpreter, StyleConstraintBuilder
from agents.stylist import StyleStylist
from agents.style_researcher import StyleResearcherAgent
from agents.refiner import RefinementAgent
from agents.style_program import StyleProgramBuilder
from agents.editor import OutfitCritic, OutfitSurgeon
from agents.qa import OutfitQA
from agents.editor import EditorAgent

# --- SERVICES ---
from services.catalog import CatalogClient

class ConversationManager:
    def __init__(self, client, user_profile, style_rules, storage=None, dev_mode=False):
        self.client = client
        self.user_profile = user_profile
        self.storage = storage
        self.dev_mode = dev_mode

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
        self.critic = OutfitCritic(client)
        self.surgeon = OutfitSurgeon(client)
        self.qa = OutfitQA()
        self.editor = EditorAgent(client)

        # 3. Initialize State
        self.current_context = {}  
        self.conversation_state = { 
            "current_recommendation": None,
            "refinement_signals": {}, 
            "anchored_items": [],
            "history": [],
            "revisions": []
        }
        
        # 4. Local Snapshot Config (Debugging only)
        self.snapshot_dir = os.path.join('.', 'snapshots')
        os.makedirs(self.snapshot_dir, exist_ok=True)

    # ====================================================
    # 🚀 SESSION ENTRY POINTS
    # ====================================================
    @property
    def current_outfit(self):
        """Helper to access the current recommendation safely."""
        return self.conversation_state.get('current_recommendation', {})
    
    def start_new_session(self, user_request_context, user_query, status_callback=None, use_cache=None):
        """Initializes a session by interpreting the raw request."""
        if use_cache is None:
            use_cache = self.dev_mode
        
        # 1. CACHE CHECK (Developer Mode)
        if use_cache:
            snapshot_data = self._load_snapshot("debug_session.json")
            if snapshot_data:
                self.current_context = snapshot_data.get("context", {})
                self.conversation_state = snapshot_data.get("conversation_state", {})
                if status_callback: status_callback("⚡ Loaded cached outfit from snapshot.")
                return self.conversation_state.get('current_recommendation')

        print(f"🚀 Starting new session: '{user_query}'")
        
        # 2. INTERPRET INPUT
        interpretation: StyleInterpretation = self.interpreter.interpret(user_request_context, user_query)
        new_signals = interpretation.model_dump(exclude_none=True) if hasattr(interpretation, "model_dump") else interpretation
        self.current_context = self._smart_update(self.current_context, new_signals)

        # 3. RESEARCHER (Check for External Inspiration)
        self._check_and_run_research(status_callback)

        # 4. RESET STATE FOR NEW LOOK
        self.conversation_state["current_recommendation"] = None
        self.conversation_state["refinement_signals"] = {}
        self.conversation_state["anchored_items"] = self.current_context.get('requested_items', [])
        self.conversation_state["revisions"] = []
        self.conversation_state["last_critique"] = None

        if status_callback: status_callback("🎨 Synthesizing outfit recommendation...")

        hard_constraints = self.current_context.get('hard_constraints', {})
        situational_signals = {
            "external_inspiration": self.current_context.get('external_style_inspiration', {}),
            # Try to find event in nested constraints, fallback to top level
            "event_type": hard_constraints.get('event_type') or self.current_context.get('event_type'),
            "weather": hard_constraints.get('weather'),
            "location": self.user_profile.get('location_city', 'NYC'),
            # Pass the strict aesthetic choice
            "aesthetic": self.current_context.get('aesthetic_bias', 'clean_chic') 
        }
        
        # 5. GENERATE OUTFIT
        final_obj, critique, draft_obj = self._generate_with_editor_pass(
            user_query=user_query,
            situational_signals=situational_signals,
            current_outfit_items=None,
            revise_threshold=8,
            store_threshold=9,
            version="editor_v1",
        )
        self.conversation_state["last_critique"] = critique.model_dump()
        recommendation = final_obj.model_dump()
        
        # 6. VISUAL SEARCH
        print("🛍️ Searching for products...")
        if recommendation.get('outfit_options'):
            items_to_search = recommendation['outfit_options'][0].get('items', [])
            self.catalog.search_products_parallel(items_to_search)

        # 7. SAVE STATE & RETURN
        self.conversation_state['current_recommendation'] = recommendation
        self.conversation_state['history'].append({
            "role": "assistant", 
            "content": recommendation.get('reasoning', "Here is your look.")
        })

        self._save_snapshot()
        return recommendation

    def refine_session(self, user_feedback_text):
        """Routes the user to either 'Action' (Generate) or 'Consultation' (Chat)."""

        print(f"🤔 Classifying intent: '{user_feedback_text}'")
        intent_action = self.interpreter.classify_intent(user_feedback_text)
        print(f"🚦 Route Detected: {intent_action}")

        # Update Context with new signals
        interpretation = self.interpreter.interpret(self.current_context, user_feedback_text)
        if hasattr(interpretation, "model_dump"):
            new_signals = interpretation.model_dump(exclude_none=True)
        else:
            new_signals = interpretation

        self.current_context = self._smart_update(self.current_context, new_signals)

        # Update Anchors if user specifically asked for items
        if 'requested_items' in self.current_context:
            self.conversation_state['anchored_items'] = self.current_context['requested_items']
               
        # --- ROUTE A: CONSULTATION ---
        if intent_action == UserActionType.ASK_QUESTION:
            current_outfit = self.conversation_state.get('current_recommendation', {})
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

        # --- ROUTE D: MODIFICATION (Standard) ---
        else:
            new_outfit = self._refine_look(user_feedback_text)
            self.conversation_state['current_recommendation'] = new_outfit
            return new_outfit

    # ====================================================
    # 🧠 CORE LOGIC
    # ====================================================
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
            user_query=user_query
        )
        signals = dict(situational_signals)

        print("\n🧵 ================= EDITOR PIPELINE =================")

        # 1) Draft
        draft_obj = self.stylist.recommend(
            constraints=self.user_profile,
            situational_signals=signals,
            user_query=user_query,
            current_outfit=current_outfit_items,
            style_program=style_program,
        )

        print("🟡 Draft generated")

        # 2) Critique (SAFE)
        critique = None
        try:
            critique = self.editor.critique(
                outfit=draft_obj,
                user_profile=self.user_profile,
                situational_signals=signals,
            )
        except Exception as e:
            print(f"⚠️ Editor critique failed: {e}")
            print(traceback.format_exc())
            
            # fallback critique: accept draft (so you don't block the user)
            critique = OutfitCritique(
                score=7,
                verdict="accept",
                summary="Editor unavailable; returning draft.",
                main_issue="Editor error",
                plan=EditPlan(hero="N/A", actions=[]),
            )

        # Now it's safe to print
        print("🧠 Editor critique")
        print(f"   Score: {critique.score}/10")
        print(f"   Verdict: {critique.verdict}")
        print(f"   Main issue: {critique.main_issue}")

        # 3) Optional revise
        final_obj = draft_obj
        if critique.verdict == "revise" and critique.score < revise_threshold and critique.plan.actions:
            print("🔁 Revision TRIGGERED")
            revised_signals = dict(signals)
            revised_signals["editor_plan"] = critique.plan.model_dump()

            final_obj = self.stylist.recommend(
                constraints=self.user_profile,
                situational_signals=revised_signals,
                user_query=user_query,
                current_outfit=current_outfit_items,
                style_program=style_program,
            )
            print("✅ Revision applied")
        else:
            print("⏭️ No revision needed")

        # 4) Log revisions (SAFE)
        def _safe_dump(x):
            return x.model_dump() if hasattr(x, "model_dump") else x

        self.conversation_state.setdefault("revisions", []).append({
            "input": user_query,
            "situational_signals": signals,
            "draft": _safe_dump(draft_obj),
            "critique": _safe_dump(critique),
            "final": _safe_dump(final_obj),
            "final_score": critique.score,
            "accepted": critique.score >= store_threshold,
            "version": version,
        })

        # 5) Store to Supabase (optional)
        accepted = critique.score >= store_threshold
        if self.storage and (store_all or accepted):
            try:
                self.storage.insert_styling_revision({
                    "user_id": str(self.user_profile.get("id")),
                    "user_query": user_query,
                    "situational_signals": signals,
                    "draft_outfit": _safe_dump(draft_obj),
                    "critique": _safe_dump(critique),
                    "final_outfit": _safe_dump(final_obj),
                    "final_score": critique.score,
                    "accepted": bool(accepted),
                    "version": version,
                })
                print("✅ Stored in Supabase")
            except Exception as e:
                print(f"⚠️ Supabase insert failed: {e}")

        print("🧵 =============== END EDITOR PIPELINE ===============\n")
        return final_obj, critique, draft_obj



    def _refine_look(self, user_text: str):
        """The 'Action' function for Route D."""
        print(f"🔄 Refining look based on: '{user_text}'")

        # 1. ANALYZE FEEDBACK
        current_data = self.conversation_state.get('current_recommendation', {})
        feedback_analysis = self.refiner_agent.analyze_feedback(
            current_outfit=current_data, 
            user_input=user_text
        )
        feedback = feedback_analysis.model_dump() if hasattr(feedback_analysis, "model_dump") else (feedback_analysis or {})

        # 2. PREPARE CONTEXT
        current_outfit_items = []
        hard_constraints = self.current_context.get('hard_constraints', {})

        if current_data and 'outfit_options' in current_data:
            current_outfit_items = current_data['outfit_options'][0].get('items', [])

        situational_signals = {
            "feedback": feedback,   
            "event_type": hard_constraints.get('event_type'),
            "external_inspiration": self.current_context.get('external_style_inspiration', {}),
            "items_to_remove": self.current_context.get('items_to_remove', []),
            "attribute_corrections": feedback_analysis.get("attribute_corrections", []),
            "edit_mode": True
        }

        # 3. CALL STYLIST (Edit Mode)
        final_obj, critique, draft_obj = self._generate_with_editor_pass(
            user_query=user_text,
            situational_signals=situational_signals,
            current_outfit_items=current_outfit_items,
            revise_threshold=8,
            store_threshold=9,
            version="editor_v1",
        )
        self.conversation_state["last_critique"] = critique.model_dump()
        new_recommendation = final_obj.model_dump()


        # 4. SEARCH
        if new_recommendation.get('outfit_options'):
            items = new_recommendation['outfit_options'][0].get('items', [])
            self.catalog.search_products_parallel(items)

        self._save_snapshot()
        return new_recommendation

    def _check_and_run_research(self, status_callback=None):
        """Checks if a Style Icon needs to be researched."""
        chat_refs = self.current_context.get('style_references', [])
        
        # Check User Profile (DB)
        profile_refs = []
        if 'preferences' in self.user_profile:
             profile_refs = self.user_profile['preferences'].get('style_icons', [])
        
        all_refs = self._safe_merge(chat_refs, profile_refs)
        
        if all_refs:
            icon_name = all_refs[0]
            current_data = self.current_context.get('external_style_inspiration', {})
            existing_name = current_data.get('name', '')
            
            if not current_data or (existing_name and existing_name.lower() != icon_name.lower()):
                if status_callback: status_callback(f"🕵️‍♀️ Researching style icon: **{icon_name}**...")
                researched_data = self.researcher.get_profile(icon_name)
                self.current_context['external_style_inspiration'] = researched_data

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

        editorial_nos = [
            "No generic mall-basic stacks (must have a point of view).",
            "No more than one hero element (silhouette OR texture OR accessory).",
            "Avoid random warm browns near the face if user is Cool/Summer unless justified.",
            "Avoid proportion-breaking hems (esp. with mid-calf boots).",
        ]

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

    def _infer_season(self) -> str:
        location_text = self.user_profile.get("location_city")

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
        text = location_text.lower()
        south_markers = (
            "australia", "new zealand", "sydney", "melbourne", "brisbane",
            "perth", "adelaide", "auckland", "wellington", "christchurch",
            "south africa", "cape town", "johannesburg", "durban",
            "argentina", "buenos aires", "chile", "santiago", "uruguay",
            "montevideo", "paraguay", "bolivia", "rio de janeiro", "sao paulo",
        )
        return "south" if any(marker in text for marker in south_markers) else "north"

    # ====================================================
    # 🛠️ UTILITIES & SNAPSHOTS
    # ====================================================

    def _update_history(self, user_text, assistant_text):
        self.conversation_state['history'].append({"role": "user", "content": user_text})
        self.conversation_state['history'].append({"role": "assistant", "content": assistant_text})

    def _save_snapshot(self, filename="debug_session.json"):
        """Saves current state locally for debugging."""
        filepath = os.path.join(self.snapshot_dir, filename)
        data = {
            "timestamp": time.time(),
            "context": self.current_context,
            "conversation_state": self.conversation_state
        }
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"📸 Snapshot saved to {filepath}")
        except Exception as e:
            print(f"⚠️ Snapshot failed: {e}")

    def _load_snapshot(self, filename="debug_session.json"):
        """Loads local state."""
        filepath = os.path.join(self.snapshot_dir, filename)
        if not os.path.exists(filepath): return None
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def _smart_update(self, current_data, new_data):
        """Recursively merges dictionaries."""
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
    
    def _safe_merge(self, list_a, list_b):
        """Deduplicates lists."""
        combined = list_a + list_b
        unique_items = []
        for item in combined:
            if item not in unique_items:
                unique_items.append(item)
        return unique_items