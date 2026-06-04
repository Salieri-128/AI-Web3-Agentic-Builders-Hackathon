from __future__ import annotations

import re
from typing import Any

from app.services.caw_service import CAW_NOT_CONFIGURED_MESSAGE, get_audit_logs, is_caw_configured
from app.services.memory_service import load_profile, update_memory_from_message


CAW_KEYWORDS = ("wallet", "audit", "logs", "caw", "钱包", "日志")
MEMORY_KEYWORDS = ("记住", "偏好", "profile", "preference", "以后")
PROPOSAL_KEYWORDS = ("转账", "转", "transfer", "支付", "swap", "交易")


async def handle_user_message(message: str) -> dict[str, Any]:
    profile = load_profile()
    normalized = message.lower()
    reply_parts = [
        "I am a policy-controlled treasury agent. I can reason about treasury actions, memory, proposals, and CAW read-only status in this stage."
    ]

    caw_used = False
    memory_updated = False
    proposal: dict[str, Any] | None = None
    audit_logs: list[dict[str, Any]] = []

    if _contains_keyword(message, normalized, CAW_KEYWORDS):
        caw_used = True
        try:
            audit_logs = await get_audit_logs()
        except Exception as error:
            audit_logs = [{"reason": f"CAW read-only audit log query failed: {error}"}]
        if is_caw_configured() and not _has_caw_error(audit_logs):
            reply_parts.append(f"CAW audit log query completed. Retrieved {len(audit_logs)} audit log item(s).")
        elif not is_caw_configured():
            reply_parts.append(CAW_NOT_CONFIGURED_MESSAGE)
        else:
            reply_parts.append("CAW read-only audit log query failed. No funds operation was executed.")

    if _contains_keyword(message, normalized, MEMORY_KEYWORDS):
        profile, updates = update_memory_from_message(message)
        memory_updated = True
        if updates:
            reply_parts.append("Memory updated: " + ", ".join(updates) + ".")
        else:
            reply_parts.append("Memory checked. No rule-based preference change was detected.")

    if _contains_keyword(message, normalized, PROPOSAL_KEYWORDS):
        proposal = _build_transfer_proposal(message)
        reply_parts.append(
            "This looks like a funds operation. Stage 1 only generates a proposal; no real transfer, swap, or contract call is executed."
        )

    if not caw_used and not memory_updated and proposal is None:
        reply_parts.append(
            "Tell me a wallet/audit-log request, a memory preference, or a transfer-style goal and I will route it through the demo loop."
        )

    return {
        "reply": " ".join(reply_parts),
        "caw_used": caw_used,
        "memory_updated": memory_updated,
        "proposal": proposal,
        "audit_logs": audit_logs,
        "profile": profile,
    }


def _contains_keyword(message: str, normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in normalized or keyword in message for keyword in keywords)


def _build_transfer_proposal(message: str) -> dict[str, Any]:
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*(USDC|USDT|DAI|USD)?", message, re.IGNORECASE)
    asset = amount_match.group(2).upper() if amount_match and amount_match.group(2) else "USDC"
    amount = amount_match.group(1) if amount_match else "1"
    destination = _extract_destination(message)

    return {
        "type": "transfer",
        "asset": asset,
        "amount": amount,
        "destination": destination,
        "status": "proposal_only",
        "execution_enabled": False,
        "reason": "Current stage only supports proposal generation. No real transfer is executed.",
    }


def _has_caw_error(audit_logs: list[dict[str, Any]]) -> bool:
    return any(str(log.get("reason", "")).startswith("CAW read-only audit log query failed") for log in audit_logs)


def _extract_destination(message: str) -> str:
    patterns = (
        r"(?:to|到)\s+(.+)$",
        r"(?:destination|address)[:：]\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            destination = match.group(1).strip()
            return destination or "unknown_or_user_provided"
    return "unknown_or_user_provided"
