from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.services.caw_service import (
    CAW_NOT_CONFIGURED_MESSAGE,
    get_pact,
    is_caw_configured,
)
from app.services.aave_service import (
    WBTC,
    execute_aave_supply,
    execute_aave_withdraw,
    execute_wbtc_transfer,
    get_aave_wallet_state,
    submit_aave_rebalance_pact,
    submit_wbtc_transfer_pact,
)


ROOT_DIR = Path(__file__).resolve().parents[4]
TREASURY_DIR = ROOT_DIR / "data" / "users" / "demo"
TREASURY_STATE_PATH = TREASURY_DIR / "wallet_state.json"
TREASURY_EVENTS_PATH = TREASURY_DIR / "events.jsonl"

ASSET = "WBTC"
TOKEN_ID = "WBTC"
CHAIN_ID = "SETH"
PROTOCOL = "Aave"


DEFAULT_STRATEGY: dict[str, Any] = {
    "base_buffer": "0.05",
    "default_liquidity_ratio": "0.20",
    "default_yield_ratio": "0.80",
    "min_liquidity_ratio": "0.10",
    "risk_multiplier": "1.20",
    "single_tx_multiplier": "1.50",
    "gas_safety_multiplier": "1.20",
    "min_rebalance_amount": "0.001",
    "aave_apy": "0.02",
    "gas_fee_asset": "0.0001",
    "rebalance_horizon_days": 7,
}

DEFAULT_STATE: dict[str, Any] = {
    "wallet_id": "caw-sepolia-wallet",
    "asset": ASSET,
    "chain_id": CHAIN_ID,
    "strategy": DEFAULT_STRATEGY,
    "pacts": [],
    "last_rebalance_at": None,
    "updated_at": None,
}


async def initialize_wallet(deposit_amount: str | None = None) -> dict[str, Any]:
    state = _load_state()
    state["asset"] = ASSET
    state["chain_id"] = CHAIN_ID
    state["strategy"] = {**DEFAULT_STRATEGY, **state.get("strategy", {})}
    state["updated_at"] = _now_iso()
    _save_state(state)
    _reset_events()
    _append_event({"type": "wallet_initialized", "mode": "caw_aave_sepolia_real", "asset": ASSET})
    return await get_treasury_state()


async def get_treasury_state() -> dict[str, Any]:
    state = _load_state()
    state = await refresh_external_pact_statuses(state)
    aave_state = await get_aave_wallet_state()
    balances = _extract_real_balances(aave_state)
    stats = get_transfer_stats()
    recommendation = calculate_recommendation(state, stats, balances)
    return {
        "mode": "caw_aave_sepolia_real",
        "wallet_id": state["wallet_id"],
        "asset": state["asset"],
        "chain_id": state["chain_id"],
        "balances": balances,
        "strategy": state["strategy"],
        "transfer_stats_7d": stats,
        "recommendation": recommendation,
        "pacts": state.get("pacts", []),
        "aave": aave_state,
        "last_rebalance_at": state.get("last_rebalance_at"),
        "updated_at": state.get("updated_at"),
    }


