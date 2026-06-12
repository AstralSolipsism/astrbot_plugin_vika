from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    name: str
    description: Optional[str] = ""
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None
    available: bool = True
    unavailable_reason: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class ExecuteRequest(BaseModel):
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    stream: Optional[bool] = True
    timeout_ms: Optional[int] = None


class ExecuteAccepted(BaseModel):
    job_id: str
    status: str = "queued"
    stream_url: Optional[str] = None


class ErrorDTO(BaseModel):
    code: str
    message: str
    retryable: Optional[bool] = False
    details: Optional[Dict[str, Any]] = None


class JobDTO(BaseModel):
    job_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[ErrorDTO] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: Optional[str] = None