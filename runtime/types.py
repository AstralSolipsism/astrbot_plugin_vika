from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: Optional[str] = ""
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None
    available: bool = True
    unavailable_reason: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    domain: str = "general"
    risk: Literal["low", "medium", "high"] = "low"
    exposure: Literal["visible", "hidden"] = "hidden"
    result_policy: Dict[str, Any] = Field(default_factory=lambda: {"mode": "inline"})
    aliases: List[str] = Field(default_factory=list)
    capability_id: Optional[str] = None
    capability_aliases: List[str] = Field(default_factory=list)
    capability_priority: int = 100
    annotations: Dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True
    write: bool = False
    destructive: bool = False
