import json
import os
import time
from datetime import datetime
from typing import Dict, Any

# --- AGENTS & CORE ---
from core.schemas import UserActionType, StyleInterpretation

from agents.interpreter import ContextInterpreter, StyleConstraintBuilder
from agents.stylist import StyleStylist
from agents.style_researcher import StyleResearcherAgent
from agents.refiner import RefinementAgent
from agents.style_program import StyleProgramBuilder
from agents.editor import OutfitCritic, OutfitSurgeon
from agents.qa import OutfitQA

# --- SERVICES ---
from services.catalog import CatalogClient

class ConversationManager:
    def __init__(self, client, user_profile, style_rules):
        self.client = client
        self.user_profile = user_profile
        
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

        # 3. Initialize State
        self.current_context = {}  
        self.conversation_state = { 
            "current_recommendation": None,
            "refinement_signals": {}, 
            "anchored_items": [],
            "history": []
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
    
    def start_new_session(self, user_request_context, user_query, status_callback=None, use_cache=True):
        """Initializes a session by interpreting the raw request."""
        
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
        if hasattr(interpretation, "model_dump"):
            new_signals = interpretation.model_dump(exclude_none=True)
        else:
            new_signals = interpretation

        self.current_context = self._smart_update(self.current_context, new_signals)

        # 3. RESEARCHER (Check for External Inspiration)
        self._check_and_run_research(status_callback)

        # 4. RESET STATE FOR NEW LOOK
        self.conversation_state["current_recommendation"] = None
        self.conversation_state["refinement_signals"] = {}
        self.conversation_state["anchored_items"] = self.current_context.get('requested_items', [])
        
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
        style_program = self._build_style_program(situational_signals)

        recommendation_obj = self.stylist.recommend(
            constraints=self.user_profile,
            situational_signals=situational_signals,
            user_query=user_query,
            current_outfit=None,
            style_program=style_program
        )

        recommendation = recommendation_obj.model_dump()

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

        self._save_snapshot() # Auto-save for debugging
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
    def _generate_with_editor_loop(self, user_query: str, situational_signals: dict, current_outfit_items: list = None):
        """
        Centralized pipeline:
        StyleProgram -> Stylist -> Critic -> (optional) Surgeon -> QA
        Keeps loop logic out of start_new_session/_refine_look.
        """

        program = self.style_program_builder.build(
            constraints=self.user_profile,
            situational_signals=situational_signals,
            user_query=user_query,
            current_outfit=current_outfit_items
        )

        # inject brief (tiny, avoids stylist prompt bloat)
        situational_signals = dict(situational_signals)
        situational_signals["style_brief"] = program.style_brief
        situational_signals["hard_constraints_summary"] = program.hard_constraints_summary

        # 1) draft
        draft = self.stylist.recommend(
            constraints=self.user_profile,
            situational_signals=situational_signals,
            user_query=user_query,
            current_outfit=current_outfit_items
        )

        # Stabilize immediately in edit mode (enforces locks even if LLM misbehaves)
        if current_outfit_items and draft.get("outfit_options"):
            swap_requests = (situational_signals.get("feedback") or {}).get("swap_out", [])
            items = draft["outfit_options"][0].get("items", [])
            draft["outfit_options"][0]["items"] = self.stylist._stabilize_outfit(
                new_items=items, old_items=current_outfit_items, swap_requests=swap_requests
            )

        critique = self.critic.evaluate(program=program, recommendation=draft, current_outfit=current_outfit_items)

        if critique.get("verdict") == "pass":
            return draft

        # 2) one surgical revision
        revised = self.surgeon.revise(program=program, recommendation=draft, critique=critique, current_outfit=current_outfit_items)

        # Stabilize again in edit mode
        if current_outfit_items and revised.get("outfit_options"):
            swap_requests = (situational_signals.get("feedback") or {}).get("swap_out", [])
            items = revised["outfit_options"][0].get("items", [])
            revised["outfit_options"][0]["items"] = self.stylist._stabilize_outfit(
                new_items=items, old_items=current_outfit_items, swap_requests=swap_requests
            )

        qa = self.qa.check(revised)
        if qa.get("passed"):
            return revised

        # fail-safe: return best attempt rather than looping forever
        return revised or draft

    def _refine_look(self, user_text: str):
        """The 'Action' function for Route D."""
        print(f"🔄 Refining look based on: '{user_text}'")

        # 1. ANALYZE FEEDBACK
        current_data = self.conversation_state.get('current_recommendation', {})
        feedback_analysis = self.refiner_agent.analyze_feedback(
            current_outfit=current_data, 
            user_input=user_text
        )

        # 2. PREPARE CONTEXT
        current_outfit_items = []
        hard_constraints = self.current_context.get('hard_constraints', {})

        if current_data and 'outfit_options' in current_data:
            current_outfit_items = current_data['outfit_options'][0].get('items', [])

        situational_signals = {
            "feedback": feedback_analysis,   
            "event_type": hard_constraints.get('event_type'),
            "external_inspiration": self.current_context.get('external_style_inspiration', {}),
            "items_to_remove": self.current_context.get('items_to_remove', []),
            "attribute_corrections": feedback_analysis.get("attribute_corrections", [])
        }

        # 3. CALL STYLIST (Edit Mode)
        style_program = self._build_style_program(situational_signals)

        new_obj = self.stylist.recommend(
            constraints=self.user_profile,
            situational_signals=situational_signals,
            user_query=user_text,
            current_outfit=current_outfit_items,
            style_program=style_program
        )

        new_recommendation = new_obj.model_dump()

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

    def _build_style_program(self, situational_signals: dict) -> dict:
        color = self.user_profile.get("personal_color", "General")
        body = self.user_profile.get("body_style_essence", "General")
        season = self._infer_season()

        style_brief = "\n".join([
            f"Vibe: {self.current_context.get('aesthetic_bias','clean_chic')} + {self.current_context.get('social_tone','polished')}",
            f"Silhouette: honor {body}; clean proportion; leg-lengthening.",
            f"Palette: prioritize {color}; keep contrast controlled.",
            "Editorial: exactly ONE hero element (silhouette OR texture OR accessory).",
            "NOs: avoid cheap-shine fabrics, overly busy prints, and mismatched formality footwear.",
        ])

        constraints_summary = "\n".join([
            f"Season: {season}",
            "Respect explicit requested items and swap/remove instructions.",
            "If editing: do not change locked categories; copy unchanged item_name/search_query verbatim.",
        ])

        # also expose the interpreter “knobs” to stylist so it stops guessing
        situational_signals["style_interpretation"] = {
            "formality_level": self.current_context.get("formality_level"),
            "social_tone": self.current_context.get("social_tone"),
            "aesthetic_bias": self.current_context.get("aesthetic_bias"),
            "vibe_modifiers": self.current_context.get("vibe_modifiers", []),
        }

        return {"style_brief": style_brief, "constraints_summary": constraints_summary}

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