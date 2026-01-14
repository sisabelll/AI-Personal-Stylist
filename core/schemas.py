from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from enum import Enum

# --- CONFIG HELPER ---
# OpenAI Structured Outputs REQUIRE 'extra="forbid"' to guarantee no hallucinated keys.
def strict_config():
    return ConfigDict(extra="forbid")

# ==========================================
# 1. INTERPRETER SCHEMAS
# ==========================================

class HardConstraints(BaseModel):
    """
    Specific constraints extracted from user input.
    Replaces generic dicts to ensure strict validation.
    """
    model_config = strict_config()
    
    event_type: Optional[str] = Field(default=None, description="The specific event (e.g. 'Wedding', 'Job Interview').")
    weather: Optional[str] = Field(default=None, description="Weather constraints (e.g. 'Rainy', 'Hot').")
    budget: Optional[str] = Field(default=None, description="Budgetary mentions (e.g. 'Cheap', 'Luxury').")
    location: Optional[str] = Field(default=None, description="Specific location (e.g. 'NYC', 'Beach').")
    time_of_day: Optional[str] = Field(default=None, description="Time context (e.g. 'Evening', 'Day').")

class StyleInterpretation(BaseModel):
    """
    Output of the Context Interpreter Agent.
    """
    model_config = strict_config()

    reasoning_steps: List[str] = Field(description="Step-by-step logic for extracting these signals.")
    requested_items: List[str] = Field(default=[], description="Items the user explicitly wants to ADD.")
    items_to_remove: List[str] = Field(default=[], description="Items the user explicitly wants to REMOVE.")
    
    # We use the specific class instead of 'dict' to prevent validation errors
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints, description="Non-negotiable constraints.")
    
    vibe_modifiers: List[str] = Field(default=[], description="Style adjectives (edgy, casual).")


# ==========================================
# 2. STYLIST SCHEMAS
# ==========================================

class OutfitItem(BaseModel):
    model_config = strict_config()

    category: str = Field(description="Type of item (e.g., Top, Shoes).")
    item_name: str = Field(description="Specific name of the item.")
    reason: str = Field(description="Mention the specific Style Rule (Body Type, Color Season) that justified this choice.")

class OutfitOption(BaseModel):
    model_config = strict_config()

    name: str = Field(description="Creative name for this outfit.")
    description: str = Field(description="2-3 sentences explaining the vibe and why it fits.")
    items: List[OutfitItem]

class StylistRecommendation(BaseModel):
    """
    Output of the Main Stylist Agent.
    """
    model_config = strict_config()

    reasoning_steps: List[str] = Field(description="Internal monologue balancing constraints. Concise bullet points.")
    outfit_options: List[OutfitOption]


# ==========================================
# 3. REFINEMENT SCHEMAS
# ==========================================

class RefinementAnalysis(BaseModel):
    """
    Output of the Refinement Interpreter (Feedback Analyzer).
    """
    model_config = strict_config()

    make_more: List[str] = Field(default=[], description="Attributes to enhance (e.g., 'more edgy').")
    make_less: List[str] = Field(default=[], description="Attributes to reduce (e.g., 'less formal').")
    swap_out: List[str] = Field(default=[], description="Specific items to replace.")
    emotional_goal: Optional[str] = Field(default=None, description="New emotional target.")
    expressed_likes: List[str] = Field(default=[], description="Things the user specifically liked.")
    expressed_dislikes: List[str] = Field(default=[], description="Things the user specifically disliked.")


# ==========================================
# 4. RESEARCHER SCHEMAS
# ==========================================

class StyleResearchDoc(BaseModel):
    """
    Output of the Style Researcher Agent.
    """
    model_config = strict_config()

    name: str = Field(description="Name of the entity.")
    vibe: str = Field(description="Short phrase capturing the essence.")
    wardrobe_staples: List[str] = Field(description="Everyday basics worn frequently.")
    statement_pieces: List[str] = Field(description="Distinctive, loud, or iconic items.")
    fabric_preferences: List[str] = Field(description="Key materials.")
    color_palette: List[str] = Field(description="Dominant colors.")

# ==========================================
# 5. USER INTENT SCHEMAS
# ==========================================

class UserActionType(str, Enum):
    MODIFY_OUTFIT = "modify_outfit"
    ASK_QUESTION = "ask_question"
    FINALIZE_OUTFIT = "finalize_outfit"
    RESET_SESSION = "reset_session"

class UserIntent(BaseModel):
    """Classifies the user's latest input to determine the system's next step."""
    model_config = strict_config()

    reasoning: str = Field(description="Analyze the grammar. Is it a Command vs. a Question? Explain here.")
    action: UserActionType = Field(description="The primary goal of the user.")

# ==========================================
# 6. OUTFIT ITEM SCHEMA (with Search Query)
# ==========================================
class OutfitItem(BaseModel):
    model_config = strict_config()

    category: str = Field(description="Type of item (e.g., Top, Shoes).")
    item_name: str = Field(description="Display name (e.g. 'Silk Camisole').")
    search_query: str = Field(description="Specific keywords to find this EXACT vibe online. INCLUDE brands or aesthetics. (e.g. 'Reformation navy silk camisole 90s vintage style').")
    
    reason: str = Field(description="Why this fits the constraints.")