async def run_daily_rebalance() -> dict[str, Any]:
    state = _load_state()
    aave_state = await get_aave_wallet_state()
    balances = _extract_real_balances(aave_state)
    stats = get_transfer_stats()
    recommendation = calculate_recommendation(state, stats, balances)
    wallet_balance = _asset_amount(balances["wallet"])
    target = _asset_amount(recommendation["recommended_liquidity"])
    min_rebalance = _asset_amount(state["strategy"]["min_rebalance_amount"])

    decision = {
        "action": "hold",
        "amount": "0",
        "reason": "Wallet liquidity is within the recommended range.",
        "pact_required": "internal_agent_rebalance",
    }

    if wallet_balance > target:
        excess = wallet_balance - target
        if excess >= min_rebalance and _is_supply_gas_worthwhile(excess, state["strategy"]):
            pact_id = _find_known_internal_caw_pact_id(state)
            if pact_id:
                execution = await execute_aave_supply(pact_id=pact_id, amount=_fmt(excess))
                if _execution_succeeded(execution):
                    decision = {
                        "action": "supply_to_aave",
                        "amount": _fmt(excess),
                        "reason": f"Wallet has excess {ASSET} liquidity, so the agent executed Aave supply through CAW Pact.",
                        "pact_required": "internal_agent_rebalance",
                        "execution": execution,
                    }
                else:
                    decision = _execution_failed_decision("supply_to_aave", _fmt(excess), execution)
            else:
                pact = await submit_internal_rebalance_pact(_fmt(excess))
                decision = {
                    "action": "internal_rebalance_pact_required",
                    "amount": _fmt(excess),
                    "reason": "Wallet has excess liquidity. Submitted a CAW Aave contract-call pact for approval.",
                    "pact_required": "internal_agent_rebalance",
                    "pact": pact,
                }
    elif wallet_balance < target:
        shortage = target - wallet_balance
        pact_id = _find_known_internal_caw_pact_id(state)
        if pact_id:
            execution = await execute_aave_withdraw(pact_id=pact_id, amount=_fmt(shortage))
            if _execution_succeeded(execution):
                decision = {
                    "action": "withdraw_from_aave",
                    "amount": _fmt(shortage),
                    "reason": f"Wallet {ASSET} liquidity is below recommendation, so the agent executed Aave withdraw through CAW Pact.",
                    "pact_required": "internal_agent_rebalance",
                    "execution": execution,
                }
            else:
                decision = _execution_failed_decision("withdraw_from_aave", _fmt(shortage), execution)
        else:
            pact = await submit_internal_rebalance_pact(_fmt(shortage))
            decision = {
                "action": "internal_rebalance_pact_required",
                "amount": _fmt(shortage),
                "reason": "Wallet liquidity is below recommendation. Submitted a CAW Aave contract-call pact for approval.",
                "pact_required": "internal_agent_rebalance",
                "pact": pact,
            }

    if decision["action"] != "execution_failed":
        state["last_rebalance_at"] = _now_iso()
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "daily_rebalance", "decision": decision, "recommendation": recommendation})
    return {
        "status": "execution_failed" if decision["action"] == "execution_failed" else decision["action"],
        "decision": decision,
        "recommendation": recommendation,
        "treasury": await get_treasury_state(),
    }


async def create_external_transfer_pact(destination: str, amount: str) -> dict[str, Any]:
    state = _load_state()
    stats = get_transfer_stats(destination=destination)
    requested_amount = _asset_amount(amount)
    max_single = max(_asset_amount(stats["weekly_max_single_amount"]), requested_amount)
    tx_cap = max(1, (int(stats["weekly_transfer_count"]) + 1) * 2)

    local_proposal = _build_external_transfer_pact(
        destination=destination,
        pending_amount=_fmt(requested_amount),
        max_single_amount=_fmt(max_single),
        weekly_amount_cap=_fmt(max_single * tx_cap),
        weekly_tx_cap=tx_cap,
        status="pending_caw_submission",
        reason="External transfers require a CAW owner-approved destination-scoped pact.",
    )

    if not is_caw_configured():
        local_proposal["status"] = "caw_not_configured"
        local_proposal["reason"] = CAW_NOT_CONFIGURED_MESSAGE
    else:
        caw_result = await submit_wbtc_transfer_pact(destination=destination, max_amount=_fmt(max_single), tx_count=tx_cap)
        local_proposal["caw_submission"] = caw_result
        local_proposal["caw_pact_id"] = _extract_caw_pact_id(caw_result)
        local_proposal["status"] = (
            "pending_owner_approval" if local_proposal.get("caw_pact_id") else "caw_submission_failed"
        )

    state.setdefault("pacts", []).append(local_proposal)
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "external_transfer_pact_submitted", "pact": local_proposal})
    return local_proposal


