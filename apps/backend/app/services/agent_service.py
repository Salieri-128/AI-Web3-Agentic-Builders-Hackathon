from __future__ import annotations

import re
from typing import Any

from app.services.caw_service import (
    CAW_NOT_CONFIGURED_MESSAGE,
    build_transfer_pact_spec,
    get_audit_logs,
    get_wallet_status,
    is_caw_configured,
    submit_transfer_pact,
    transfer_tokens_with_pact,
)
from app.services.llm_service import compose_agent_reply, is_llm_configured, route_with_llm
from app.services.memory_service import load_profile, update_memory_from_message


CAW_KEYWORDS = ("wallet", "audit", "logs", "caw", "balance", "钱包", "日志", "余额", "状态")
MEMORY_KEYWORDS = ("记住", "偏好", "profile", "preference", "以后")
PACT_KEYWORDS = ("pact", "授权", "approval", "approve", "权限")
PROPOSAL_KEYWORDS = ("转账", "转", "transfer", "支付", "swap", "交易")
EXECUTE_KEYWORDS = ("execute", "执行", "send now", "提交交易")


async def handle_user_message(message: str) -> dict[str, Any]:
    profile = load_profile()
    normalized = message.lower()
    llm_result = await _safe_llm_route(message, profile)

    action = llm_result.get("action") or _infer_action(message, normalized)
    parameters = _merge_parameters(_build_transfer_parameters(message), llm_result.get("parameters", {}))

    caw_used = False
    memory_updated = False
    proposal: dict[str, Any] | None = None
    wallet: dict[str, Any] | None = None
    audit_logs: list[dict[str, Any]] = []
    tool_results: dict[str, Any] = {"action": action, "parameters": parameters}

    if _contains_keyword(message, normalized, MEMORY_KEYWORDS) or action == "memory_update":
        profile, updates = update_memory_from_message(message)
        memory_updated = True
        tool_results["memory"] = {"updated": memory_updated, "updates": updates, "profile": profile}

    if action == "wallet_status":
        caw_used = True
        wallet = await get_wallet_status()
        tool_results["wallet"] = wallet

    if action == "audit_logs":
        caw_used = True
        audit_logs = await get_audit_logs()
        tool_results["audit_logs"] = audit_logs

    if action in ("submit_pact", "transfer_proposal"):
        proposal = _build_transfer_proposal(parameters, action)
        if action == "submit_pact":
            caw_used = True
            pact = await submit_transfer_pact(
                intent=parameters["intent"],
                chain_id=parameters["chain_id"],
                token_id=parameters["token_id"],
                destination=parameters["destination"],
                amount=parameters["amount"],
                max_amount_usd=parameters.get("max_amount_usd"),
            )
            proposal["pact_submission"] = pact
            proposal["status"] = pact.get("status") or ("submitted" if pact.get("pact_id") else "submission_failed")
        tool_results["proposal"] = proposal

    if action == "execute_transfer":
        caw_used = True
        transfer = await transfer_tokens_with_pact(
            pact_id=parameters.get("pact_id", ""),
            chain_id=parameters["chain_id"],
            token_id=parameters["token_id"],
            destination=parameters["destination"],
            amount=parameters["amount"],
            request_id=parameters.get("request_id"),
            execute=_contains_keyword(message, normalized, EXECUTE_KEYWORDS),
        )
        proposal = _build_transfer_proposal(parameters, "execute_transfer")
        proposal["execution_result"] = transfer
        proposal["status"] = transfer.get("status", "unknown")
        tool_results["transfer"] = transfer
        tool_results["proposal"] = proposal

    if not caw_used and not memory_updated and proposal is None:
        tool_results["note"] = "No CAW tool was required for this request."

    reply = await _final_agent_reply(
        message=message,
        profile=profile,
        llm_result=llm_result,
        tool_results=tool_results,
        wallet=wallet,
        audit_logs=audit_logs,
        proposal=proposal,
        memory_updated=memory_updated,
    )

    return {
        "reply": reply,
        "llm_used": bool(llm_result.get("llm_used")),
        "caw_used": caw_used,
        "memory_updated": memory_updated,
        "proposal": proposal,
        "wallet": wallet,
        "audit_logs": audit_logs,
        "profile": profile,
    }


async def _final_agent_reply(
    *,
    message: str,
    profile: dict[str, Any],
    llm_result: dict[str, Any],
    tool_results: dict[str, Any],
    wallet: dict[str, Any] | None,
    audit_logs: list[dict[str, Any]],
    proposal: dict[str, Any] | None,
    memory_updated: bool,
) -> str:
    if llm_result.get("llm_used"):
        try:
            final_reply = await compose_agent_reply(
                message=message,
                profile=profile,
                route_result=llm_result,
                tool_results=tool_results,
            )
            if final_reply:
                return final_reply
        except Exception:
            pass

    if wallet is not None:
        return _wallet_status_summary(wallet)
    if audit_logs:
        return f"Retrieved {len(audit_logs)} audit log item(s)."
    if proposal is not None:
        return "I prepared a scoped Pact proposal. Owner approval is required before execution."
    if memory_updated:
        return "Memory updated."
    return llm_result.get("reply") or "I parsed your request."


