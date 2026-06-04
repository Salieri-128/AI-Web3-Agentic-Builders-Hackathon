from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.config import caw_api_key, caw_api_url, caw_wallet_id


REQUIRED_CAW_ENV_VARS = (
    "AGENT_WALLET_API_URL",
    "AGENT_WALLET_API_KEY",
    "AGENT_WALLET_WALLET_ID",
)

CAW_NOT_CONFIGURED_MESSAGE = (
    "CAW is not configured. Please set API URL, API key, and wallet ID. "
    "Supported names include AGENT_WALLET_*, CAW_*, COBO_*, and WALLET_ID aliases."
)


def is_caw_configured() -> bool:
    return bool(caw_api_url() and caw_api_key() and caw_wallet_id())


async def get_wallet_status() -> dict[str, Any]:
    if not is_caw_configured():
        return {"reason": CAW_NOT_CONFIGURED_MESSAGE}

    try:
        async with _wallet_client() as client:
            wallet_id = _required_caw_wallet_id()
            wallet = await _maybe_await(_call_with_fallback(client.get_wallet, wallet_id, wallet_uuid=wallet_id))
            addresses = await _safe_items_call(client, "list_wallet_addresses", wallet_id)
            balances = await _safe_items_call(client, "list_balances", wallet_uuid=wallet_id)
            return {
                "wallet": _simplify_wallet(wallet),
                "addresses": [_simplify_address(address) for address in addresses],
                "balances": [_simplify_balance(balance) for balance in balances],
            }
    except Exception as error:
        return _service_error(error)