async def execute_ready_pending_transfer() -> dict[str, Any]:
    state = await refresh_external_pact_statuses(_load_state())
    for pact in reversed(state.get("pacts", [])):
        pending = pact.get("pending_execution")
        if pact.get("pact_type") != "external_transfer" or not pending:
            continue
        if _pending_transfer_has_matching_event(pact, pending):
            pending["status"] = "completed"
            pending["updated_at"] = _now_iso()
            state["updated_at"] = _now_iso()
            _save_state(state)
            continue
        if pending.get("status") not in {"pending_owner_approval", "ready"}:
            continue
        if pact.get("status") != "active":
            continue
        if _is_legacy_usd_capped_transfer_pact(pact):
            pending["status"] = "blocked_legacy_pact"
            pending["updated_at"] = _now_iso()
            _save_state(state)
            return {"status": "blocked_legacy_pact", "pact": pact, "treasury": await get_treasury_state()}

        destination = str(pending["destination"])
        amount = str(pending["amount"])
        caw_pact_id = str(pact.get("caw_pact_id") or "")
        result = await execute_wbtc_transfer(pact_id=caw_pact_id, destination=destination, amount=amount)
        pending["updated_at"] = _now_iso()
        pending["execution"] = result
        if result.get("status") in {"ok", "success"}:
            pending["status"] = "completed"
            _append_event(
                {
                    "type": "external_transfer",
                    "destination": destination,
                    "asset": ASSET,
                    "amount": amount,
                    "pact_id": caw_pact_id,
                    "caw_result": result,
                }
            )
        else:
            pending["status"] = "execution_failed"
        state["updated_at"] = _now_iso()
        _save_state(state)
        return {"status": pending["status"], "execution": result, "pact": pact, "treasury": await get_treasury_state()}

    return {"status": "no_ready_pending_transfer", "treasury": await get_treasury_state()}


async def get_pending_transfer_status() -> dict[str, Any]:
    state = await refresh_external_pact_statuses(_load_state())
    for pact in reversed(state.get("pacts", [])):
        pending = pact.get("pending_execution")
        if pact.get("pact_type") != "external_transfer" or not pending:
            continue
        if _pending_transfer_has_matching_event(pact, pending):
            pending["status"] = "completed"
            pending["updated_at"] = _now_iso()
            state["updated_at"] = _now_iso()
            _save_state(state)
            continue
        pending_status = str(pending.get("status", ""))
        if pending_status in {"completed", "execution_failed", "blocked_legacy_pact"}:
            continue
        if _is_legacy_usd_capped_transfer_pact(pact):
            pending["status"] = "blocked_legacy_pact"
            pending["updated_at"] = _now_iso()
            _save_state(state)
            return {"status": "blocked_legacy_pact", "pact": pact, "treasury": await get_treasury_state()}
        pact_status = str(pact.get("status", ""))
        if pact_status == "active":
            pending["status"] = "ready"
            pending["updated_at"] = _now_iso()
            state["updated_at"] = _now_iso()
            _save_state(state)
            return {"status": "ready_to_execute", "pact": pact, "treasury": await get_treasury_state()}
        if pact_status in {"revoked", "rejected", "expired"}:
            pending["status"] = "approval_stopped"
            pending["updated_at"] = _now_iso()
            state["updated_at"] = _now_iso()
            _save_state(state)
            return {
                "status": "approval_stopped",
                "reason": f"Pact status is {pact_status}. Please submit the transfer again to create a new Pact.",
                "pact": pact,
                "treasury": await get_treasury_state(),
            }
        return {"status": "pending_owner_approval", "pact": pact, "treasury": await get_treasury_state()}
    return {"status": "no_pending_transfer", "treasury": await get_treasury_state()}


async def approve_local_pact(pact_id: str) -> dict[str, Any]:
    state = _load_state()
    pact = _find_pact_by_any_id(state, pact_id)
    if pact is None:
        return {"status": "not_found", "reason": f"Unknown pact_id: {pact_id}"}
    caw_pact_id = pact.get("caw_pact_id") or pact.get("pact_id")
    caw_status = await get_pact(caw_pact_id) if is_caw_configured() else {"reason": CAW_NOT_CONFIGURED_MESSAGE}
    pact["caw_status"] = caw_status
    pact["status"] = caw_status.get("status", pact.get("status", "unknown"))
    state["updated_at"] = _now_iso()
    _save_state(state)
    return {
        "status": pact["status"],
        "message": "Owner approval must happen in Cobo/CAW. This endpoint only refreshes pact status.",
        "pact": pact,
    }


