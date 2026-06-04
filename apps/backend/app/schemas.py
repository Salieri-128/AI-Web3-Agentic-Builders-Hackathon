from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class StatusResponse(BaseModel):
    backend: str
    agent: str
    caw_configured: bool
    memory_loaded: bool


class ChatResponse(BaseModel):
    reply: str
    caw_used: bool
    memory_updated: bool
    proposal: dict[str, Any] | None
    audit_logs: list[dict[str, Any]]
    profile: dict[str, Any] | None
