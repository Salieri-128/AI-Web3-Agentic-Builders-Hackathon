from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import ChatRequest, ChatResponse, StatusResponse
from app.services.agent_service import handle_user_message
from app.services.caw_service import is_caw_configured
from app.services.memory_service import is_memory_loaded, load_profile


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
        memory_loaded=is_memory_loaded(),
    )


@app.get("/api/profile")
async def profile() -> dict:
    return load_profile()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    result = await handle_user_message(request.message)
    return ChatResponse(**result)