async def send_asset(
    destination: str,
    amount: str,
    *,
    pact_id: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    requested_amount = _asset_amount(amount)
    if requested_amount <= Decimal("0"):
        return {"status": "rejected", "reason": "Transfer amount must be positive."}

    balances = _extract_real_balances(await get_aave_wallet_state())
    if _asset_amount(balances["wallet"]) < requested_amount:
        return {
            "status": "insufficient_wallet_balance",
            "reason": "Current CAW Sepolia wallet balance cannot cover this transfer.",
            "treasury": await get_treasury_state(),
        }

    state = await refresh_external_pact_statuses(_load_state())
    caw_pact_id = _resolve_external_transfer_caw_pact_id(state, pact_id, destination, requested_amount)
    caw_pact_id = caw_pact_id or _find_matching_caw_transfer_pact(state, destination, requested_amount)
    if not caw_pact_id:
        proposal = await create_external_transfer_pact(destination, amount)
        return {
            "status": "pact_required",
            "reason": "Submitted a real CAW transfer pact. Approve it in Cobo/CAW before execution.",
            "proposal": proposal,
            "treasury": await get_treasury_state(),
        }

    result = await execute_wbtc_transfer(pact_id=caw_pact_id, destination=destination, amount=amount)

    if result.get("status") in ("ok", "success") or result.get("uuid") or result.get("transaction_id"):
        _mark_pending_transfer_completed(
            state=state,
            caw_pact_id=caw_pact_id,
            destination=destination,
            amount=_fmt(requested_amount),
            execution=result,
        )
        _append_event(
            {
                "type": "external_transfer",
                "destination": destination,
                "asset": ASSET,
                "amount": _fmt(requested_amount),
                "pact_id": caw_pact_id,
                "caw_result": result,
            }
        )

    return {
        "status": str(result.get("status", "submitted" if execute else "proposal_only")),
        "execution": result,
        "transfer_stats_7d": get_transfer_stats(),
        "treasury": await get_treasury_state(),
    }


def calculate_recommendation(
    state: dict[str, Any], stats: dict[str, Any], balances: dict[str, str]
) -> dict[str, Any]:
    total = _asset_amount(balances["total"])
    strategy = state["strategy"]
    candidates = {
        "base_buffer": _asset_amount(strategy["base_buffer"]),
        "min_liquidity_ratio": total * _decimal(strategy["min_liquidity_ratio"]),
        "weekly_transfer_sum": _asset_amount(stats["weekly_transfer_sum"]) * _decimal(strategy["risk_multiplier"]),
        "weekly_max_single_amount": _asset_amount(stats["weekly_max_single_amount"])
        * _decimal(strategy["single_tx_multiplier"]),
    }
    recommended = min(total, max(candidates.values())) if total > 0 else Decimal("0")
    return {
        "recommended_liquidity": _fmt(recommended),
        "target_yield_balance": _fmt(max(Decimal("0"), total - recommended)),
        "candidates": {key: _fmt(value) for key, value in candidates.items()},
        "formula": "max(base_buffer, total_balance * min_liquidity_ratio, weekly_sum * risk_multiplier, weekly_max * single_tx_multiplier)",
    }


def get_transfer_stats(now: datetime | None = None, destination: str | None = None) -> dict[str, Any]:
    events = _read_events()
    current_time = now or datetime.now(timezone.utc)
    start = current_time - timedelta(days=7)
    transfers = [
        event
        for event in events
        if event.get("type") == "external_transfer" and _parse_time(event.get("created_at")) >= start
    ]
    if destination:
        transfers = [event for event in transfers if _same_address(event.get("destination"), destination)]
    amounts = [_asset_amount(event.get("amount", "0")) for event in transfers]
    count = len(amounts)
    total = sum(amounts, Decimal("0"))
    max_single = max(amounts) if amounts else Decimal("0")
    avg = total / count if count else Decimal("0")
    return {
        "weekly_transfer_count": count,
        "weekly_transfer_sum": _fmt(total),
        "weekly_max_single_amount": _fmt(max_single),
        "weekly_avg_transfer_amount": _fmt(avg),
    }


async def submit_internal_rebalance_pact(max_amount: str = "100") -> dict[str, Any]:
    result = await submit_aave_rebalance_pact(max_amount=max_amount)
    pact = _build_internal_rebalance_pact(
        max_amount=max_amount,
        status="pending_owner_approval" if _extract_caw_pact_id(result) else "caw_submission_failed",
        reason=f"CAW Aave contract-call pact for Sepolia {ASSET} approve, supply, and withdraw.",
    )
    pact["caw_submission"] = result
    pact["caw_pact_id"] = _extract_caw_pact_id(result)
    state = _load_state()
    state.setdefault("pacts", []).append(pact)
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "internal_rebalance_pact_submitted", "pact": pact})
    return pact


