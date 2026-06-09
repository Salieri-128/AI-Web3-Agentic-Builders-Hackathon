from __future__ import annotations

import asyncio
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
from app.services.llm_service import compose_agent_reply, decide_transfer_flow, is_llm_configured, route_with_llm
from app.services.memory_service import load_profile, update_memory_from_message
from app.services.treasury_service import (
    approve_local_pact,
    create_external_transfer_pact,
    get_treasury_state,
    initialize_wallet,
    run_daily_rebalance,
    send_asset,
    submit_internal_rebalance_pact,
)
from app.services.aave_service import execute_aave_supply, execute_aave_withdraw, get_aave_wallet_state


CAW_KEYWORDS = ("wallet", "audit", "logs", "caw", "balance", "钱包", "日志", "余额", "状态")
MEMORY_KEYWORDS = ("记住", "偏好", "profile", "preference", "以后")
PACT_KEYWORDS = ("pact", "授权", "approval", "approve", "权限")
PROPOSAL_KEYWORDS = ("转账", "转", "transfer", "支付", "swap", "交易")
EXECUTE_KEYWORDS = ("execute", "执行", "send now", "提交交易")
TREASURY_STATUS_KEYWORDS = ("策略状态", "treasury", "资金状态", "稳定币状态")
REBALANCE_KEYWORDS = ("rebalance", "再平衡", "调仓", "每日计算", "每天计算")
INITIALIZE_KEYWORDS = ("初始化", "存入", "deposit")
APPROVE_KEYWORDS = ("approve pact", "批准 pact", "审批 pact", "通过 pact")
AAVE_KEYWORDS = ("aave", "Aave", "生息", "supply", "withdraw")


async def handle_user_message(message: str) -> dict[str, Any]:
    profile = load_profile()
    normalized = message.lower()
    inferred_action = _infer_action(message, normalized)
    llm_result = (
        {"reply": "Using local deterministic routing for wallet safety flow.", "llm_used": False}
        if inferred_action != "none"
        else await _safe_llm_route(message, profile)
    )

    deterministic_transfer_parameters = _build_transfer_parameters(message)
    action = _normalize_action(
        inferred_action if inferred_action != "none" else str(llm_result.get("action", "none")),
        deterministic_transfer_parameters,
    )
    parameters = (
        deterministic_transfer_parameters
        if action == "treasury_transfer"
        else _merge_parameters(deterministic_transfer_parameters, llm_result.get("parameters", {}))
    )

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
        caw_used = True
        result = await _run_llm_guided_transfer(message=message, profile=profile, parameters=parameters)
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
                max_amount=parameters.get("max_amount", parameters["amount"]),
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
        "llm_used": bool(llm_result.get("llm_used") or final_llm_used or _tool_results_used_llm(tool_results)),
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
    transfer_result = tool_results.get("treasury_transfer")
    if isinstance(transfer_result, dict):
        return _transfer_result_summary(transfer_result), False

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


def _normalize_action(action: str, transfer_parameters: dict[str, Any]) -> str:
    if action in {"submit_pact", "transfer_proposal", "execute_transfer"}:
        if transfer_parameters.get("destination") != "unknown_or_user_provided":
            return "treasury_transfer"
    return action


def _merge_parameters(defaults: dict[str, Any], llm_parameters: Any) -> dict[str, Any]:
    if not isinstance(llm_parameters, dict):
        return defaults
    merged = defaults.copy()
    for key, value in llm_parameters.items():
        if value not in (None, ""):
            merged[key] = str(value)
    return merged


def _build_transfer_parameters(message: str) -> dict[str, Any]:
    amount, token_id = _extract_transfer_amount_and_token(message)
    chain_id = _extract_value(message, ("chain", "chain_id", "链")) or _chain_from_token(token_id)
    destination = _extract_destination(message)

    return {
        "intent": f"Transfer {amount} {token_id} to {destination} on {chain_id}",
        "chain_id": chain_id,
        "token_id": token_id,
        "amount": amount,
        "destination": destination,
        "max_amount": amount,
        "pact_id": _extract_pact_id(message),
    }


