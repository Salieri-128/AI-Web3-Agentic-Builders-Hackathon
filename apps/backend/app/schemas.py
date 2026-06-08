from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class StatusResponse(BaseModel):
    backend: str
    agent: str
    caw_configured: bool
    llm_configured: bool
    memory_loaded: bool


class ChatResponse(BaseModel):
    reply: str
    llm_used: bool
    caw_used: bool
    memory_updated: bool
    proposal: dict[str, Any] | None
    wallet: dict[str, Any] | None = None
    audit_logs: list[dict[str, Any]]
    profile: dict[str, Any] | None


class PactProposalRequest(BaseModel):
    intent: str
    chain_id: str = "SETH"
    token_id: str = "SETH_WBTC"
    destination: str
    amount: str
    max_amount_usd: str | None = None


class TransferRequest(BaseModel):
    pact_id: str
    chain_id: str
    token_id: str
    destination: str
    amount: str
    request_id: str | None = None
    execute: bool = False


class TreasuryInitializeRequest(BaseModel):
    deposit_amount: str = "1000"


class TreasuryTransferRequest(BaseModel):
    destination: str
    amount: str
    pact_id: str | None = None
    execute: bool = False


class PactApprovalRequest(BaseModel):
    pact_id: str


class AavePactRequest(BaseModel):
    max_amount: str = "100"


class AaveActionRequest(BaseModel):
    pact_id: str
    amount: str


class CawActionResponse(BaseModel):
    status: str
    message: str
    data: dict[str, Any] | list[dict[str, Any]] | None = None
