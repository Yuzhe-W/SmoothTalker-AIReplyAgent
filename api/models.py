from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


Role = Literal["crush", "colleague"]


class GenerateRequest(BaseModel):
    incoming_text: str = Field(..., min_length=1)
    role: Role
    thread_id: str = Field(..., min_length=1, description="Stable conversation identifier")
    user_id: Optional[str] = Field(None, description="External user identifier (optional)")


class GenerateResponse(BaseModel):
    options: List[str]
    session_id: str
    meta: dict[str, Any]


class SelectRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    thread_id: str = Field(..., min_length=1)
    option_index: int = Field(..., ge=0, le=2)
    user_id: Optional[str] = Field(None, description="External user identifier (optional)")


class ThreadsRequest(BaseModel):
    role: Role
    user_id: Optional[str] = Field(None, description="External user identifier (optional)")
    limit: int = Field(12, ge=1, le=50)


class DeleteThreadRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    role: Role
    user_id: Optional[str] = Field(None, description="External user identifier (optional)")


class ThreadItem(BaseModel):
    thread_id: str
    role: Role
    summary: str
    updated_at: str


class ThreadsResponse(BaseModel):
    threads: List[ThreadItem]


class SimpleResponse(BaseModel):
    ok: bool


class Metrics(BaseModel):
    provider: str
    model: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