async def refresh_external_pact_statuses(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or _load_state()
    if not is_caw_configured():
        return state
    changed = False
    for pact in state.get("pacts", []):
        if pact.get("pact_type") != "external_transfer" or not pact.get("caw_pact_id"):
            continue
        caw_status = await get_pact(str(pact["caw_pact_id"]))
        if caw_status.get("status"):
            pact["caw_status"] = caw_status
            pact["status"] = caw_status["status"]
            changed = True
    if changed:
        state["updated_at"] = _now_iso()
        _save_state(state)
    return state


def _extract_real_balances(aave_state: dict[str, Any]) -> dict[str, str]:
    if aave_state.get("reason") or aave_state.get("status") == "error":
        return {"wallet": "0", "yield": "0", "total": "0"}
    wallet = _asset_amount(aave_state.get("wallet_balance", "0"))
    aave = _asset_amount(aave_state.get("aave_balance", "0"))
    return {"wallet": _fmt(wallet), "yield": _fmt(aave), "total": _fmt(wallet + aave)}


def _load_state() -> dict[str, Any]:
    if not TREASURY_STATE_PATH.exists():
        return _new_default_state()
    with TREASURY_STATE_PATH.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)
    return _merge_state_defaults(state)


def _new_default_state() -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_STATE)
    state["updated_at"] = _now_iso()
    _save_state(state)
    return state


def _save_state(state: dict[str, Any]) -> None:
    TREASURY_DIR.mkdir(parents=True, exist_ok=True)
    with TREASURY_STATE_PATH.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)
        state_file.write("\n")


def _merge_state_defaults(state: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_STATE)
    merged.update(state)
    merged["asset"] = ASSET
    merged["chain_id"] = CHAIN_ID
    merged["strategy"] = {**DEFAULT_STRATEGY, **state.get("strategy", {})}
    merged["pacts"] = [_normalize_pact(pact) for pact in state.get("pacts", []) if _should_keep_pact(pact)]
    return merged


def _normalize_pact(pact: dict[str, Any]) -> dict[str, Any]:
    if pact.get("pact_type") != "internal_agent_rebalance":
        return pact
    pact = copy.deepcopy(pact)
    if isinstance(pact.get("reason"), str):
        pact["reason"] = pact["reason"].replace("faucet, ", "")
    return pact


def _should_keep_pact(pact: dict[str, Any]) -> bool:
    if pact.get("pact_type") != "internal_agent_rebalance":
        return True
    if not pact.get("caw_pact_id"):
        return False
    serialized = json.dumps(pact, ensure_ascii=False).lower()
    return "faucet" not in serialized


def _append_event(event: dict[str, Any]) -> None:
    TREASURY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": _now_iso(), **event}
    with TREASURY_EVENTS_PATH.open("a", encoding="utf-8") as events_file:
        events_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _reset_events() -> None:
    TREASURY_DIR.mkdir(parents=True, exist_ok=True)
    TREASURY_EVENTS_PATH.write_text("", encoding="utf-8")


