import json
from services.storage import DataLoader
from agents.interpreter import ContextInterpreter, StyleConstraintBuilder
from core.schemas import UserActionType
from agents.stylist import StyleStylist
from agents.style_researcher import StyleResearcherAgent
from agents.refiner import RefinementAgent
from services.catalog import CatalogClient

class ConversationManager:
    def __init__(self, client, user_profile, style_rules, request_context_schema):
        self.client = client
        self.user_profile = user_profile
        self.data_loader = DataLoader()

        # 1. Initialize Static Rules (The "Librarian")
        builder = StyleConstraintBuilder(user_profile, style_rules)
        self.static_constraints = builder.build()
        
        # 2. Initialize Helpers
        self.interpreter = ContextInterpreter(client, request_context_schema)
        self.stylist = StyleStylist(client)
        self.researcher = StyleResearcherAgent(client)
        self.refiner_agent = RefinementAgent(client)
        self.catalog = CatalogClient()

        # 3. Initialize Mutable State
        self.current_context = {}  # "Brunch, casual"
        self.conversation_state = { # Tracks history & refinement
            "current_recommendation": None,
            "refinement_signals": {}, 
            "anchored_items": [],
            "history": []
        }

    def start_new_session(self, user_request_context, user_query, status_callback=None, use_cache=False):
        """Initializes a session by interpreting the raw request (e.g., 'Brunch')."""
        
        # 1. DEVELOPER CACHE CHECK
        if use_cache:
            snapshot_data = self.data_loader.load_snapshot("debug_session.json")
            if snapshot_data:
                self.current_context = snapshot_data.get("context", {})
                self.conversation_state = snapshot_data.get("conversation_state", {})
                if status_callback: status_callback("⚡ Loaded cached outfit.")
                return self.conversation_state.get('current_recommendation')

        print(f"🚀 Starting new session with request: '{user_query}'")
        
        # 2. INTERPRET INPUT
        new_signals = self.interpreter.interpret(user_request_context, user_query)
        self.current_context = self._smart_update(self.current_context, new_signals)

        # 3. RESEARCHER (Style Icons)
        profile_refs = self.user_profile.get('style_references', [])
        chat_refs = self.current_context.get('style_references', [])
        all_style_refs = self._safe_merge(profile_refs, chat_refs)
        
        if all_style_refs:
            icon_name = all_style_refs[0]
            current_data = self.current_context.get('external_style_inspiration', {})
            existing_name = current_data.get('name', '')
            
            if not current_data or (existing_name and existing_name.lower() != icon_name.lower()):
                if status_callback: status_callback(f"🕵️‍♀️ Researching style icon: **{icon_name}**...")
                researched_data = self.researcher.get_profile(icon_name)
                self.current_context['external_style_inspiration'] = researched_data

        # 4. RESET STATE
        self.conversation_state = {
            "current_recommendation": None,
            "refinement_signals": {}, 
            "history": [],
            "anchored_items": self.current_context.get('requested_items', [])
        }
        
        if status_callback: status_callback("🎨 Synthesizing outfit recommendation...")

        # Note: We pass 'current_outfit=None' to force a fresh start.
        recommendation = self.stylist.recommend(
            constraints=self.user_profile,
            situational_signals={
                "external_inspiration": self.current_context.get('external_style_inspiration', {}),
                "event_type": self.current_context.get('event_type', ''),
                "season": self.current_context.get('season', 'General')
            },
            user_query=user_query,
            current_outfit=None 
        )

        # We dig into the list to find specific items, effectively ignoring the "Reasoning" text.
        print("🛍️ searching for initial products...")
        if recommendation.get('outfit_options'):
            items_to_search = recommendation['outfit_options'][0].get('items', [])
            self.catalog.search_products_parallel(items_to_search)

        # 7. SAVE & RETURN
        self.conversation_state['current_recommendation'] = recommendation
        
        # Add initial message to history
        self.conversation_state['history'].append({
            "role": "assistant", 
            "content": recommendation.get('reasoning', "Here is your look.")
        })

        # Auto-save Snapshot
        self.data_loader.save_snapshot(
            context=self.current_context,
            state=self.conversation_state,
            filename="debug_session.json"
        )
        
        return recommendation

    def refine_session(self, user_feedback_text):
        """
        Smartly routes the user to either 'Action' (Generate) or 'Consultation' (Chat).     
        """

        print(f"🤔 Classifying intent for: '{user_feedback_text}'...")
        intent_action = self.interpreter.classify_intent(user_feedback_text)
        print(f"🚦 Route Detected: {intent_action}")

        new_signals = self.interpreter.interpret(self.current_context, user_feedback_text)
        self.current_context = self._smart_update(self.current_context, new_signals)

        if 'requested_items' in self.current_context:
            self.conversation_state['anchored_items'] = self.current_context['requested_items']
               
        # ====================================================
        # ROUTE A: CONSULTATION (Chat / Advice)
        # ====================================================
        if intent_action == UserActionType.ASK_QUESTION:
            print("💬 User is asking a question. Switching to Consult mode.")
            current_outfit = self.conversation_state.get('current_recommendation', {})
            
            # Ask the Stylist for advice
            advice_text = self.stylist.consult(current_outfit, user_feedback_text)
            
            # Save this Q&A to the chat history so it appears in the UI
            self.conversation_state['history'].append({
                "role": "user", 
                "content": user_feedback_text
            })
            self.conversation_state['history'].append({
                "role": "assistant", 
                "content": advice_text
            })
            return advice_text

        # ====================================================
        # ROUTE B: FINALIZATION (Save & Celebrate)
        # ====================================================
        elif intent_action == UserActionType.FINALIZE_OUTFIT:
            # User loves it. Save the current state.
            # (Future: You can save this to a database here)
            success_msg = "🎉 I'm so glad you love it! I've saved this look to your history. Have an amazing time!"
            
            self.conversation_state['history'].append({
                "role": "assistant", 
                "content": success_msg
            })
            return success_msg

        # ====================================================
        # ROUTE C: RESET (Start Over)
        # ====================================================
        elif intent_action == UserActionType.RESET_SESSION:
            return self.start_new_session(user_request_context={}, user_query="Let's start fresh.")

        # ====================================================
        # ROUTE D: MODIFICATION (The "Standard" Path)
        # ====================================================
        else:
            self.conversation_state['history'].append({"role": "user", "content": user_feedback_text})
            new_outfit = self.refine_look(user_feedback_text)

            self.conversation_state['current_recommendation'] = new_outfit
            self.conversation_state['history'].append({
                "role": "assistant", 
                "content": new_outfit.get('reasoning', "Here is your updated look.")
            })
            return new_outfit

    def _generate_recommendation(self, user_query):
        """
        Internal helper to call the Stylist Engine with current state.
        Dynamically merges ALL refinement signals into the active context
        WITHOUT corrupting the permanent context.
        """
        
        # 1. Start with a shallow copy (Safe ONLY if we don't mutate lists in-place)
        active_signals = self.current_context.copy()

        # 2. Get the latest refinement state
        refinements = self.conversation_state.get('refinement_signals', {})
        
        # 3. Dynamic Injection: Safe Merging
        
        # A. Handle "Make More" (Add to Vibe/Direction)
        if refinements.get('make_more'):
            current_vibes = active_signals.get('vibe_modifiers', [])
            active_signals['vibe_modifiers'] = self._safe_merge(current_vibes, refinements['make_more'])

        # B. Handle "Make Less" (Add to Negative Constraints)
        if refinements.get('make_less'):
            current_avoids = active_signals.get('avoid_vibes', [])
            active_signals['avoid_vibes'] = self._safe_merge(current_avoids, refinements['make_less'])

        # C. Handle "Swap Out" & "Dislikes" (Critical: These become HARD AVOIDS)
        items_to_block = refinements.get('swap_out', []) + refinements.get('expressed_dislikes', [])
        if items_to_block:
            current_session_avoids = active_signals.get('session_avoids', [])
            active_signals['session_avoids'] = self._safe_merge(current_session_avoids, items_to_block)

        # D. Handle "Emotional Goal" (High priority override)
        if refinements.get('emotional_goal'):
            active_signals['emotional_target'] = refinements['emotional_goal']

        # E. Handle "Expressed Likes" (Add to Preferences)
        if refinements.get('expressed_likes'):
            current_prefs = active_signals.get('temporary_preferences', [])
            active_signals['temporary_preferences'] = self._safe_merge(current_prefs, refinements['expressed_likes'])

        # F. Inject Anchored Items (The "Lock")
        anchored_items = self.conversation_state.get('anchored_items', [])
        if anchored_items:
            # Force overwrite to ensure the lock is respected
            active_signals['requested_items'] = anchored_items

        # 4. Construct the Prompt (Your logic here is excellent)
        final_query_text = user_query
        
        if anchored_items:
            items_str = ", ".join(anchored_items)
            final_query_text = (
                f"Constraint: I am definitely wearing my {items_str}. "
                f"With that locked in, please address this feedback: {user_query}"
            )

        print(f"🎨 Generating with Active Signals: {json.dumps(active_signals, indent=2)}")

        # 5. Call the Stylist
        recommendation = self.stylist.recommend(
            constraints=self.static_constraints, 
            situational_signals=active_signals, 
            user_query=final_query_text
        )
        
        # 6. Update History
        self.conversation_state['current_recommendation'] = recommendation
        self.conversation_state['history'].append({
            "query": user_query,
            "response": recommendation,
            "active_signals_snapshot": active_signals 
        })
        
        return recommendation
    
    def update_profile_and_research(self, new_profile_data, status_callback=None):
        """
        Updates the profile, runs research if needed, and returns a SUMMARY (not an outfit).
        """
        # 1. Update the Internal Profile
        self.user_profile = new_profile_data
        
        # 2. Check for Style Icons
        style_refs = self.user_profile.get('style_references', [])
        
        summary_msg = f"✅ Profile updated for **{self.user_profile.get('name')}**."
        
        if style_refs:
            raw_input = style_refs[0] # TODO: Support multiple later
            
            # 🟢 Trigger Callback: "Starting Research..."
            if status_callback:
                status_callback(f"🕵️‍♀️ New Style Icon detected: **{raw_input}**. Starting research...")
            
            # 3. Perform Research (The researcher cleans the name internally)
            researched_profile = self.researcher.get_profile(raw_input)
            
            # 4. Extract the CLEAN Name
            clean_name = researched_profile.get('name', raw_input)
            
            # 🟢 Trigger Callback: "Research Complete" (Use clean name here too!)
            if status_callback:
                status_callback(f"✅ Knowledge Base updated with **{clean_name}** style rules.")
            
            # 5. Update Context (Memory)
            self.current_context['external_style_inspiration'] = researched_profile
            
            # 6. Create a Summary
            vibe = researched_profile.get('vibe', 'Distinctive')
            staples = ", ".join(researched_profile.get('wardrobe_staples', [])[:3])
            
            # 🟢 FIX: Use clean_name in the final message
            summary_msg += f"\n\nI've analyzed **{clean_name}** ({vibe}). \nI'll keep their staples ({staples}...) in mind."

        summary_msg += "\n\n**How can I help you dress today?** (e.g., 'I have a dinner date', 'Job interview')"
        
        return summary_msg
    
    def _consolidate_items(self, items_list):
        """
        Removes redundant items where one is a substring of another.
        Optimized by sorting: Longest items act as the "parents".
        """
        if not items_list: return []
        
        # 1. Deduplicate exact matches & Sort by length (Longest first)
        # Sorting ensures we see "Navy Mid-Calf Rainboots" before "Rainboots"
        sorted_items = sorted(list(set(items_list)), key=len, reverse=True)
        
        kept_items = []
        
        for candidate in sorted_items:
            # Check if 'candidate' is part of any item we've already kept
            # Since we go Longest -> Shortest, we only need to look at what we've kept so far.
            is_redundant = any(candidate.lower() in kept.lower() for kept in kept_items)
            
            if not is_redundant:
                kept_items.append(candidate)
                
        return kept_items
    
    # This helps with scalability when new attributes get added to context
    def _smart_update(self, current_data, new_data):
        """
        Recursively merges new_data into current_data.
        - Lists: Append + Deduplicate (using _safe_merge)
        - Dicts: Recursive merge
        - Others: Overwrite
        """
        for key, new_val in new_data.items():
            # If key doesn't exist, just add it
            if key not in current_data:
                current_data[key] = new_val
                continue
            
            old_val = current_data[key]
            
            # CASE 1: Both are Lists -> Safe Merge
            if isinstance(old_val, list) and isinstance(new_val, list):
                current_data[key] = self._safe_merge(old_val, new_val)
                
            # CASE 2: Both are Dicts -> Recursive Update (Dive Deeper)
            elif isinstance(old_val, dict) and isinstance(new_val, dict):
                self._smart_update(old_val, new_val)
                
            # CASE 3: Conflict or Scalar (String/Int) -> Overwrite
            else:
                current_data[key] = new_val
                
        return current_data
    
    def _safe_merge(self, list_a, list_b):
        """
        Merges two lists and removes duplicates without crashing on Dictionaries.
        """
        # Combine everything
        combined = list_a + list_b
        
        # Deduplicate using a loop (Safe for dicts)
        unique_items = []
        for item in combined:
            if item not in unique_items:
                unique_items.append(item)
                
        return unique_items
    
    def refine_look(self, user_text: str):
        """
        The 'Action' function. 
        """
        print(f"🔄 Refine Look triggered with: '{user_text}'")

        # 1. ANALYZE FEEDBACK
        current_data = self.conversation_state.get('current_recommendation', {})
        
        feedback_analysis = self.refiner_agent.analyze_feedback(
            current_outfit=current_data, 
            user_input=user_text
        )
        print(f"📊 Feedback Analysis: {feedback_analysis}")

        # 2. PREPARE CONTEXT (Items + Vibe)
        current_outfit_items = []
        if current_data and 'outfit_options' in current_data:
            current_outfit_items = current_data['outfit_options'][0].get('items', [])

        # (Assuming you stored it in self.current_context during start_new_session)
        active_inspo = self.current_context.get('inspiration_data', {})

        # 3. CALL THE STYLIST (EDIT MODE)
        new_recommendation = self.stylist.recommend(
            constraints=self.user_profile,       
            situational_signals={
                "feedback": feedback_analysis,   
                "event_type": current_data.get('occasion', ''),
                "external_inspiration": active_inspo 
            },
            user_query=user_text,
            current_outfit=current_outfit_items
        )

        # 4. SEARCH FOR NEW PRODUCTS
        print("🛍️ Searching for new visuals...")
        if new_recommendation.get('outfit_options'):
            items = new_recommendation['outfit_options'][0].get('items', [])
            self.catalog.search_products_parallel(items)

        # 5. RETURN RESULTS
        return new_recommendation