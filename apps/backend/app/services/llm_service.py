from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import llm_api_base_url, llm_api_key, llm_chat_completions_url, llm_fallback_models, llm_model


LLM_SYSTEM_PROMPT = """You are an AI stablecoin treasury manager for a Cobo Agentic Wallet demo.
Return only compact JSON with this shape:
{
  "reply": "short user-facing answer",
  "action": "wallet_status|audit_logs|submit_pact|transfer_proposal|execute_transfer|memory_update|none",
  "parameters": {
    "chain_id": "SETH",
    "token_id": "SETH_WBTC",
    "amount": "1",
    "destination": "0x...",
    "max_amount_usd": "101",
    "pact_id": "optional"
  }
}
Never claim that a pact is approved. Never approve pacts yourself. For funds movement, prefer submit_pact or transfer_proposal unless the user explicitly asks to execute an already approved pact."""

LLM_FINAL_ANSWER_PROMPT = """You are the chat-facing AI agent for a Cobo Agentic Wallet treasury demo.
Answer the user's latest message naturally, like a helpful ChatGPT-style assistant.
Use the provided tool results as ground truth. Do not invent balances, addresses, approvals, or transactions.
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