async def get_audit_logs(result: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    if not is_caw_configured():
        return [{"reason": CAW_NOT_CONFIGURED_MESSAGE}]

    try:
        async with _wallet_client() as client:
            raw_logs = await _call_list_audit_logs(
                client=client,
                wallet_id=_required_caw_wallet_id(),
                result=result,
                limit=limit,
            )
            return [_simplify_audit_log(log) for log in _coerce_items(raw_logs)]
    except Exception as error:
        return [_service_error(error)]


async def submit_transfer_pact(
    *,
    intent: str,
    chain_id: str,
    token_id: str,
    destination: str,
    amount: str,
    max_amount_usd: str | None = None,
) -> dict[str, Any]:
    if not is_caw_configured():
        return {"reason": CAW_NOT_CONFIGURED_MESSAGE}

    cap = max_amount_usd or amount
    spec = build_transfer_pact_spec(
        chain_id=chain_id,
        token_id=token_id,
        destination=destination,
        amount=amount,
        max_amount_usd=cap,
    )
    try:
        async with _wallet_client() as client:
            result = await client.submit_pact(
                wallet_id=_required_caw_wallet_id(),
                intent=intent,
                spec=spec,
            )
            return _as_dict(result)
    except Exception as error:
        return _service_error(error)


async def get_pact(pact_id: str) -> dict[str, Any]:
    if not is_caw_configured():
        return {"reason": CAW_NOT_CONFIGURED_MESSAGE}

    try:
        async with _wallet_client() as client:
            pact = await client.get_pact(pact_id)
            return _redact_sensitive(_as_dict(pact))
    except Exception as error:
        return _service_error(error)


async def transfer_tokens_with_pact(
    *,
    pact_id: str,
    chain_id: str,
    token_id: str,
    destination: str,
    amount: str,
    request_id: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    if not is_caw_configured():
        return {"reason": CAW_NOT_CONFIGURED_MESSAGE}

    if not execute:
        return {
            "status": "proposal_only",
            "execution_enabled": False,
            "reason": "Set execute=true only after the user explicitly approves execution.",
            "request": {
                "pact_id": pact_id,
                "chain_id": chain_id,
                "token_id": token_id,
                "destination": destination,
                "amount": amount,
            },
        }

    if os.getenv("CAW_ENABLE_REAL_EXECUTION", "").lower() != "true":
        return {
            "status": "blocked_by_backend_guard",
            "execution_enabled": False,
            "reason": "Real CAW transfers require CAW_ENABLE_REAL_EXECUTION=true in backend .env.",
        }

    try:
        async with _wallet_client() as owner_client:
            pact = await owner_client.get_pact(pact_id)
            pact_dict = _as_dict(pact)
            if pact_dict.get("status") != "active":
                return {
                    "status": "pact_not_active",
                    "reason": f"Pact status is {pact_dict.get('status', 'unknown')}. Wait for owner approval.",
                }
            pact_api_key = pact_dict.get("api_key")
            if not pact_api_key:
                return {"status": "missing_pact_api_key", "reason": "CAW did not return a pact-scoped API key."}

        async with _wallet_client(api_key=pact_api_key) as pact_client:
            result = await pact_client.transfer_tokens(
                _required_caw_wallet_id(),
                chain_id=chain_id,
                dst_addr=destination,
                token_id=token_id,
                amount=amount,
                request_id=request_id or f"agentic-treasury-{uuid.uuid4()}",
            )
            return _redact_sensitive(_as_dict(result))
    except Exception as error:
        return _service_error(error)


def build_transfer_pact_spec(
    *,
    chain_id: str,
    token_id: str,
    destination: str,
    amount: str,
    max_amount_usd: str,
) -> dict[str, Any]:
    # The pact is the permission boundary: it allowlists chain, token, destination, and caps spend.
    return {
        "policies": [
            {
                "name": "stablecoin-transfer",
                "type": "transfer",
                "rules": {
                    "effect": "allow",
                    "when": {
                        "chain_in": [chain_id],
                        "token_in": [{"chain_id": chain_id, "token_id": token_id}],
                        "destination_address_in": [{"chain_id": chain_id, "address": destination}],
                    },
                    "deny_if": {"amount_usd_gt": max_amount_usd},
                },
            }
        ],
        "completion_conditions": [{"type": "tx_count", "threshold": "1"}],
        "execution_plan": (
            "# Summary\n"
            f"Transfer {amount} {token_id} to {destination} on {chain_id}.\n\n"
            "# Operations\n"
            f"- Transfer {amount} {token_id} on {chain_id}\n\n"
            "# Risk Controls\n"
            f"- Destination allowlist: {destination}\n"
            f"- Max spend cap: {max_amount_usd} USD\n"
            "- One-time transfer only"
        ),
    }


@asynccontextmanager
async def _wallet_client(api_key: str | None = None) -> AsyncIterator[Any]:
    try:
        from cobo_agentic_wallet import WalletAPIClient
    except ModuleNotFoundError as error:
        raise RuntimeError("Missing dependency: run pip install -r apps/backend/requirements.txt") from error

    client = WalletAPIClient(
        base_url=_required_caw_api_url(),
        api_key=api_key or _required_caw_api_key(),
    )
    try:
        enter = getattr(client, "__aenter__", None)
        if enter is not None:
            yield await enter()
        else:
            yield client
    finally:
        exit_method = getattr(client, "__aexit__", None)
        if exit_method is not None:
            await exit_method(None, None, None)
        else:
            close = getattr(client, "close", None)
            if close is not None:
                await _maybe_await(close())


async def _safe_items_call(client: Any, method_name: str, *args: Any, **kwargs: Any) -> list[Any]:
    method = getattr(client, method_name, None)
    if method is None:
        return []
    try:
        response = await _maybe_await(method(*args, **kwargs))
    except TypeError:
        if "wallet_uuid" in kwargs:
            response = await _maybe_await(method(kwargs["wallet_uuid"]))
        else:
            response = await _maybe_await(method(*args))
    return _coerce_items(response)


async def _call_list_audit_logs(client: Any, wallet_id: str, result: str | None, limit: int) -> Any:
    kwargs: dict[str, Any] = {"wallet_id": wallet_id, "limit": limit}
    if result is not None:
        kwargs["result"] = result

    try:
        response = client.list_audit_logs(**kwargs)
    except TypeError:
        response = client.list_audit_logs(wallet_id=wallet_id, result=result)
    return await _maybe_await(response)


def _call_with_fallback(method: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args)
    except TypeError:
        return method(**kwargs)


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _required_caw_api_url() -> str:
    value = caw_api_url()
    if not value:
        raise RuntimeError(CAW_NOT_CONFIGURED_MESSAGE)
    return value


def _required_caw_api_key() -> str:
    value = caw_api_key()
    if not value:
        raise RuntimeError(CAW_NOT_CONFIGURED_MESSAGE)
    return value


def _required_caw_wallet_id() -> str:
    value = caw_wallet_id()
    if not value:
        raise RuntimeError(CAW_NOT_CONFIGURED_MESSAGE)
    return value


def _coerce_items(raw_value: Any) -> list[Any]:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return raw_value
    for key in ("items", "data", "logs", "audit_logs", "balances", "addresses"):
        value = _read_field(raw_value, key)
        if isinstance(value, list):
            return value
    return [raw_value]


def _simplify_wallet(wallet: Any) -> dict[str, Any]:
    return _pick_fields(wallet, ("uuid", "id", "name", "status", "created_at", "updated_at"))


def _simplify_address(address: Any) -> dict[str, Any]:
    return _pick_fields(address, ("chain_id", "address", "status"))


def _simplify_balance(balance: Any) -> dict[str, Any]:
    return _pick_fields(
        balance,
        (
            "chain_id",
            "chain_type",
            "token_id",
            "symbol",
            "amount",
            "total",
            "balance",
            "available",
            "pending",
            "locked",
            "address",
            "balance_updated_at",
        ),
    )


def _simplify_audit_log(log: Any) -> dict[str, Any]:
    simplified = _pick_fields(
        log,
        ("id", "action", "result", "created_at", "reason", "request_id", "wallet_id", "principal_id"),
    )
    for field in ("authz_details", "request", "error"):
        value = _read_field(log, field)
        if value is not None:
            simplified[field] = value
    return simplified


def _pick_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        field_value = _read_field(value, field)
        if field_value is not None:
            result[field] = field_value
    return _redact_sensitive(result)


def _read_field(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if model_dump is not None:
        return model_dump()
    as_dict = getattr(value, "dict", None)
    if as_dict is not None:
        return as_dict()
    return {key: getattr(value, key) for key in dir(value) if not key.startswith("_")}


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if "api_key" in key.lower() or "secret" in key.lower() or "token" == key.lower():
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _service_error(error: Exception) -> dict[str, Any]:
    return {"status": "error", "reason": str(error)}
