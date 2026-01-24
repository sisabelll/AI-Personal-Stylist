from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any

def strict_config():
    return ConfigDict(extra="forbid")

class StyleProgram(BaseModel):
    model_config = strict_config()
    style_brief: str = Field(description="1-3 sentences: editorial brief for this request.")
    constraints_summary: List[str] = Field(default_factory=list, description="Non-negotiables.")
    editorial_nos: List[str] = Field(default_factory=list, description="Hard taste no's.")
    hero_strategy: str = Field(description="How to create a single clear point of view.")
    trend_budget: int = Field(default=1, ge=0, le=3)