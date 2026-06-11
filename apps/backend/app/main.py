from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import (
    AaveActionRequest,
    AavePactRequest,
    CawActionResponse,
    ChatRequest,
    ChatResponse,
    PactApprovalRequest,
    PactProposalRequest,
    StatusResponse,
    TransferRequest,
    TreasuryInitializeRequest,
    TreasuryTransferRequest,
)
from app.services.aave_service import (
    execute_aave_supply,
    execute_aave_withdraw,
    get_aave_wallet_state,
)
from app.services.agent_service import handle_user_message
from app.services.caw_service import get_audit_logs, get_wallet_status, is_caw_configured, submit_transfer_pact, transfer_tokens_with_pact
from app.services.llm_service import is_llm_configured
from app.services.memory_service import is_memory_loaded, load_profile
from app.services.treasury_service import (
    approve_local_pact,
    execute_ready_pending_transfer,
    get_pending_transfer_status,
    get_treasury_state,
    initialize_wallet,
    preview_rebalance,
    run_daily_rebalance,
    send_asset,
    submit_internal_rebalance_pact,
    sync_treasury,
)


ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")
load_dotenv()

app = FastAPI(title="Agentic Treasury Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
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


@app.get("/api/treasury", response_model=CawActionResponse)
async def treasury_state() -> CawActionResponse:
    return CawActionResponse(status="ok", message="Treasury state loaded", data=await get_treasury_state())


@app.post("/api/treasury/initialize", response_model=CawActionResponse)
async def treasury_initialize(request: TreasuryInitializeRequest) -> CawActionResponse:
    result = await initialize_wallet(request.deposit_amount)
    return CawActionResponse(status="initialized", message="Demo wallet initialized", data=result)


@app.post("/api/treasury/rebalance", response_model=CawActionResponse)
async def treasury_rebalance() -> CawActionResponse:
    result = await run_daily_rebalance()
    return CawActionResponse(status=str(result.get("status", "ok")), message="Daily rebalance completed", data=result)


@app.post("/api/treasury/rebalance/preview", response_model=CawActionResponse)
async def treasury_rebalance_preview() -> CawActionResponse:
    result = await preview_rebalance()
    return CawActionResponse(status=str(result.get("action", "hold")), message="Rebalance preview loaded", data=result)


@app.post("/api/treasury/sync", response_model=CawActionResponse)
async def treasury_sync() -> CawActionResponse:
    result = await sync_treasury()
    return CawActionResponse(status=str(result.get("status", "synced")), message="Treasury balances synced", data=result)


@app.post("/api/treasury/transfers", response_model=CawActionResponse)
async def treasury_transfer(request: TreasuryTransferRequest) -> CawActionResponse:
    result = await send_asset(
        destination=request.destination,
        amount=request.amount,
        pact_id=request.pact_id,
        execute=request.execute,
    )
    return CawActionResponse(status=str(result.get("status", "ok")), message="Transfer flow completed", data=result)


@app.post("/api/treasury/transfers/pending/execute", response_model=CawActionResponse)
async def treasury_execute_pending_transfer() -> CawActionResponse:
    result = await execute_ready_pending_transfer()
    return CawActionResponse(status=str(result.get("status", "ok")), message="Pending transfer check completed", data=result)


@app.get("/api/treasury/transfers/pending/status", response_model=CawActionResponse)
async def treasury_pending_transfer_status() -> CawActionResponse:
    result = await get_pending_transfer_status()
    return CawActionResponse(status=str(result.get("status", "ok")), message="Pending transfer status loaded", data=result)


@app.post("/api/treasury/pacts/approve", response_model=CawActionResponse)
async def treasury_approve_pact(request: PactApprovalRequest) -> CawActionResponse:
    result = await approve_local_pact(request.pact_id)
    return CawActionResponse(status=str(result.get("status", "ok")), message="Local pact approval completed", data=result)


@app.get("/api/aave", response_model=CawActionResponse)
async def aave_state() -> CawActionResponse:
    result = await get_aave_wallet_state()
    return CawActionResponse(status=str(result.get("status", "ok")), message="Aave Sepolia state loaded", data=result)


@app.post("/api/aave/pacts", response_model=CawActionResponse)
async def aave_submit_pact(request: AavePactRequest) -> CawActionResponse:
    result = await submit_internal_rebalance_pact(max_amount=request.max_amount)
    return CawActionResponse(status=str(result.get("status", "submitted")), message="Aave contract-call pact submitted", data=result)


@app.post("/api/aave/supply", response_model=CawActionResponse)
async def aave_supply(request: AaveActionRequest) -> CawActionResponse:
    result = await execute_aave_supply(pact_id=request.pact_id, amount=request.amount)
    return CawActionResponse(status=str(result.get("status", "ok")), message="Aave supply completed", data=result)


@app.post("/api/aave/withdraw", response_model=CawActionResponse)
async def aave_withdraw(request: AaveActionRequest) -> CawActionResponse:
    result = await execute_aave_withdraw(pact_id=request.pact_id, amount=request.amount)
    return CawActionResponse(status=str(result.get("status", "ok")), message="Aave withdraw completed", data=result)