async def _run_llm_guided_transfer(*, message: str, profile: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    treasury_state = await get_treasury_state()
    balance_decision = await _safe_transfer_decision(
        message=message,
        profile=profile,
        parameters=parameters,
        stage="balance_checked",
        tool_state={"balances": treasury_state.get("balances", {}), "asset": treasury_state.get("asset")},
    )
    decisions.append(balance_decision)
    if balance_decision.get("decision") == "insufficient_balance":
        return {
            "status": "insufficient_wallet_balance",
            "reason": balance_decision.get("reason") or "Wallet balance is lower than the requested transfer amount.",
            "treasury": treasury_state,
            "llm_transfer_decisions": decisions,
        }

    pact_decision = await _safe_transfer_decision(
        message=message,
        profile=profile,
        parameters=parameters,
        stage="pacts_checked",
        tool_state={
            "balances": treasury_state.get("balances", {}),
            "pacts": _summarize_transfer_pacts(treasury_state.get("pacts", [])),
        },
    )
    decisions.append(pact_decision)
    if pact_decision.get("decision") in {"use_existing_pact", "execute_with_pact"} and pact_decision.get("pact_id"):
        execution = await send_asset(
            destination=parameters["destination"],
            amount=parameters["amount"],
            pact_id=str(pact_decision["pact_id"]),
            execute=True,
        )
        execution["llm_transfer_decisions"] = decisions
        return execution

    proposal = await create_external_transfer_pact(parameters["destination"], parameters["amount"])
    if not proposal.get("caw_pact_id"):
        return {
            "status": proposal.get("status", "pact_submission_failed"),
            "reason": proposal.get("reason", "CAW did not return a Pact ID."),
            "proposal": proposal,
            "treasury": await get_treasury_state(),
            "llm_transfer_decisions": decisions,
        }

    submitted_decision = await _safe_transfer_decision(
        message=message,
        profile=profile,
        parameters=parameters,
        stage="pact_submitted",
        tool_state={"proposal": proposal},
    )
    decisions.append(submitted_decision)
    return {
        "status": "pact_required",
        "reason": "Submitted a real CAW transfer Pact. Approve it in Cobo/CAW before execution.",
        "proposal": proposal,
        "treasury": await get_treasury_state(),
        "llm_transfer_decisions": decisions,
    }


async def _safe_transfer_decision(
    *,
    message: str,
    profile: dict[str, Any],
    parameters: dict[str, Any],
    stage: str,
    tool_state: dict[str, Any],
) -> dict[str, Any]:
    try:
        decision = await decide_transfer_flow(
            message=message,
            profile=profile,
            transfer_request=_llm_transfer_request(parameters),
            stage=stage,
            tool_state=tool_state,
        )
        if decision.get("decision") != "fallback":
            return decision
    except Exception as error:
        return {
            "decision": _fallback_transfer_decision(stage, parameters, tool_state),
            "pact_id": _fallback_transfer_pact_id(tool_state, parameters),
            "reason": str(error),
            "llm_used": False,
        }
    return {
        "decision": _fallback_transfer_decision(stage, parameters, tool_state),
        "pact_id": _fallback_transfer_pact_id(tool_state, parameters),
        "reason": "Backend fallback decision.",
        "llm_used": False,
    }


def _fallback_transfer_decision(stage: str, parameters: dict[str, Any], tool_state: dict[str, Any]) -> str:
    if stage == "balance_checked":
        wallet_balance = _safe_number(tool_state.get("balances", {}).get("wallet"))
        amount = _safe_number(parameters.get("amount"))
        return "insufficient_balance" if wallet_balance < amount else "use_existing_pact"
    if stage == "pacts_checked":
        return "use_existing_pact" if _fallback_transfer_pact_id(tool_state, parameters) else "submit_new_pact"
    if stage == "pact_submitted":
        return "wait_for_pact_approval"
    if stage == "pact_approved":
        return "execute_with_pact"
    return "transfer_failed"


def _llm_transfer_request(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "chain_id": parameters.get("chain_id"),
        "token_id": parameters.get("token_id"),
        "amount": parameters.get("amount"),
        "max_amount": parameters.get("max_amount", parameters.get("amount")),
        "destination": parameters.get("destination"),
    }


def _fallback_transfer_pact_id(tool_state: dict[str, Any], parameters: dict[str, Any]) -> str:
    requested_amount = _safe_number(parameters.get("amount"))
    for pact in tool_state.get("pacts", []):
        if (
            pact.get("status") == "active"
            and pact.get("caw_pact_id")
            and not pact.get("legacy_usd_cap")
            and str(pact.get("destination_address", "")).lower() == str(parameters.get("destination", "")).lower()
            and str(pact.get("chain_id", "")) == str(parameters.get("chain_id", ""))
            and _safe_number(pact.get("max_single_amount")) >= requested_amount
        ):
            return str(pact["caw_pact_id"])
    return ""


def _summarize_transfer_pacts(pacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized = []
    for pact in pacts:
        if pact.get("pact_type") != "external_transfer":
            continue
        scope = pact.get("scope", {})
        serialized = str(pact)
        summarized.append(
            {
                "pact_id": pact.get("pact_id"),
                "caw_pact_id": pact.get("caw_pact_id"),
                "status": pact.get("status"),
                "destination_address": scope.get("destination_address"),
                "asset": scope.get("asset"),
                "chain_id": scope.get("chain_id"),
                "max_single_amount": scope.get("max_single_amount"),
                "weekly_amount_cap": scope.get("weekly_amount_cap"),
                "weekly_tx_cap": scope.get("weekly_tx_cap"),
                "legacy_usd_cap": "amount_usd_gt" in serialized or "SETH_WBTC" in serialized,
                "duration": pact.get("duration"),
            }
        )
    return summarized


async def _wait_for_transfer_pact_active(pact_id: str) -> dict[str, Any]:
    for _ in range(120):
        result = await approve_local_pact(pact_id)
        pact = result.get("pact") if isinstance(result, dict) else {}
        status = str(result.get("status") or pact.get("status") or "")
        if status == "active":
            return {
                "status": "active",
                "pact": pact,
                "caw_pact_id": pact.get("caw_pact_id") or pact_id,
                "message": "Pact approved by owner.",
            }
        if status in {"revoked", "rejected", "declined", "caw_submission_failed", "error"}:
            return {"status": status, "pact": pact, "message": f"Pact approval stopped with status {status}."}
        await asyncio.sleep(3)
    return {
        "status": "pending_owner_approval",
        "pact_id": pact_id,
        "message": "Pact is still waiting for owner approval in CAW App.",
    }


def _extract_transfer_amount_and_token(message: str) -> tuple[str, str]:
    token_pattern = r"(SETH_WBTC|SETH_USDC|SETH_USDT|SETH_DAI|WBTC|USDC|USDT|DAI|BTC|U)"
    token_amount_match = re.search(rf"(\d+(?:\.\d+)?)\s*{token_pattern}\b", message, re.IGNORECASE)
    if token_amount_match:
        return token_amount_match.group(1), _normalize_token_id(token_amount_match.group(2))

    amount_after_verb = re.search(r"(?:转|transfer|send|支付)\s*(\d+(?:\.\d+)?)", message, re.IGNORECASE)
    if amount_after_verb:
        return amount_after_verb.group(1), "WBTC"

    return "1", "WBTC"


def _normalize_token_id(raw_token: str) -> str:
    token = raw_token.upper()
    if token in {"BTC", "WBTC", "SETH_WBTC"}:
        return "WBTC"
    if token in {"U", "USDC", "SETH_USDC"}:
        return "USDC"
    if token in {"USDT", "SETH_USDT"}:
        return "USDT"
    if token in {"DAI", "SETH_DAI"}:
        return "DAI"
    return token


def _build_transfer_proposal(parameters: dict[str, Any], action: str) -> dict[str, Any]:
    spec = build_transfer_pact_spec(
        chain_id=parameters["chain_id"],
        token_id=parameters["token_id"],
        destination=parameters["destination"],
        amount=parameters["amount"],
        max_amount=parameters.get("max_amount", parameters["amount"]),
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


def _transfer_result_summary(result: dict[str, Any]) -> str:
    status = str(result.get("status", "unknown"))
    proposal = result.get("proposal") or {}
    approval_wait = result.get("approval_wait") or {}
    if approval_wait.get("status") == "pending_owner_approval":
        return "新的 CAW Pact 已提交，但仍在等待 owner 审批。请在 Cobo/CAW App 中 approve，Agent 检测到 active 后会继续执行转账。"
    if approval_wait.get("status") and approval_wait.get("status") != "active":
        if approval_wait.get("status") == "revoked":
            return "这个 CAW Pact 已被撤销，本次转账未执行。再次发起转账时，Agent 会重新检查余额和可用 Pact，并在需要时提交新的 Pact。"
        return str(approval_wait.get("message") or f"Pact 审批状态为 {approval_wait.get('status')}，转账尚未执行。")
    if status == "pact_required":
        return (
            "已为这笔转账提交新的 CAW Pact。请在 Cobo/CAW App 中 approve，"
            "Agent 会在检测到授权生效后继续执行转账。"
        )
    if status in {"ok", "success", "submitted"} or result.get("transaction_id") or result.get("uuid"):
        gas_text = _extract_gas_fee_text(result)
        if result.get("auto_executed_after_approval"):
            return f"Pact 已审批通过，Agent 已继续执行转账，结果已写入审计日志。Gas fee：{gas_text}。"
        return f"转账已按可用 CAW Pact 执行，结果已写入审计日志。Gas fee：{gas_text}。"
    reason = _extract_result_reason(result)
    if reason:
        return reason
    if proposal:
        return "已处理转账请求，并生成了对应的 Pact/执行结果。"
    return f"转账流程状态：{status}"


def _extract_result_reason(result: dict[str, Any]) -> str:
    for candidate in (
        result.get("reason"),
        result.get("message"),
        result.get("execution", {}).get("reason") if isinstance(result.get("execution"), dict) else None,
        result.get("execution", {}).get("message") if isinstance(result.get("execution"), dict) else None,
    ):
        if candidate:
            return str(candidate)
    return ""


def _extract_gas_fee_text(result: dict[str, Any]) -> str:
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    transfer = execution.get("transfer") if isinstance(execution.get("transfer"), dict) else {}
    transaction = execution.get("transaction") if isinstance(execution.get("transaction"), dict) else {}
    transaction_fee = _first_fee_dict(transaction)
    candidates = (
        result.get("gas_fee"),
        result.get("fee"),
        result.get("gas_cost"),
        execution.get("gas_fee"),
        execution.get("fee"),
        execution.get("gas_cost"),
        transfer.get("gas_fee"),
        transfer.get("fee"),
        transfer.get("gas_cost"),
        transfer.get("transaction_fee"),
        transfer.get("fee_amount"),
        transaction_fee.get("fee_used"),
        transaction_fee.get("estimated_fee_used"),
    )
    for candidate in candidates:
        if candidate not in (None, ""):
            token_id = transaction_fee.get("token_id")
            if candidate in (transaction_fee.get("fee_used"), transaction_fee.get("estimated_fee_used")) and token_id:
                return f"{candidate} {token_id}"
            return str(candidate)
    transfer_status = transfer.get("status_display") or transfer.get("status")
    if transfer_status:
        return f"CAW 返回结果中未提供（交易状态：{transfer_status}）"
    transaction_status = transaction.get("status")
    if transaction_status:
        return f"CAW 交易详情暂未返回 fee（交易状态：{transaction_status}）"
    return "CAW 返回结果中未提供"


def _first_fee_dict(transaction: dict[str, Any]) -> dict[str, Any]:
    for path in (("fee",), ("data", "fee"), ("prepared_tx", "fee")):
        current: Any = transaction
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, dict):
            return current
    for ext_transaction in transaction.get("ext_transactions", []):
        if not isinstance(ext_transaction, dict):
            continue
        data = ext_transaction.get("data")
        if isinstance(data, dict) and isinstance(data.get("fee"), dict):
            return data["fee"]
    return {}


def _tool_results_used_llm(tool_results: dict[str, Any]) -> bool:
    transfer_result = tool_results.get("treasury_transfer")
    if not isinstance(transfer_result, dict):
        return False
    return any(decision.get("llm_used") for decision in transfer_result.get("llm_transfer_decisions", []))


def _safe_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
        "aave_asset": aave.get("asset", treasury.get("asset", "asset")),
        "aave_yield_asset": aave.get("a_token_asset", f"a{aave.get('asset', treasury.get('asset', 'asset'))}"),
        "wallet_strategy_balance": aave.get("wallet_balance", "0"),
        "aave_strategy_balance": aave.get("aave_balance", "0"),
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
        f"Sepolia {balance_summary['aave_asset']}: {balance_summary['wallet_strategy_balance']}. "
        f"Aave {balance_summary['aave_yield_asset']}: {balance_summary['aave_strategy_balance']}. "
        f"Recommended liquidity: {balance_summary.get('recommended_liquidity') or 'n/a'} {balance_summary['aave_asset']}."
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
    return re.search(r"\d+(?:\.\d+)?\s*(?:BTC|WBTC|U|USDC|USDT|DAI)", message, re.IGNORECASE) is not None


def _extract_pact_id(message: str) -> str:
    match = re.search(r"pact-[a-z0-9_-]+", message, re.IGNORECASE)
    return match.group(0) if match else ""


def _chain_from_token(token_id: str) -> str:
    if token_id.startswith("SETH_"):
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