async def _safe_llm_route(message: str, profile: dict[str, Any]) -> dict[str, Any]:
    if not is_llm_configured():
        return {"reply": "LLM is not configured; using local demo routing.", "llm_used": False}
    try:
        return await route_with_llm(message, profile)
    except Exception as error:
        return {
            "reply": f"LLM service failed, using local demo routing instead: {error}",
            "llm_used": False,
        }


def _infer_action(message: str, normalized: str) -> str:
    if _contains_keyword(message, normalized, PACT_KEYWORDS) and _contains_keyword(message, normalized, PROPOSAL_KEYWORDS):
        return "submit_pact"
    if _contains_keyword(message, normalized, EXECUTE_KEYWORDS):
        return "execute_transfer"
    if _contains_keyword(message, normalized, PROPOSAL_KEYWORDS):
        return "transfer_proposal"
    if "audit" in normalized or "logs" in normalized or "日志" in message:
        return "audit_logs"
    if _contains_keyword(message, normalized, CAW_KEYWORDS):
        return "wallet_status"
    return "none"


def _contains_keyword(message: str, normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in normalized or keyword in message for keyword in keywords)


def _merge_parameters(defaults: dict[str, Any], llm_parameters: Any) -> dict[str, Any]:
    if not isinstance(llm_parameters, dict):
        return defaults
    merged = defaults.copy()
    for key, value in llm_parameters.items():
        if value not in (None, ""):
            merged[key] = str(value)
    return merged


def _build_transfer_parameters(message: str) -> dict[str, Any]:
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*([A-Z_]*USDC|[A-Z_]*USDT|[A-Z_]*DAI|SETH)?", message, re.IGNORECASE)
    amount = amount_match.group(1) if amount_match else "1"
    token_id = amount_match.group(2).upper() if amount_match and amount_match.group(2) else "SETH_USDC"
    chain_id = _extract_value(message, ("chain", "chain_id", "链")) or _chain_from_token(token_id)
    destination = _extract_destination(message)

    return {
        "intent": f"Transfer {amount} {token_id} to {destination} on {chain_id}",
        "chain_id": chain_id,
        "token_id": token_id,
        "amount": amount,
        "destination": destination,
        "max_amount_usd": amount,
    }


def _build_transfer_proposal(parameters: dict[str, Any], action: str) -> dict[str, Any]:
    spec = build_transfer_pact_spec(
        chain_id=parameters["chain_id"],
        token_id=parameters["token_id"],
        destination=parameters["destination"],
        amount=parameters["amount"],
        max_amount_usd=parameters.get("max_amount_usd", parameters["amount"]),
    )
    return {
        "type": "transfer",
        "asset": parameters["token_id"],
        "amount": parameters["amount"],
        "destination": parameters["destination"],
        "chain_id": parameters["chain_id"],
        "status": "proposal_only" if action != "submit_pact" else "ready_to_submit",
        "execution_enabled": False,
        "reason": "Proposal only until CAW pact approval and explicit execution request.",
        "pact_spec": spec,
    }


def _caw_status_reply(success_text: str) -> str:
    if not is_caw_configured():
        return CAW_NOT_CONFIGURED_MESSAGE
    return success_text


def _wallet_status_summary(wallet_status: dict[str, Any] | None) -> str:
    if not wallet_status:
        return "Wallet status query returned no data."
    if wallet_status.get("status") == "error" or wallet_status.get("reason"):
        return f"Wallet status query failed: {wallet_status.get('reason', 'unknown error')}"

    wallet = wallet_status.get("wallet", {})
    balances = wallet_status.get("balances", [])
    addresses = wallet_status.get("addresses", [])
    wallet_name = wallet.get("name") or wallet.get("uuid") or "wallet"
    wallet_state = wallet.get("status", "unknown")

    balance_parts = []
    for balance in balances[:5]:
        token_id = balance.get("token_id") or balance.get("symbol") or "token"
        amount = balance.get("balance") or balance.get("available") or "0"
        chain_id = balance.get("chain_id") or "unknown chain"
        balance_parts.append(f"{token_id}: {amount} on {chain_id}")
    balance_text = "; ".join(balance_parts) if balance_parts else "no balances returned"

    return (
        f"Wallet {wallet_name} is {wallet_state}. "
        f"Balances: {balance_text}. "
        f"Addresses loaded: {len(addresses)}."
    )


def _chain_from_token(token_id: str) -> str:
    if "_" in token_id:
        return token_id.split("_", 1)[0]
    return "SETH"


def _extract_destination(message: str) -> str:
    address_match = re.search(r"0x[a-fA-F0-9]{40}", message)
    if address_match:
        return address_match.group(0)

    patterns = (
        r"(?:to|到)\s+(.+)$",
        r"(?:destination|address|地址)[:：]\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            destination = match.group(1).strip()
            return destination or "unknown_or_user_provided"
    return "unknown_or_user_provided"


def _extract_value(message: str, names: tuple[str, ...]) -> str | None:
    for name in names:
        match = re.search(rf"{name}\s*[:=：]\s*([A-Za-z0-9_]+)", message, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None
