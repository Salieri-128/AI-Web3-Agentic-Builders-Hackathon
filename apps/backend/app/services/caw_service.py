from __future__ import annotations

import os
from typing import Any


REQUIRED_CAW_ENV_VARS = (
    "AGENT_WALLET_API_URL",
    "AGENT_WALLET_API_KEY",
    "AGENT_WALLET_WALLET_ID",
)

CAW_NOT_CONFIGURED_MESSAGE = (
    "CAW is not configured. Please check AGENT_WALLET_API_URL, "
    "AGENT_WALLET_API_KEY, AGENT_WALLET_WALLET_ID."
)


def is_caw_configured() -> bool:
    return all(os.getenv(env_name) for env_name in REQUIRED_CAW_ENV_VARS)


async def get_audit_logs(result: str | None = None) -> list[dict[str, Any]]:
    if not is_caw_configured():
        return [{"reason": CAW_NOT_CONFIGURED_MESSAGE}]

    from cobo_agentic_wallet import WalletAPIClient

    client = WalletAPIClient(
        base_url=os.environ["AGENT_WALLET_API_URL"],
        api_key=os.environ["AGENT_WALLET_API_KEY"],
    )

    try:
        raw_logs = await _call_list_audit_logs(
            client=client,
            wallet_id=os.environ["AGENT_WALLET_WALLET_ID"],
            result=result,
        )
        return [_simplify_audit_log(log) for log in _coerce_log_items(raw_logs)]
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            maybe_awaitable = close()
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable


async def _call_list_audit_logs(
    client: Any,
    wallet_id: str,
    result: str | None,
) -> Any:
    list_audit_logs = getattr(client, "list_audit_logs")
    kwargs: dict[str, Any] = {"wallet_id": wallet_id}
    if result is not None:
        kwargs["result"] = result

    try:
        response = list_audit_logs(**kwargs)
    except TypeError:
        response = list_audit_logs(wallet_id, result) if result is not None else list_audit_logs(wallet_id)

    if hasattr(response, "__await__"):
        return await response
    return response


def _coerce_log_items(raw_logs: Any) -> list[Any]:
    if raw_logs is None:
        return []
    if isinstance(raw_logs, list):
        return raw_logs
    for key in ("items", "data", "logs", "audit_logs"):
        value = _read_field(raw_logs, key)
        if isinstance(value, list):
            return value
    return [raw_logs]


def _simplify_audit_log(log: Any) -> dict[str, Any]:
    simplified: dict[str, Any] = {}
    for field in ("action", "result", "created_at", "reason", "request_id"):
        value = _read_field(log, field)
        if value is not None:
            simplified[field] = value
    return simplified


def _read_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)
