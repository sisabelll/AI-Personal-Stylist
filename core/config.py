import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the root directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    """Central configuration for the AI Stylist App."""
    
    # --- OpenAI (The Brain) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL_SMART = "gpt-4o-2024-08-06" # For Stylist & Complex Logic
    OPENAI_MODEL_FAST = "gpt-4o-mini"        # For Classifier & Interpreter
    
    # --- Tavily (The Researcher) ---
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    
    # --- SerpApi (The Visualizer - Google Shopping) ---
    SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
    
    # --- Replicate (The Avatar Generator) ---
    REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
    
    # --- Google Search APIs ---
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
    
    # --- App Settings ---
    DEBUG_MODE = os.getenv("DEBUG_MODE", "True").lower() == "true"
    
    @classmethod
    def validate(cls):
        """Checks if critical keys are missing."""
        required_keys = [
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
            ("TAVILY_API_KEY", cls.TAVILY_API_KEY)
        ]
        
        missing = [key for key, val in required_keys if not val]
        
        if missing:
            raise EnvironmentError(f"❌ Missing critical environment variables: {', '.join(missing)}")
        else:
            print("✅ Configuration loaded successfully.")

# Run validation on import (optional, but safer)
Config.validate()