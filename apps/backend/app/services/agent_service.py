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
from app.services.treasury_service import (
    approve_local_pact,
    get_treasury_state,
    initialize_wallet,
    run_daily_rebalance,
    send_asset,
    submit_internal_rebalance_pact,
)
from app.services.aave_service import execute_aave_faucet_claim, execute_aave_supply, execute_aave_withdraw, get_aave_wallet_state


CAW_KEYWORDS = ("wallet", "audit", "logs", "caw", "balance", "钱包", "日志", "余额", "状态")
MEMORY_KEYWORDS = ("记住", "偏好", "profile", "preference", "以后")
PACT_KEYWORDS = ("pact", "授权", "approval", "approve", "权限")
PROPOSAL_KEYWORDS = ("转账", "转", "transfer", "支付", "swap", "交易")
EXECUTE_KEYWORDS = ("execute", "执行", "send now", "提交交易")
TREASURY_STATUS_KEYWORDS = ("策略状态", "treasury", "资金状态", "稳定币状态")
REBALANCE_KEYWORDS = ("rebalance", "再平衡", "调仓", "每日计算", "每天计算")
INITIALIZE_KEYWORDS = ("初始化", "存入", "deposit")
APPROVE_KEYWORDS = ("approve pact", "批准 pact", "审批 pact", "通过 pact")
AAVE_KEYWORDS = ("aave", "Aave", "生息", "supply", "withdraw", "faucet", "领取")


