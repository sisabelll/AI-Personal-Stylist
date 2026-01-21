import json
import os
import time
from typing import Dict, Any

# --- AGENTS & CORE ---
from agents.interpreter import ContextInterpreter, StyleConstraintBuilder
from core.schemas import UserActionType, StyleInterpretation
from agents.stylist import StyleStylist
from agents.style_researcher import StyleResearcherAgent
from agents.refiner import RefinementAgent

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
    
    def start_new_session(self, user_request_context, user_query, status_callback=None, use_cache=False):
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
        recommendation = self.stylist.recommend(
            constraints=self.user_profile, 
            situational_signals=situational_signals,
            user_query=user_query,
            current_outfit=None 
        )

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
            "items_to_remove": self.current_context.get('items_to_remove', [])
        }

        # 3. CALL STYLIST (Edit Mode)
        new_recommendation = self.stylist.recommend(
            constraints=self.user_profile,       
            situational_signals=situational_signals,
            user_query=user_text,
            current_outfit=current_outfit_items
        )

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