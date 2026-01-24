from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any

def strict_config():
    return ConfigDict(extra="forbid")

class StyleProgram(BaseModel):
    """Internal compiled style guidance (kept short)."""
    model_config = strict_config()

    style_brief: str = Field(description="Short editorial brief (<= ~200 tokens).")
    constraints_summary: str = Field(description="Non-negotiables, short.")
    editorial_nos: List[str] = Field(default_factory=list)
    hero_strategy: Optional[str] = Field(default="Exactly one hero element.")
    trend_budget: Optional[int] = Field(default=1, description="Max number of trend-forward elements.")