def _read_events() -> list[dict[str, Any]]:
    if not TREASURY_EVENTS_PATH.exists():
        return []
    events: list[dict[str, Any]] = []
    with TREASURY_EVENTS_PATH.open("r", encoding="utf-8") as events_file:
        for line in events_file:
            if line.strip():
                events.append(json.loads(line))
    return events


def _build_internal_rebalance_pact(*, max_amount: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "pact_id": f"pact-internal-{uuid.uuid4().hex[:10]}",
        "pact_type": "internal_agent_rebalance",
        "status": status,
        "scope": {
            "allowed_actions": ["aave_supply", "aave_withdraw"],
            "protocol": PROTOCOL,
            "asset": ASSET,
            "chain_id": CHAIN_ID,
            "max_amount": max_amount,
            "external_destination_allowed": False,
            "real_execution": True,
        },
        "duration": "7d",
        "reason": reason,
        "created_at": _now_iso(),
    }


def _build_external_transfer_pact(
    *,
    destination: str,
    pending_amount: str,
    max_single_amount: str,
    weekly_amount_cap: str,
    weekly_tx_cap: int,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "pact_id": f"pact-transfer-local-{uuid.uuid4().hex[:10]}",
        "pact_type": "external_transfer",
        "status": status,
        "scope": {
            "destination_address": destination,
            "asset": ASSET,
            "token_contract": WBTC,
            "execution_type": "erc20_contract_call",
            "chain_id": CHAIN_ID,
            "max_single_amount": max_single_amount,
            "weekly_amount_cap": weekly_amount_cap,
            "weekly_tx_cap": weekly_tx_cap,
        },
        "pending_execution": {
            "status": "pending_owner_approval",
            "destination": destination,
            "amount": pending_amount,
            "asset": ASSET,
            "created_at": _now_iso(),
        },
        "duration": "7d",
        "reason": reason,
        "created_at": _now_iso(),
    }


def _find_known_internal_pact(state: dict[str, Any]) -> dict[str, Any] | None:
    for pact in state.get("pacts", []):
        if pact.get("pact_type") == "internal_agent_rebalance":
            return pact
    return None


def _find_known_internal_caw_pact_id(state: dict[str, Any]) -> str | None:
    for pact in state.get("pacts", []):
        if (
            pact.get("pact_type") == "internal_agent_rebalance"
            and pact.get("status") == "active"
            and pact.get("caw_pact_id")
        ):
            return str(pact["caw_pact_id"])
    return None


def _find_pact_by_any_id(state: dict[str, Any], pact_id: str) -> dict[str, Any] | None:
    for pact in state.get("pacts", []):
        if pact_id in (pact.get("pact_id"), pact.get("caw_pact_id")):
            return pact
    return None


def _execution_succeeded(execution: dict[str, Any]) -> bool:
    return execution.get("status") == "ok"


def _execution_failed_decision(intended_action: str, amount: str, execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": "execution_failed",
        "intended_action": intended_action,
        "amount": amount,
        "reason": "CAW Pact execution failed, so the Aave strategy was not completed.",
        "pact_required": "internal_agent_rebalance",
        "execution": execution,
    }


def _find_matching_caw_transfer_pact(state: dict[str, Any], destination: str, amount: Decimal) -> str | None:
    stats = get_transfer_stats(destination=destination)
    for pact in state.get("pacts", []):
        scope = pact.get("scope", {})
        caw_pact_id = pact.get("caw_pact_id")
        if pact.get("pact_type") != "external_transfer" or not caw_pact_id:
            continue
        if pact.get("status") != "active":
            continue
        if _is_legacy_usd_capped_transfer_pact(pact):
            continue
        if scope.get("destination_address") != destination:
            continue
        next_count = int(stats["weekly_transfer_count"]) + 1
        next_sum = _asset_amount(stats["weekly_transfer_sum"]) + amount
        if amount <= _asset_amount(scope["max_single_amount"]) and next_sum <= _asset_amount(scope["weekly_amount_cap"]):
            if next_count <= int(scope["weekly_tx_cap"]):
                return caw_pact_id
    return None


