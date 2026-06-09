from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import llm_api_base_url, llm_api_key, llm_chat_completions_url, llm_fallback_models, llm_model


LLM_SYSTEM_PROMPT = """You are the intent parser for a Cobo Agentic Wallet treasury demo.
Return only compact JSON with this shape:
{
  "reply": "short user-facing answer",
  "action": "wallet_status|audit_logs|treasury_transfer|memory_update|treasury_status|treasury_rebalance|aave_status|none",
  "parameters": {
    "chain_id": "SETH",
    "token_id": "WBTC",
    "amount": "1",
    "max_amount": "1",
    "destination": "0x..."
  }
}
Your role is intent classification and parameter extraction only.
Never decide whether a Pact is usable, never decide whether to submit or approve a Pact, and never decide whether to execute a transaction.
For any user request that asks to send, transfer, or pay funds to a destination address, return action "treasury_transfer".
The backend tool layer will then check balance, check local Pact permissions, submit a scoped Pact if needed, wait for owner approval, and execute inside the approved boundary."""

LLM_FINAL_ANSWER_PROMPT = """You are the chat-facing AI agent for a Cobo Agentic Wallet treasury demo.
Answer the user's latest message naturally, like a helpful ChatGPT-style assistant.
Use the provided tool results as ground truth. Do not invent balances, addresses, approvals, or transactions.
For funds movement, do not reinterpret parsed amounts or Pact decisions. Report only the tool result.
If wallet balances are present, state the exact token amount, token, and chain.
For direct balance questions such as "钱包有多少钱", answer simply and directly:
- list native Sepolia ETH/SETH balance
- list Sepolia WBTC wallet balance
- list Aave Sepolia aWBTC/yield balance
- include the wallet address if available
Do not say a token is missing just because one tool omitted it; use the merged treasury/aave results when present.
If a Pact or transaction requires approval, say so clearly.
Use short paragraphs or simple bullet lines. Do not use markdown tables.
Reply in the same language as the user unless the user asks otherwise."""

LLM_TRANSFER_FLOW_PROMPT = """You are the transfer-flow controller for a Cobo Agentic Wallet demo.
You may decide the next step only from the tool data provided by the backend.
The backend tools still enforce balance checks, Pact limits, CAW approval, and execution safety.

Return only compact JSON:
{
  "decision": "insufficient_balance|use_existing_pact|submit_new_pact|wait_for_pact_approval|execute_with_pact|transfer_complete|transfer_failed",
  "pact_id": "optional local pact_id or CAW pact_id",
  "reason": "short reason"
}

Rules:
- If wallet balance is lower than the requested amount, choose insufficient_balance.
- A usable transfer Pact must be active, match destination, chain, token, and allow the requested token amount.
- For external transfer requests, compare token amount only. Do not introduce or infer USD limits.
- max_amount, if present, is denominated in the same token as amount, not USD.
- Do not use legacy transfer Pacts whose CAW spec contains amount_usd_gt for token amount requests.
- If no usable Pact exists, choose submit_new_pact.
- If a submitted Pact is not active yet, choose wait_for_pact_approval.
- If a usable Pact exists, choose use_existing_pact or execute_with_pact and include pact_id.
- Never claim that you approved a Pact yourself."""


def is_llm_configured() -> bool:
    return bool(llm_api_key())


async def route_with_llm(message: str, profile: dict[str, Any] | None) -> dict[str, Any]:
    if not is_llm_configured():
        return {
            "reply": "LLM service is not configured. Add api_key, LLM_API_KEY, or OPENAI_API_KEY to .env.",
            "action": "none",
            "parameters": {},
            "llm_used": False,
        }

    last_error: RuntimeError | None = None
    async with httpx.AsyncClient(timeout=30) as client:
        for model in _candidate_models():
            payload = _build_payload(message=message, profile=profile, model=model)
            response = await _post_chat_completion(client, payload)
            if response.status_code == 400 and "response_format" in payload:
                fallback_payload = payload.copy()
                fallback_payload.pop("response_format", None)
                response = await _post_chat_completion(client, fallback_payload)
            try:
                _raise_for_llm_error(response)
            except RuntimeError as error:
                last_error = error
                if _is_model_unavailable_error(response):
                    continue
                raise
            break
        else:
            raise last_error or RuntimeError("LLM API request failed.")

    content = response.json()["choices"][0]["message"]["content"]
    parsed = _parse_json_content(content)
    parsed["llm_used"] = True
    parsed["llm_model"] = response.json()["model"] if "model" in response.json() else payload["model"]
    parsed.setdefault("parameters", {})
    parsed.setdefault("action", "none")
    parsed.setdefault("reply", "I parsed your request.")
    return parsed


