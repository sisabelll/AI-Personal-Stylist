import json
from typing import Dict, List, Union

from core.client import OpenAIClient
from core.schemas import StyleInterpretation, UserIntent

class StyleConstraintBuilder:
    def __init__(self, user_profile: Union[Dict, List[Dict]], style_rules: dict):
        if isinstance(user_profile, list):
            self.user_profile = user_profile[0] if user_profile else {}
        else:
            self.user_profile = user_profile or {}
        self.style_rules = style_rules or {}

    def build(self) -> dict:
        constraints = {}
        personal_color = self.user_profile.get('personal_color')
        body_type = self.user_profile.get('body_style_essence')
        aesthetic = self.user_profile.get('style_persona')
        wear_pref = self.user_profile.get('wear_preference', 'Unisex')
        constraints['wear_category'] = wear_pref
        
        if personal_color:
            constraints['color_guidelines'] = self.style_rules.get('personal_color_theory', {}).get(personal_color, {})
        if body_type:
            constraints['body_guidelines'] = self.style_rules.get('body_style_essence_theory', {}).get(body_type, {})
        if aesthetic:
            constraints['aesthetic_guidelines'] = self.style_rules.get('aesthetic_style_summary', {}).get(aesthetic, {})

        return constraints


class ContextInterpreter:
    def __init__(self, client: OpenAIClient, request_schema: dict):
        self.client = client
        self.schema = request_schema or {}
        self._cache = {}

    def interpret(self, request_context_input: dict, user_query: str) -> dict:
        cache_key_data = {
            "context": request_context_input,
            "query": user_query
        }
        key = json.dumps(cache_key_data, sort_keys=True)
        
        if key in self._cache:
            print('Using cached interpreter result.')
            return self._cache[key]
        
        system_prompt = """
        You are a Context Interpreter. Extract style signals from the USER QUERY.
        
        # INPUT DATA:
        1. REQUEST CONTEXT: Background info, previous items, and inspiration.
        2. USER QUERY: The active command from the user.

        # CRITICAL RULE ON 'REQUESTED ITEMS':
        - Your job is to list items the user explicitly DEMANDS to wear in the current query.
        - 🚫 DO NOT assume items from 'REQUEST CONTEXT' are requested unless the user references them.
        
        # EXAMPLES:
        
        Case 1: Implicit Interest (Background)
        Context: "Inspiration contains Silver Earrings."
        User Query: "Make me an outfit."
        Output: "requested_items": []  <-- CORRECT. User didn't ask for them.
        
        Case 2: Explicit Request
        User Query: "I want to wear those silver earrings."
        Output: "requested_items": ["silver earrings"] <-- CORRECT. User asked.
        
        Case 3: Reference Resolution
        Context: "Last outfit had a Tweed Dress."
        User Query: "Actually, let's go with that dress."
        Output: "requested_items": ["Tweed Dress"] <-- CORRECT. Resolved 'that dress'.
        """

        user_prompt = (
            f"CONTEXT: {request_context_input}\n"
            f"QUERY: {user_query}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        result = self.client.call_api(model='gpt-4o-mini', messages=messages, temperature=0.1, response_model=StyleInterpretation)        
        self._cache[key] = result
        return result

    def classify_intent(self, user_text: str) -> str:
        
        system_prompt = """
        You are a Semantic Intent Classifier.
        
        YOUR JOB:
        Analyze the user's input grammar to determine the immediate next step.
        
        THE RULES:
        1. 'ask_question': 
           - Input starts with a Verb/Auxiliary (Is, Does, Do, Would, Should, Could, Why).
           - Input ends with a question mark.
           - User is seeking an OPINION, JUDGMENT, or FACT.
           - Example: "Is tweed too much?", "Would boots look good?", "Why this color?"
           
        2. 'modify_outfit':
           - Input is an Imperative (Change, Swap, Add, Remove).
           - Input is a Conditional Proposal (What if we..., How about...).
           - Input is a Negative Statement (I don't like x, It's too heavy).
           
        3. 'finalize_outfit': 
           - User accepts the current state (Perfect, Great, Thanks).

        TRICKY EXAMPLES (Study These):
        - User: "Is tweed too much?" 
          Reasoning: Starts with 'Is'. Asks for judgment. 
          Action: ask_question
          
        - User: "Tweed is too much." 
          Reasoning: Statement of fact/preference. Implies change needed.
          Action: modify_outfit
          
        - User: "What if I wear boots?" 
          Reasoning: 'What if' proposes a new state. 
          Action: modify_outfit
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ]
        
        result = self.client.call_api(
            model='gpt-4o-mini',
            messages=messages,
            temperature=0.0, # Zero temp is crucial for strict logic
            response_model=UserIntent
        )
        
        print(f"🧠 Intent Reasoning for {result['action']}: {result['reasoning']}") # Debug print to see it thinking!
        return result['action']