def _resolve_external_transfer_caw_pact_id(
    state: dict[str, Any],
    pact_id: str | None,
    destination: str,
    amount: Decimal,
) -> str | None:
    if not pact_id:
        return None
    pact = _find_pact_by_any_id(state, pact_id)
    if pact is None:
        return pact_id
    if pact.get("pact_type") != "external_transfer":
        return pact_id
    if pact.get("status") != "active":
        return None
    if _is_legacy_usd_capped_transfer_pact(pact):
        return None
    scope = pact.get("scope", {})
    if not _same_address(scope.get("destination_address"), destination):
        return None
    if amount > _asset_amount(scope.get("max_single_amount", "0")):
        return None
    return str(pact.get("caw_pact_id") or "")


def _mark_pending_transfer_completed(
    *,
    state: dict[str, Any],
    caw_pact_id: str,
    destination: str,
    amount: str,
    execution: dict[str, Any],
) -> None:
    requested_amount = _asset_amount(amount)
    changed = False
    for pact in state.get("pacts", []):
        pending = pact.get("pending_execution")
        if pact.get("pact_type") != "external_transfer" or not pending:
            continue
        if str(pact.get("caw_pact_id") or "") != caw_pact_id:
            continue
        if not _same_address(str(pending.get("destination", "")), destination):
            continue
        if _asset_amount(pending.get("amount", "0")) != requested_amount:
            continue
        pending["status"] = "completed"
        pending["updated_at"] = _now_iso()
        pending["execution"] = execution
        changed = True
    if changed:
        state["updated_at"] = _now_iso()
        _save_state(state)


def _pending_transfer_has_matching_event(pact: dict[str, Any], pending: dict[str, Any]) -> bool:
    caw_pact_id = str(pact.get("caw_pact_id") or "")
    destination = str(pending.get("destination", ""))
    amount = _asset_amount(pending.get("amount", "0"))
    created_at = _parse_time(str(pending.get("created_at") or pact.get("created_at") or ""))
    for event in reversed(_read_events()):
        if event.get("type") != "external_transfer":
            continue
        if str(event.get("pact_id") or "") != caw_pact_id:
            continue
        if not _same_address(event.get("destination"), destination):
            continue
        if _asset_amount(event.get("amount", "0")) != amount:
            continue
        if _parse_time(event.get("created_at")) >= created_at:
            return True
    return False


def _extract_caw_pact_id(caw_result: dict[str, Any]) -> str | None:
    for key in ("pact_id", "id", "uuid"):
        value = caw_result.get(key)
        if value:
            return str(value)
    data = caw_result.get("data")
    if isinstance(data, dict):
        return _extract_caw_pact_id(data)
    return None


def _is_legacy_usd_capped_transfer_pact(pact: dict[str, Any]) -> bool:
    serialized = json.dumps(pact, ensure_ascii=False)
    if "amount_usd_gt" in serialized or "SETH_WBTC" in serialized:
        return True
    return '"type": "transfer"' in serialized or "'type': 'transfer'" in serialized


def _is_supply_gas_worthwhile(amount: Decimal, strategy: dict[str, Any]) -> bool:
    horizon_days = Decimal(str(strategy["rebalance_horizon_days"]))
    expected_yield = amount * _decimal(strategy["aave_apy"]) * (horizon_days / Decimal("365"))
    gas_cost = _asset_amount(strategy["gas_fee_asset"]) * _decimal(strategy["gas_safety_multiplier"])
    return expected_yield > gas_cost


def _asset_amount(value: Any) -> Decimal:
    return _decimal(value).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _fmt(value: Decimal) -> str:
    normalized = _asset_amount(value).normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    return datetime.fromisoformat(value)


def _same_address(left: Any, right: str) -> bool:
    return str(left or "").lower() == right.lower()
