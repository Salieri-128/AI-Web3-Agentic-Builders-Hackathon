from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import CawActionResponse, ChatRequest, ChatResponse, PactProposalRequest, StatusResponse, TransferRequest
from app.services.agent_service import handle_user_message
from app.services.caw_service import get_audit_logs, get_wallet_status, is_caw_configured, submit_transfer_pact, transfer_tokens_with_pact
from app.services.llm_service import is_llm_configured
from app.services.memory_service import is_memory_loaded, load_profile


ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

app = FastAPI(title="Agentic Treasury Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentic-treasury-backend"}


@app.get("/api/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    return StatusResponse(
        backend="ok",
        agent="ok",
        caw_configured=is_caw_configured(),
        llm_configured=is_llm_configured(),
        memory_loaded=is_memory_loaded(),
    )


@app.get("/api/profile")
async def profile() -> dict:
    return load_profile()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    result = await handle_user_message(request.message)
    return ChatResponse(**result)


@app.get("/api/caw/wallet", response_model=CawActionResponse)
async def caw_wallet() -> CawActionResponse:
    wallet = await get_wallet_status()
    return CawActionResponse(status="ok", message="Wallet status loaded", data=wallet)


@app.get("/api/caw/audit-logs", response_model=CawActionResponse)
async def caw_audit_logs() -> CawActionResponse:
    logs = await get_audit_logs()
    return CawActionResponse(status="ok", message="Audit logs loaded", data=logs)


@app.post("/api/caw/pacts", response_model=CawActionResponse)
async def caw_submit_pact(request: PactProposalRequest) -> CawActionResponse:
    pact = await submit_transfer_pact(
        intent=request.intent,
        chain_id=request.chain_id,
        token_id=request.token_id,
        destination=request.destination,
        amount=request.amount,
        max_amount_usd=request.max_amount_usd,
    )
    return CawActionResponse(status="submitted", message="Pact proposal submitted to CAW", data=pact)


@app.post("/api/caw/transfers", response_model=CawActionResponse)
async def caw_transfer(request: TransferRequest) -> CawActionResponse:
    result = await transfer_tokens_with_pact(
        pact_id=request.pact_id,
        chain_id=request.chain_id,
        token_id=request.token_id,
        destination=request.destination,
        amount=request.amount,
        request_id=request.request_id,
        execute=request.execute,
    )
    return CawActionResponse(status=str(result.get("status", "ok")), message="Transfer route completed", data=result)