async def handle_user_message(message: str) -> dict[str, Any]:
    profile = load_profile()
    normalized = message.lower()
    inferred_action = _infer_action(message, normalized)
    llm_result = (
        {"reply": "Using local deterministic routing for wallet safety flow.", "llm_used": False}
        if inferred_action != "none"
        else await _safe_llm_route(message, profile)
    )

    action = inferred_action if inferred_action != "none" else llm_result.get("action", "none")
    parameters = _merge_parameters(_build_transfer_parameters(message), llm_result.get("parameters", {}))

    caw_used = False
    memory_updated = False
    proposal: dict[str, Any] | None = None
    wallet: dict[str, Any] | None = None
    audit_logs: list[dict[str, Any]] = []
    tool_results: dict[str, Any] = {"action": action, "parameters": parameters}

    if action == "treasury_status":
        wallet = {"treasury": await get_treasury_state()}
        tool_results["treasury"] = wallet["treasury"]

    if action == "treasury_initialize":
        wallet = {"treasury": await initialize_wallet(parameters["amount"])}
        tool_results["treasury"] = wallet["treasury"]

    if action == "treasury_rebalance":
        wallet = {"treasury": await run_daily_rebalance()}
        tool_results["treasury"] = wallet["treasury"]

    if action == "approve_local_pact":
        pact_id = _extract_pact_id(message)
        result = await approve_local_pact(pact_id)
        proposal = result.get("pact") if isinstance(result, dict) else None
        tool_results["local_pact_approval"] = result

    if action == "treasury_transfer":
        result = await send_asset(
            destination=parameters["destination"],
            amount=parameters["amount"],
            pact_id=parameters.get("pact_id"),
            execute=_contains_keyword(message, normalized, EXECUTE_KEYWORDS),
        )
        wallet = {"treasury": result.get("treasury") or await get_treasury_state()}
        proposal = result.get("proposal") or result.get("pact")
        tool_results["treasury_transfer"] = result

    if action == "aave_status":
        wallet = {"treasury": await get_treasury_state(), "aave": await get_aave_wallet_state()}
        tool_results["aave"] = wallet["aave"]

    if action == "aave_submit_pact":
        proposal = await submit_internal_rebalance_pact(parameters["amount"])
        wallet = {"treasury": await get_treasury_state()}
        tool_results["aave_pact"] = proposal

    if action == "aave_faucet":
        result = await execute_aave_faucet_claim(pact_id=parameters.get("pact_id", ""), amount=parameters["amount"])
        wallet = {"treasury": await get_treasury_state(), "aave": result.get("aave")}
        proposal = result
        tool_results["aave_faucet"] = result

    if action == "aave_supply":
        result = await execute_aave_supply(pact_id=parameters.get("pact_id", ""), amount=parameters["amount"])
        wallet = {"treasury": await get_treasury_state(), "aave": result.get("aave")}
        proposal = result
        tool_results["aave_supply"] = result

    if action == "aave_withdraw":
        result = await execute_aave_withdraw(pact_id=parameters.get("pact_id", ""), amount=parameters["amount"])
        wallet = {"treasury": await get_treasury_state(), "aave": result.get("aave")}
        proposal = result
        tool_results["aave_withdraw"] = result

    if _contains_keyword(message, normalized, MEMORY_KEYWORDS) or action == "memory_update":
        profile, updates = update_memory_from_message(message)
        memory_updated = True
        tool_results["memory"] = {"updated": memory_updated, "updates": updates, "profile": profile}

    if action == "wallet_status":
        caw_used = True
        caw_wallet = await get_wallet_status()
        treasury_state = await get_treasury_state()
        aave_state = await get_aave_wallet_state()
        wallet = {"wallet": caw_wallet, "treasury": treasury_state, "aave": aave_state}
        tool_results["wallet"] = caw_wallet
        tool_results["treasury"] = treasury_state
        tool_results["aave"] = aave_state
        tool_results["balance_summary"] = _build_balance_summary(caw_wallet, treasury_state, aave_state)

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

    reply, final_llm_used = await _final_agent_reply(
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
        "llm_used": final_llm_used,
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
) -> tuple[str, bool]:
    try:
        final_reply = await compose_agent_reply(
            message=message,
            profile=profile,
            route_result=llm_result,
            tool_results=tool_results,
        )
        if final_reply:
            return final_reply, True
    except Exception:
        pass

    if wallet is not None and "treasury" in wallet:
        return _treasury_summary(wallet["treasury"]), False
    if wallet is not None:
        return _wallet_status_summary(wallet), False
    if audit_logs:
        return f"Retrieved {len(audit_logs)} audit log item(s).", False
    if proposal is not None:
        return "I prepared a scoped Pact proposal. Owner approval is required before execution.", False
    if memory_updated:
        return "Memory updated.", False
    return llm_result.get("reply") or "I parsed your request.", bool(llm_result.get("llm_used"))


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
    if ("钱包" in message and any(keyword in message for keyword in ("钱", "余额", "资产", "多少"))) or (
        "wallet" in normalized and any(keyword in normalized for keyword in ("balance", "money", "asset"))
    ):
        return "wallet_status"
    if "aave" in normalized or "生息" in message:
        if "pact" in normalized or "授权" in message:
            return "aave_submit_pact"
        return "aave_status"
    if "领取" in message or "faucet" in normalized:
        return "aave_faucet"
    if "supply" in normalized or "存入 aave" in normalized or "存入Aave" in message:
        return "aave_supply"
    if "withdraw" in normalized or "取出" in message:
        return "aave_withdraw"
    if _contains_keyword(message, normalized, APPROVE_KEYWORDS):
        return "approve_local_pact"
    if _contains_keyword(message, normalized, REBALANCE_KEYWORDS):
        return "treasury_rebalance"
    if _contains_keyword(message, normalized, INITIALIZE_KEYWORDS) and _contains_stable_amount(message):
        return "treasury_initialize"
    if _contains_keyword(message, normalized, TREASURY_STATUS_KEYWORDS):
        return "treasury_status"
    if _contains_keyword(message, normalized, PROPOSAL_KEYWORDS) and _extract_destination(message) != "unknown_or_user_provided":
        return "treasury_transfer"
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
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*([A-Z_]*USDC|[A-Z_]*USDT|[A-Z_]*DAI|U|SETH)?", message, re.IGNORECASE)
    amount = amount_match.group(1) if amount_match else "1"
    raw_token = amount_match.group(2).upper() if amount_match and amount_match.group(2) else "SETH_USDC"
    token_id = "SETH_USDC" if raw_token == "U" else raw_token
    chain_id = _extract_value(message, ("chain", "chain_id", "链")) or _chain_from_token(token_id)
    destination = _extract_destination(message)

    return {
        "intent": f"Transfer {amount} {token_id} to {destination} on {chain_id}",
        "chain_id": chain_id,
        "token_id": token_id,
        "amount": amount,
        "destination": destination,
        "max_amount_usd": amount,
        "pact_id": _extract_pact_id(message),
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
    if "treasury" in wallet_status or "aave" in wallet_status:
        return _merged_wallet_summary(wallet_status)
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


def _build_balance_summary(
    caw_wallet: dict[str, Any], treasury: dict[str, Any], aave: dict[str, Any]
) -> dict[str, Any]:
    native_balances = []
    for balance in caw_wallet.get("balances", []):
        token_id = balance.get("token_id") or balance.get("symbol") or "token"
        chain_id = balance.get("chain_id") or "unknown"
        amount = balance.get("balance") or balance.get("available") or balance.get("amount") or balance.get("total") or "0"
        native_balances.append({"chain_id": chain_id, "token": token_id, "amount": str(amount)})
    return {
        "wallet_address": aave.get("wallet_address"),
        "native_balances": native_balances,
        "sepolia_usdc": aave.get("wallet_balance", "0"),
        "aave_ausdc": aave.get("aave_balance", "0"),
        "pool_allowance": aave.get("pool_allowance", "0"),
        "recommended_liquidity": treasury.get("recommendation", {}).get("recommended_liquidity"),
    }


def _merged_wallet_summary(wallet_status: dict[str, Any]) -> str:
    caw_wallet = wallet_status.get("wallet", {})
    treasury = wallet_status.get("treasury", {})
    aave = wallet_status.get("aave", {})
    balance_summary = _build_balance_summary(caw_wallet, treasury, aave)
    native_parts = [
        f"{item['token']}: {item['amount']} on {item['chain_id']}"
        for item in balance_summary["native_balances"]
    ]
    native_text = "; ".join(native_parts) if native_parts else "no native balances returned"
    return (
        f"Wallet address: {balance_summary.get('wallet_address') or 'unknown'}. "
        f"Native balances: {native_text}. "
        f"Sepolia USDC: {balance_summary['sepolia_usdc']}. "
        f"Aave aUSDC: {balance_summary['aave_ausdc']}. "
        f"Recommended liquidity: {balance_summary.get('recommended_liquidity') or 'n/a'} USDC."
    )


def _treasury_summary(treasury: dict[str, Any]) -> str:
    if "treasury" in treasury:
        treasury = treasury["treasury"]
    balances = treasury.get("balances", {})
    recommendation = treasury.get("recommendation", {})
    decision = treasury.get("decision")
    pacts = treasury.get("pacts", [])
    active_pacts = [pact for pact in pacts if pact.get("status") == "active"]
    parts = [
        f"Mode: {treasury.get('mode', 'local')}.",
        f"Wallet liquidity: {balances.get('wallet', '0')} {treasury.get('asset', 'asset')}.",
        f"Yield position: {balances.get('yield', balances.get('aave', '0'))} {treasury.get('asset', 'asset')}.",
        f"Recommended liquidity: {recommendation.get('recommended_liquidity', 'n/a')} {treasury.get('asset', 'asset')}.",
        f"Active local pacts: {len(active_pacts)}.",
    ]
    if decision:
        parts.append(f"Decision: {decision.get('action')} ({decision.get('reason')})")
    return " ".join(parts)


def _contains_stable_amount(message: str) -> bool:
    return re.search(r"\d+(?:\.\d+)?\s*(?:U|USDC|USDT|DAI)", message, re.IGNORECASE) is not None


def _extract_pact_id(message: str) -> str:
    match = re.search(r"pact-[a-z0-9_-]+", message, re.IGNORECASE)
    return match.group(0) if match else ""


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
