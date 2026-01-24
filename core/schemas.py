from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, List, Optional, Literal
from enum import Enum

# --- CONFIG HELPER ---
# OpenAI Structured Outputs REQUIRE 'extra="forbid"' to guarantee no hallucinated keys.
def strict_config():
    return ConfigDict(extra="forbid")

# ==========================================
# 1. INTERPRETER SCHEMAS (Input Analysis)
# ==========================================
class EnvironmentConstraints(BaseModel):
    """Physical constraints driven by weather or activity."""
    model_config = strict_config()

    layering: Optional[Literal["none", "light", "heavy"]] = Field(
        default="none", 
        description="Required warmth level based on weather/context"
    )
    footwear_resistance: Optional[Literal["normal", "weather_safe"]] = Field(
        default="normal",
        description="Whether shoes need to handle rain/snow/mud"
    )

class HardConstraints(BaseModel):
    """Specific situational limits extracted from user input."""
    model_config = strict_config()
    
    event_type: Optional[str] = Field(description="The specific event (e.g. 'Wedding', 'Job Interview').")
    budget: Optional[Literal["economy", "standard", "luxury"]] = Field(default="standard")
    time_of_day: Optional[Literal["day", "evening", "night"]] = Field(default="day")
    
    environment: EnvironmentConstraints = Field(default_factory=EnvironmentConstraints)

class StyleInterpretation(BaseModel):
    """Output of the Context Interpreter Agent."""
    model_config = strict_config()

    # A. CoT (Chain of Thought) - Helps debugging
    reasoning_steps: List[str] = Field(
        description="Brief step-by-step logic. e.g. ['User mentioned dinner', 'Implies evening polish']."
    )

    # B. Strict Style Dimensions (The "Knobs" we can turn)
    formality_level: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="How formal the outfit needs to be."
    )
    social_tone: Literal["relaxed", "warm", "polished", "professional"] = Field(
        default="polished",
        description="The emotional vibe of the setting."
    )
    aesthetic_bias: Literal["quiet_luxury", "clean_chic", "romantic", "neutral", "edgy"] = Field(
        default="clean_chic",
        description="The visual filter to apply to the recommendations."
    )

    # C. Item Actions
    requested_items: List[str] = Field(
        default=[], 
        description="Specific items the user EXPLICITLY wants to wear (e.g. 'my black skirt')."
    )
    items_to_remove: List[str] = Field(
        default=[], 
        description="Items the user explicitly DISLIKES or wants to swap out."
    )
    
    # D. The "Catch-All" (For nuance)
    hard_constraints: HardConstraints = Field(default_factory=HardConstraints)
    vibe_modifiers: List[str] = Field(
        default=[], 
        description="Extra adjectives that don't fit the strict buckets (e.g. 'cozy', 'sexy')."
    )


# ==========================================
# 2. RESEARCHER SCHEMAS
# ==========================================

class StyleResearchDoc(BaseModel):
    """Output of the Style Researcher Agent."""
    model_config = strict_config()

    name: str = Field(description="Name of the entity.")
    vibe: str = Field(description="Short phrase capturing the essence.")
    wardrobe_staples: List[str] = Field(description="Everyday basics worn frequently.")
    statement_pieces: List[str] = Field(description="Distinctive, loud, or iconic items.")
    fabric_preferences: List[str] = Field(description="Key materials.")
    color_palette: List[str] = Field(description="Dominant colors.")


# ==========================================
# 3. REFINEMENT SCHEMAS (Feedback)
# ==========================================
class AttributeCorrection(BaseModel):
    model_config = strict_config()

    target_category: Literal["Top", "Bottom", "Shoes", "Outerwear", "Accessory", "Accessories", "Dress", "Jumpsuit"] = Field(
        description="Which category the correction applies to."
    )
    must_include: List[str] = Field(
        default_factory=list,
        description="Attributes that must be reflected (e.g., 'beige', 'no buckle', 'smooth leather', 'not furry')."
    )
    must_avoid: List[str] = Field(
        default_factory=list,
        description="Attributes that must not appear (e.g., 'furry', 'shearling', 'buckles')."
    )
    note: Optional[str] = Field(
        default=None,
        description="Any extra nuance in plain language."
    )

