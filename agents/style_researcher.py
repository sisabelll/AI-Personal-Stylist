import json
import os
from core.schemas import StyleResearchDoc
from services.search_tool import SearchTool
from services.client import OpenAIClient
from core.config import get_logger

logger = get_logger(__name__)

class StyleResearcherAgent:
    def __init__(self, client: OpenAIClient):
        self.search_tool = SearchTool()
        self.client = client
        self.kb_path = 'data/knowledge_base.json'
        
        # Ensure KB exists
        if not os.path.exists(self.kb_path):
            with open(self.kb_path, 'w') as f:
                json.dump({"entities": {}}, f)

    def _sanitize_entity(self, raw_input):
        """
        Uses LLM to clean typos and remove noise (e.g., 'theory brand' -> 'Theory').
        Returns the raw input if LLM fails.
        """
        # 1. Fail Fast: If input is empty or no LLM, just return it.
        if not raw_input or not self.client:
            return raw_input

        # 2. The Strict Prompt
        prompt = f"""
        TASK: Clean and standardize this fashion search term.
        INPUT: "{raw_input}"
        
        RULES:
        1. Correct spelling (e.g. "prda" -> "Prada").
        2. Remove generic words (e.g. "Theory brand" -> "Theory", "Zara style" -> "Zara").
        3. If it's a celebrity, return their full name (e.g. "zendaya" -> "Zendaya").
        4. OUTPUT ONLY THE CLEAN NAME. No punctuation, no "Here is the name".
        
        Clean Name:
        """

        try:
            # 3. Call the LLM
            response = self.client.call_api(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a precise data cleaning assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0 # Strict determinism
            )
            
            clean_name = response.strip()
            clean_name = clean_name.replace('"', '').replace("'", "").rstrip(".")
            return clean_name

        except Exception as e:
            logger.warning("Sanitation failed for '%s': %s", raw_input, e)
            # If AI fails, fall back to the raw input so the app doesn't crash
            return raw_input

    def get_profile(self, entity_name):
        # 1. Load Knowledge Base
        kb_data = self._load_kb()
        entities = kb_data.get('entities', {})
        
        # Fast Lookup (Raw Input)
        if entity_name.lower() in entities:
            logger.debug("KB hit (raw): '%s'", entity_name)
            return entities[entity_name.lower()]

        # 2. If missed, THEN Sanitize (e.g. "Theory brand" -> "Theory")
        clean_name = self._sanitize_entity(entity_name)

        # Avoid double-checking if sanitization didn't change anything
        if clean_name.lower() != entity_name.lower():
            logger.debug("Sanitized '%s' -> '%s'", entity_name, clean_name)
            # Smart Lookup (Clean Input)
            if clean_name.lower() in entities:
                logger.debug("KB hit (sanitized): '%s'", clean_name)
                return entities[clean_name.lower()]

        # 3. Research (True Miss)
        logger.debug("Researching: '%s'", clean_name)
        new_data = self._perform_research(clean_name)
        
        # 4. Save to KB
        if new_data:
            self._save_to_kb(clean_name, new_data)
            
        return new_data

    def _perform_research(self, entity_name):
        results = self.search_tool.search_web(f"{entity_name} fashion style key elements analysis 2025")
        if not results:
            logger.warning("No search results for '%s'", entity_name)
            return None
            
        context_text = "\n".join([r['content'] for r in results])
        
        # B. Analyze (The "Thinking" Step)
        prompt = f"""
        You are a Fashion Archivist. 
        Analyze the raw search text below about {entity_name}'s style.
        
        YOUR GOAL: 
        Extract a structured style profile.
        
        CRITICAL DISTINCTION:
        1. **Wardrobe Staples**: The "Uniform". Items worn repeatedly in daily life (e.g., simple denim, white tees).
        2. **Statement Pieces**: The "Highlights". Red carpet looks or unique items that define their specific flair.
        
        RAW SEARCH CONTEXT:
        {context_text[:5000]}
        """
        messages = [{"role": "system", "content": prompt}]
        result = self.client.call_api(
            model='gpt-4o-2024-08-06', 
            messages=messages, 
            temperature=0.5, # Mid-temp is good for summarization
            response_model=StyleResearchDoc
        )

        # C. Save
        result = result.model_dump(exclude_none=True)
        self._save_to_kb(entity_name, result)
        return result

    def _load_kb(self):
        with open(self.kb_path, 'r') as f:
            return json.load(f)

    def _save_to_kb(self, entity, data):
        kb = self._load_kb()
        kb['entities'][entity.lower()] = data
        with open(self.kb_path, 'w') as f:
            json.dump(kb, f, indent=2)

   