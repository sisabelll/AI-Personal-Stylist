import logging
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the root directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Configure logging once at import time.
# Set LOG_LEVEL=DEBUG in .env to see detailed debug output.
_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _level, logging.INFO),
    format="%(levelname)s [%(name)s] %(message)s",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


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

    @classmethod
    def validate(cls):
        """Checks if critical keys are missing."""
        required_keys = [
            ("OPENAI_API_KEY", cls.OPENAI_API_KEY),
            ("TAVILY_API_KEY", cls.TAVILY_API_KEY),
        ]
        missing = [key for key, val in required_keys if not val]
        if missing:
            raise EnvironmentError(f"Missing critical environment variables: {', '.join(missing)}")


# Run validation on import
Config.validate()