async def compose_agent_reply(
    *,
    message: str,
    profile: dict[str, Any] | None,
    route_result: dict[str, Any],
    tool_results: dict[str, Any],
) -> str:
    if not is_llm_configured():
        return ""

    payload_messages = [
        {"role": "system", "content": LLM_FINAL_ANSWER_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": message,
                    "memory_profile": profile or {},
                    "routing_result": route_result,
                    "tool_results": tool_results,
                },
                ensure_ascii=False,
            ),
        },
    ]

    last_error: RuntimeError | None = None
    async with httpx.AsyncClient(timeout=30) as client:
        for model in _candidate_models():
            payload = {
                "model": model,
                "messages": payload_messages,
                "temperature": 0.4,
            }
            response = await _post_chat_completion(client, payload)
            try:
                _raise_for_llm_error(response)
            except RuntimeError as error:
                last_error = error
                if _is_model_unavailable_error(response):
                    continue
                raise
            content = response.json()["choices"][0]["message"]["content"]
            return content.strip()

    raise last_error or RuntimeError("LLM final answer request failed.")


async def decide_transfer_flow(
    *,
    message: str,
    profile: dict[str, Any] | None,
    transfer_request: dict[str, Any],
    stage: str,
    tool_state: dict[str, Any],
) -> dict[str, Any]:
    if not is_llm_configured():
        return {
            "decision": "fallback",
            "pact_id": "",
            "reason": "LLM is not configured; backend fallback will choose the next safe step.",
            "llm_used": False,
        }

    payload_messages = [
        {"role": "system", "content": LLM_TRANSFER_FLOW_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": message,
                    "memory_profile": profile or {},
                    "transfer_request": transfer_request,
                    "stage": stage,
                    "tool_state": tool_state,
                },
                ensure_ascii=False,
            ),
        },
    ]

    last_error: RuntimeError | None = None
    async with httpx.AsyncClient(timeout=30) as client:
        for model in _candidate_models():
            payload = {
                "model": model,
                "messages": payload_messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            response = await _post_chat_completion(client, payload)
            if response.status_code == 400 and "response_format" in payload:
                fallback_payload = payload.copy()
                fallback_payload.pop("response_format", None)
                response = await _post_chat_completion(client, fallback_payload)
            try:
                _raise_for_llm_error(response)
            except RuntimeError as error:
                last_error = error
                if _is_model_unavailable_error(response):
                    continue
                raise
            parsed = _parse_json_content(response.json()["choices"][0]["message"]["content"])
            return {
                "decision": str(parsed.get("decision", "transfer_failed")),
                "pact_id": str(parsed.get("pact_id", "")),
                "reason": str(parsed.get("reason", "")),
                "llm_used": True,
                "llm_model": response.json().get("model", model),
            }

    raise last_error or RuntimeError("LLM transfer-flow decision request failed.")


def _candidate_models() -> list[str]:
    models: list[str] = []
    for model in [llm_model(), *llm_fallback_models()]:
        if model and model not in models:
            models.append(model)
    return models


def _build_payload(*, message: str, profile: dict[str, Any] | None, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": message,
                        "memory_profile": profile or {},
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }


def _chat_completions_url() -> str:
    configured_url = llm_chat_completions_url()
    if configured_url:
        return configured_url

    base_url = llm_api_base_url().rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


async def _post_chat_completion(client: httpx.AsyncClient, payload: dict[str, Any]) -> httpx.Response:
    return await client.post(
        _chat_completions_url(),
        headers={
            "Authorization": f"Bearer {llm_api_key()}",
            "Content-Type": "application/json",
        },
        json=payload,
    )


def _raise_for_llm_error(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise RuntimeError("LLM API returned 401 Unauthorized. Check api_key/LLM_API_KEY and API_URL/BASE_URL.")
    if response.status_code == 404:
        raise RuntimeError("LLM API returned 404. Check whether API_URL/BASE_URL should include /v1.")
    if response.status_code == 400:
        raise RuntimeError(f"LLM API returned 400 Bad Request: {_short_response_text(response)}")
    response.raise_for_status()


def _short_response_text(response: httpx.Response) -> str:
    text = response.text.strip().replace("\n", " ")
    return text[:400] if text else "empty response body"


def _is_model_unavailable_error(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    text = response.text.lower()
    return "no healthy deployments" in text or "model" in text and "not" in text and "found" in text


def _parse_json_content(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))