class RefinementAnalysis(BaseModel):
    """Output of the Refinement Interpreter."""
    model_config = strict_config()

    make_more: List[str] = Field(default=[], description="Attributes to enhance (e.g., 'more edgy').")
    make_less: List[str] = Field(default=[], description="Attributes to reduce (e.g., 'less formal').")
    swap_out: List[str] = Field(default=[], description="Specific items to replace.")
    attribute_corrections: List[AttributeCorrection] = Field(default_factory=list)
    emotional_goal: Optional[str] = Field(default=None, description="New emotional target.")
    expressed_likes: List[str] = Field(default=[], description="Things the user specifically liked.")
    expressed_dislikes: List[str] = Field(default=[], description="Things the user specifically disliked.")


# ==========================================
# 4. USER INTENT SCHEMAS
# ==========================================

class UserActionType(str, Enum):
    MODIFY_OUTFIT = "modify_outfit"
    ASK_QUESTION = "ask_question"
    FINALIZE_OUTFIT = "finalize_outfit"
    RESET_SESSION = "reset_session"

class UserIntent(BaseModel):
    """Classifies the user's latest input."""
    model_config = strict_config()

    reasoning: str = Field(description="Analyze the grammar. Is it a Command vs. a Question? Explain here.")
    action: UserActionType = Field(description="The primary goal of the user.")


# ==========================================
# 5. STYLIST OUTPUT SCHEMAS (The Main Event)
# ==========================================

class OutfitItem(BaseModel):
    """A single item in the outfit."""
    model_config = strict_config()

    category: str = Field(description="Type of item (e.g., Top, Shoes).")
    item_name: str = Field(description="Display name (e.g. 'Silk Camisole').")
    search_query: str = Field(description="Specific keywords to find this EXACT vibe online. INCLUDE brands or aesthetics. (e.g. 'Reformation navy silk camisole 90s vintage style').")
    reason: str = Field(description="Why this specific item fits the constraints.")

class OutfitOption(BaseModel):
    """A full outfit grouping."""
    model_config = strict_config()

    name: str = Field(description="Creative name for this look (e.g. 'Rainy Day Chic').")
    items: List[OutfitItem]

class StylingRationale(BaseModel):
    model_config = strict_config()
    color_season_fit: str = Field(description="2-4 sentences: why palette works for user's color season.")
    body_essence_fit: str = Field(description="2-4 sentences: why silhouette/lines work for user's body essence.")
    inspiration_translation: str = Field(description="2-4 sentences: how this channels the inspiration without cosplay.")
    hero_item_and_balance: str = Field(description="1-3 sentences: what the hero is + how the rest supports it.")
    key_proportion_moves: List[str] = Field(description="Bullet list of proportion choices that make the look flattering.")

class OutfitRecommendation(BaseModel):
    """The final response from the Stylist Agent."""
    model_config = strict_config()

    id: str
    occasion: str
    season: str
    reasoning: str = Field(description="EXECUTIVE SUMMARY: A 2-3 sentence pitch to the client explaining the vibe, why it works for the weather/event, and the style strategy used.")
    outfit_options: List[OutfitOption]
    styling_rationale: StylingRationale

# ==========================================
# 6. FEEDBACK SCHEMAS (Critique & Edit Plan)
# ==========================================

class EditAction(BaseModel):
    model_config = strict_config()
    target_category: Literal["Top", "Bottom", "Shoes", "Outerwear", "Accessory", "Dress", "Jumpsuit", "Other"]
    action_type: Literal["swap", "add", "remove", "restyle", "tighten_query"]
    instruction: str

class EditPlan(BaseModel):
    model_config = strict_config()
    hero: str = Field(description="Name the hero item or hero move.")
    actions: List[EditAction] = Field(default_factory=list, description="Max 2 actions.")

class OutfitCritique(BaseModel):
    model_config = strict_config()
    score: int = Field(ge=1, le=10)
    verdict: Literal["accept", "revise"]
    summary: str
    main_issue: str
    plan: EditPlan
