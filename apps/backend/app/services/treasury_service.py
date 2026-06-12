from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.aave_service import (
    WBTC,
    estimate_aave_fees,
    estimate_aave_withdraw_fee,
    estimate_wbtc_transfer_fee,
    execute_aave_supply,
    execute_aave_withdraw,
    execute_wbtc_transfer,
    get_aave_wallet_state,
    submit_aave_rebalance_pact,
    submit_wbtc_transfer_pact,
)
from app.services.caw_service import (
    CAW_NOT_CONFIGURED_MESSAGE,
    get_asset_prices,
    get_pact,
    get_transaction_by_request_id,
    get_wallet_status,
    is_caw_configured,
)
from app.services.memory_service import load_profile
from app.services.treasury_policy import (
    asset_amount,
    build_effective_strategy,
    calculate_liquidity_target,
    calculate_rebalance_economics,
    fmt,
    percentile95,
    plan_transfer,
    project_stats_with_transfer,
)
from app.services.treasury_memory_service import (
    classify_transfer_events,
    planned_outflow_sum,
)


ROOT_DIR = Path(__file__).resolve().parents[4]
TREASURY_DIR = ROOT_DIR / "data" / "users" / "demo"
TREASURY_STATE_PATH = TREASURY_DIR / "wallet_state.json"
TREASURY_EVENTS_PATH = TREASURY_DIR / "events.jsonl"

ASSET = "WBTC"
TOKEN_ID = "WBTC"
CHAIN_ID = "SETH"
PROTOCOL = "Aave"
ACTIVE_TRANSFER_STAGES = {
    "checking_balance",
    "waiting_transfer_pact",
    "waiting_aave_pact",
    "estimating_gas",
    "withdrawing",
    "transferring",
}
TRANSFER_STAGE_ORDER = {
    "waiting_transfer_pact": 0,
    "checking_balance": 1,
    "waiting_aave_pact": 2,
    "estimating_gas": 3,
    "withdrawing": 4,
    "transferring": 5,
    "completed": 6,
}

DEFAULT_STRATEGY: dict[str, Any] = {
    "base_buffer": "0.05",
    "min_liquidity_ratio": "0.10",
    "liquidity_horizon_days": 7,
    "risk_multiplier": "1.20",
    "recurring_single_multiplier": "1.50",
    "gas_safety_multiplier": "1.20",
    "min_rebalance_amount": "0.001",
    "aave_apy": "0.02",
    "max_holding_days": 30,
    "transfer_history_days": 30,
}

DEFAULT_STATE: dict[str, Any] = {
    "wallet_id": "caw-sepolia-wallet",
    "asset": ASSET,
    "chain_id": CHAIN_ID,
    "strategy": DEFAULT_STRATEGY,
    "pacts": [],
    "pending_transfer": None,
    "balance_snapshot": None,
    "last_rebalance_preview": None,
    "last_rebalance_at": None,
    "updated_at": None,
}


async def initialize_wallet(deposit_amount: str | None = None) -> dict[str, Any]:
    state = _load_state()
    state["strategy"] = _migrate_strategy(state.get("strategy", {}))
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "wallet_initialized", "mode": "caw_aave_sepolia_real", "asset": ASSET})
    return await get_treasury_state()


async def get_treasury_state() -> dict[str, Any]:
    state = await refresh_pact_statuses(_load_state())
    aave_state, wallet_status = await asyncio.gather(get_aave_wallet_state(), get_wallet_status())
    return _compose_treasury_state(state, aave_state, wallet_status)


def _compose_treasury_state(
    state: dict[str, Any],
    aave_state: dict[str, Any],
    wallet_status: dict[str, Any],
) -> dict[str, Any]:
    balances = _extract_real_balances(aave_state, wallet_status)
    stats = get_transfer_stats()
    liquidity = _calculate_liquidity(state, stats, balances)
    classification_attention = _build_classification_attention(
        state=state,
        balances=balances,
        stats=stats,
        current_liquidity=liquidity,
    )
    recommendation = _legacy_recommendation(liquidity)
    return {
        "mode": "caw_aave_sepolia_real",
        "wallet_id": state["wallet_id"],
        "asset": state["asset"],
        "chain_id": state["chain_id"],
        "balances": balances,
        "liquidity": liquidity,
        "strategy": liquidity["effective_strategy"],
        "base_strategy": state["strategy"],
        "effective_strategy": liquidity["effective_strategy"],
        "profile_impacts": liquidity["profile_impacts"],
        "candidate_sources": liquidity["candidate_sources"],
        "classification_attention": classification_attention,
        "transfer_stats_7d": stats,
        "recommendation": recommendation,
        "rebalance_preview": state.get("last_rebalance_preview"),
        "pending_transfer": state.get("pending_transfer"),
        "pacts": _public_pacts(state.get("pacts", [])),
        "aave": aave_state,
        "wallet_status": wallet_status,
        "last_rebalance_at": state.get("last_rebalance_at"),
        "updated_at": state.get("updated_at"),
    }


def _build_classification_attention(
    *,
    state: dict[str, Any],
    balances: dict[str, str],
    stats: dict[str, Any],
    current_liquidity: dict[str, Any],
) -> dict[str, Any] | None:
    automatic_one_offs = [
        item
        for item in stats.get("transfer_classifications", [])
        if item.get("classification") == "one_off"
        and item.get("source") == "automatic"
    ]
    if not automatic_one_offs:
        return None

    current_effect = _classification_strategy_effect(
        state=state,
        balances=balances,
        liquidity=current_liquidity,
    )
    for event in sorted(
        automatic_one_offs,
        key=lambda item: asset_amount(item.get("amount", "0")),
        reverse=True,
    ):
        alternate_stats = get_transfer_stats(
            classification_overrides={
                str(event["event_id"]): {
                    "classification": "recurring",
                    "reason": "Impact simulation only.",
                }
            }
        )
        alternate_liquidity = _calculate_liquidity(
            state,
            alternate_stats,
            balances,
        )
        alternate_effect = _classification_strategy_effect(
            state=state,
            balances=balances,
            liquidity=alternate_liquidity,
        )
        liquidity_delta = abs(
            asset_amount(alternate_liquidity["target"])
            - asset_amount(current_liquidity["target"])
        )
        action_changed = current_effect["action"] != alternate_effect["action"]
        pact_gap_changed = (
            current_effect["requires_new_pact"]
            != alternate_effect["requires_new_pact"]
        )
        needs_attention = (
            liquidity_delta >= Decimal("0.01")
            or action_changed
            or pact_gap_changed
        )
        if needs_attention:
            return {
                "event": event,
                "automatic_classification": "one_off",
                "alternative_classification": "recurring",
                "needs_attention": True,
                "threshold": "0.01",
                "impact": {
                    "liquidity_delta": fmt(liquidity_delta),
                    "action_changed": action_changed,
                    "pact_gap_changed": pact_gap_changed,
                    "one_off": {
                        "recommended_liquidity": current_liquidity["target"],
                        "target_yield_balance": current_liquidity[
                            "target_yield_balance"
                        ],
                        **current_effect,
                    },
                    "recurring": {
                        "recommended_liquidity": alternate_liquidity["target"],
                        "target_yield_balance": alternate_liquidity[
                            "target_yield_balance"
                        ],
                        **alternate_effect,
                    },
                },
            }
    return None


def _classification_strategy_effect(
    *,
    state: dict[str, Any],
    balances: dict[str, str],
    liquidity: dict[str, Any],
) -> dict[str, Any]:
    current_aave = asset_amount(balances.get("aave_withdrawable", "0"))
    target_aave = asset_amount(liquidity["target_yield_balance"])
    delta = target_aave - current_aave
    if delta > 0:
        action = "supply_to_aave"
        amount = delta
    elif delta < 0:
        action = "withdraw_from_aave"
        amount = -delta
    else:
        action = "hold"
        amount = Decimal("0")
    active_limit = max(
        (
            asset_amount(pact.get("scope", {}).get("max_amount", "0"))
            for pact in state.get("pacts", [])
            if pact.get("pact_type") == "internal_agent_rebalance"
            and pact.get("status") == "active"
        ),
        default=Decimal("0"),
    )
    return {
        "action": action,
        "amount": fmt(amount),
        "requires_new_pact": amount > active_limit,
    }


async def preview_rebalance(*, record_event: bool = True) -> dict[str, Any]:
    state = await refresh_pact_statuses(_load_state())
    aave_state, wallet_status = await asyncio.gather(get_aave_wallet_state(), get_wallet_status())
    balances = _extract_real_balances(aave_state, wallet_status)
    stats = get_transfer_stats()
    profile = load_profile()
    effective_strategy, profile_impacts = build_effective_strategy(state["strategy"], profile)
    wallet = asset_amount(balances["wallet_available"])
    aave = asset_amount(balances["aave_withdrawable"])
    total = asset_amount(balances["total"])
    sample_amount = fmt(
        max(
            asset_amount(effective_strategy["min_rebalance_amount"]),
            total,
            Decimal("0.00000001"),
        )
    )
    active_pact_id = _find_known_internal_caw_pact_id(state, asset_amount(sample_amount))
    fee_estimates, prices = await asyncio.gather(
        estimate_aave_fees(amount=sample_amount, pact_id=active_pact_id),
        _load_asset_prices(),
    )
    converted = _convert_aave_fee_amounts(fee_estimates, prices)
    liquidity = _calculate_liquidity(
        state,
        stats,
        balances,
        estimated_withdraw_gas_asset=converted["amounts_wbtc"].get("withdraw", "0"),
        profile=profile,
        effective_strategy=effective_strategy,
        profile_impacts=profile_impacts,
    )
    target = asset_amount(liquidity["target"])

    if wallet < target:
        amount = min(aave, target - wallet)
        exact_fees = fee_estimates
        exact_converted = converted
        required_native = asset_amount(fee_estimates.get("amounts", {}).get("withdraw", "0"))
        gas_available = asset_amount(balances["gas_native"])
        allowed = amount > 0 and fee_estimates.get("status") == "ok" and gas_available >= required_native
        preview = {
            "action": "withdraw_from_aave" if allowed else "hold",
            "allowed": allowed,
            "amount": fmt(amount),
            "estimated_fees": exact_converted,
            "expected_yield": "0",
            "net_benefit": "0",
            "reason": (
                "Wallet liquidity is below target."
                if allowed
                else "Aave withdrawal is unavailable, its Gas could not be estimated, or SETH is insufficient."
            ),
            "gas_available": fmt(gas_available),
            "required_native_gas": fmt(required_native),
            "liquidity": liquidity,
        }
    else:
        excess = max(Decimal("0"), wallet - target)
        exact_fees = fee_estimates
        exact_converted = converted
        economics = calculate_rebalance_economics(
            wallet_available=wallet,
            liquidity_target=target,
            stats=stats,
            strategy=effective_strategy,
            approve_gas_asset=exact_converted["amounts_wbtc"].get("approve", "0"),
            supply_gas_asset=exact_converted["amounts_wbtc"].get("supply", "0"),
            withdraw_gas_asset=exact_converted["amounts_wbtc"].get("withdraw", "0"),
            prices_available=exact_converted["prices_available"] and exact_fees.get("status") == "ok",
        )
        required_native = asset_amount(exact_fees.get("amounts", {}).get("approve", "0")) + asset_amount(
            exact_fees.get("amounts", {}).get("supply", "0")
        )
        gas_available = asset_amount(balances["gas_native"])
        if economics["allowed"] and gas_available < required_native:
            economics["allowed"] = False
            economics["action"] = "hold"
            economics["reason"] = "SETH balance cannot cover the estimated approve and supply Gas."
        preview = {
            **economics,
            "estimated_fees": exact_converted,
            "gas_available": fmt(gas_available),
            "required_native_gas": fmt(required_native),
            "liquidity": liquidity,
        }

    state["last_rebalance_preview"] = preview
    state["updated_at"] = _now_iso()
    _save_state(state)
    if record_event:
        _append_event({"type": "rebalance_preview", "preview": _compact_preview(preview)})
    return preview


async def run_daily_rebalance() -> dict[str, Any]:
    preview = await preview_rebalance()
    state = await refresh_pact_statuses(_load_state())
    action = str(preview.get("action", "hold"))
    amount = str(preview.get("amount", "0"))
    if not preview.get("allowed") or action == "hold" or asset_amount(amount) <= 0:
        decision = {
            "action": "hold",
            "amount": amount,
            "reason": preview.get("reason", "No rebalance is needed."),
            "preview": preview,
        }
        _append_event({"type": "rebalance_hold", "decision": _compact_decision(decision)})
        return {"status": "hold", "decision": decision, "recommendation": preview["liquidity"], "treasury": await get_treasury_state()}

    pact_id = _find_known_internal_caw_pact_id(state, asset_amount(amount))
    if not pact_id:
        pact = await submit_internal_rebalance_pact(fmt(max(asset_amount(amount), asset_amount("1"))))
        decision = {
            "action": "internal_rebalance_pact_required",
            "amount": amount,
            "reason": "Submitted a CAW Aave Pact for owner approval.",
            "pact": pact,
            "preview": preview,
        }
        return {
            "status": "internal_rebalance_pact_required",
            "decision": decision,
            "recommendation": preview["liquidity"],
            "treasury": await get_treasury_state(),
        }

    if action == "supply_to_aave":
        execution = await execute_aave_supply(
            pact_id=pact_id,
            amount=amount,
            request_ids={
                "approve": f"rebalance-approve-{uuid.uuid4()}",
                "supply": f"rebalance-supply-{uuid.uuid4()}",
            },
        )
    else:
        execution = await execute_aave_withdraw(
            pact_id=pact_id,
            amount=amount,
            request_id=f"rebalance-withdraw-{uuid.uuid4()}",
        )
    succeeded = _execution_succeeded(execution)
    decision = {
        "action": action if succeeded else "execution_failed",
        "intended_action": action,
        "amount": amount,
        "reason": preview["reason"] if succeeded else "CAW Aave execution did not complete.",
        "execution": execution,
        "preview": preview,
    }
    state = _load_state()
    if succeeded:
        state["last_rebalance_at"] = _now_iso()
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "rebalance_execution", "decision": decision})
    return {
        "status": action if succeeded else "execution_failed",
        "decision": decision,
        "recommendation": preview["liquidity"],
        "treasury": await get_treasury_state(),
    }


async def sync_treasury() -> dict[str, Any]:
    state = await refresh_pact_statuses(_load_state())
    aave_state, wallet_status = await asyncio.gather(get_aave_wallet_state(), get_wallet_status())
    balances = _extract_real_balances(aave_state, wallet_status)
    previous = state.get("balance_snapshot") or {}
    previous_wallet = asset_amount(previous.get("wallet_available", balances["wallet_available"]))
    current_wallet = asset_amount(balances["wallet_available"])
    incoming = max(Decimal("0"), current_wallet - previous_wallet)
    detected = incoming > 0
    state["balance_snapshot"] = {
        "wallet_available": balances["wallet_available"],
        "aave_withdrawable": balances["aave_withdrawable"],
        "updated_at": _now_iso(),
    }
    state["updated_at"] = _now_iso()
    _save_state(state)
    if detected:
        _append_event({"type": "incoming_funds_detected", "asset": ASSET, "amount": fmt(incoming)})
    return {
        "status": "incoming_funds_detected" if detected else "synced",
        "incoming_amount": fmt(incoming),
        "treasury": _compose_treasury_state(state, aave_state, wallet_status),
    }


async def sync_workspace() -> dict[str, Any]:
    sync_result = await sync_treasury()
    preview = await preview_rebalance(record_event=False)
    treasury = sync_result["treasury"]
    treasury["liquidity"] = preview["liquidity"]
    treasury["recommendation"] = _legacy_recommendation(preview["liquidity"])
    treasury["rebalance_preview"] = preview
    treasury["strategy"] = preview["liquidity"]["effective_strategy"]
    treasury["effective_strategy"] = preview["liquidity"]["effective_strategy"]
    treasury["profile_impacts"] = preview["liquidity"]["profile_impacts"]
    treasury["candidate_sources"] = preview["liquidity"]["candidate_sources"]
    return {
        "status": sync_result["status"],
        "synced_at": _now_iso(),
        "incoming_amount": sync_result["incoming_amount"],
        "profile": load_profile(),
        "treasury": treasury,
        "preview": preview,
    }


async def send_asset(
    destination: str,
    amount: str,
    *,
    pact_id: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    requested = asset_amount(amount)
    if requested <= 0:
        return {"status": "rejected", "reason": "Transfer amount must be positive."}

    state = _restore_latest_transfer_intent(_load_state())
    state = await refresh_pact_statuses(state)
    state = await _reconcile_completed_pending_transfer(state)
    active_pending = state.get("pending_transfer")
    if isinstance(active_pending, dict) and active_pending.get("stage") in ACTIVE_TRANSFER_STAGES:
        if _same_address(active_pending.get("destination"), destination) and asset_amount(active_pending.get("amount")) == requested:
            return {
                "status": str(active_pending["stage"]),
                "reason": "This transfer is already in progress.",
                "pending_transfer": active_pending,
                "treasury": await get_treasury_state(),
            }
        return {
            "status": "transfer_in_progress",
            "reason": "Another transfer is still in progress.",
            "pending_transfer": active_pending,
            "treasury": await get_treasury_state(),
        }

    aave_state, wallet_status = await asyncio.gather(get_aave_wallet_state(), get_wallet_status())
    balances = _extract_real_balances(aave_state, wallet_status)
    if asset_amount(balances["total"]) < requested:
        return {
            "status": "insufficient_total_balance",
            "reason": "Combined wallet and Aave balance cannot cover this transfer.",
            "treasury": await get_treasury_state(),
        }

    caw_pact_id = _resolve_external_transfer_caw_pact_id(state, pact_id, destination, requested)
    caw_pact_id = caw_pact_id or _find_matching_caw_transfer_pact(state, destination, requested)
    if not caw_pact_id:
        proposal = await create_external_transfer_pact(destination, amount)
        return {
            "status": "pact_required",
            "reason": "Submitted a destination-scoped CAW transfer Pact for approval.",
            "proposal": proposal,
            "pending_transfer": proposal.get("pending_execution"),
            "treasury": await get_treasury_state(),
        }

    state = _load_state()
    state["pending_transfer"] = _new_pending_transfer(
        destination=destination,
        amount=fmt(requested),
        transfer_pact_id=caw_pact_id,
        stage="checking_balance",
    )
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "transfer_started", "pending_transfer": state["pending_transfer"]})
    return await execute_ready_pending_transfer()


async def create_external_transfer_pact(destination: str, amount: str) -> dict[str, Any]:
    state = _load_state()
    stats = get_transfer_stats(destination=destination)
    requested = asset_amount(amount)
    max_single = max(asset_amount(stats["weekly_max_single_amount"]), requested)
    tx_cap = max(1, (int(stats["weekly_transfer_count"]) + 1) * 2)
    proposal = _build_external_transfer_pact(
        destination=destination,
        pending_amount=fmt(requested),
        max_single_amount=fmt(max_single),
        weekly_amount_cap=fmt(max_single * tx_cap),
        weekly_tx_cap=tx_cap,
        status="pending_caw_submission",
        reason="External transfers require a CAW owner-approved destination-scoped Pact.",
    )
    if not is_caw_configured():
        proposal["status"] = "caw_not_configured"
        proposal["reason"] = CAW_NOT_CONFIGURED_MESSAGE
    else:
        result = await submit_wbtc_transfer_pact(
            destination=destination,
            max_amount=fmt(max_single),
            tx_count=tx_cap,
        )
        proposal["caw_submission"] = result
        proposal["caw_pact_id"] = _extract_caw_pact_id(result)
        proposal["status"] = "pending_owner_approval" if proposal.get("caw_pact_id") else "caw_submission_failed"
    state.setdefault("pacts", []).append(proposal)
    state["pending_transfer"] = _new_pending_transfer(
        destination=destination,
        amount=fmt(requested),
        transfer_pact_id=str(proposal.get("caw_pact_id") or proposal["pact_id"]),
        stage="waiting_transfer_pact",
    )
    proposal["pending_execution"] = state["pending_transfer"]
    state["updated_at"] = _now_iso()
    _save_state(state)
    _append_event({"type": "external_transfer_pact_submitted", "pact": proposal})
    return proposal


async def execute_ready_pending_transfer() -> dict[str, Any]:
    state = await refresh_pact_statuses(_load_state())
    pending = state.get("pending_transfer")
    if not isinstance(pending, dict) or pending.get("stage") not in ACTIVE_TRANSFER_STAGES:
        return {"status": "no_ready_pending_transfer", "treasury": await get_treasury_state()}

    destination = str(pending["destination"])
    amount = asset_amount(pending["amount"])
    transfer_pact = _find_pact_by_any_id(state, str(pending.get("transfer_pact_id") or ""))
    if not transfer_pact:
        proposal = await create_external_transfer_pact(destination, fmt(amount))
        return {
            "status": "pact_required",
            "reason": "Submitted a destination-scoped CAW transfer Pact for approval.",
            "proposal": proposal,
            "pact": proposal,
            "pending_transfer": proposal.get("pending_execution"),
            "treasury": await get_treasury_state(),
        }
    if transfer_pact.get("status") != "active":
        pending["stage"] = "waiting_transfer_pact"
        _save_pending(state, pending)
        return {"status": "pending_owner_approval", "pact": transfer_pact, "pending_transfer": pending, "treasury": await get_treasury_state()}

    aave_state, wallet_status = await asyncio.gather(get_aave_wallet_state(), get_wallet_status())
    balances = _extract_real_balances(aave_state, wallet_status)
    wallet = asset_amount(balances["wallet_available"])
    aave = asset_amount(balances["aave_withdrawable"])
    if wallet + aave < amount:
        return await _fail_pending(state, pending, "insufficient_total_balance", "Combined wallet and Aave balance cannot cover this transfer.")

    needs_withdraw = wallet < amount
    if needs_withdraw:
        pending["stage"] = "estimating_gas"
        _save_pending(state, pending)
        preliminary_fee = await estimate_aave_withdraw_fee(
            amount=fmt(amount - wallet),
            pact_id=None,
        )
        transfer_fee = await estimate_wbtc_transfer_fee(
            destination=destination,
            amount=fmt(amount),
            pact_id=str(transfer_pact["caw_pact_id"]),
        )
        prices = await _load_asset_prices()
        preliminary_converted = _convert_single_fee(preliminary_fee, prices)
        if preliminary_fee.get("status") != "ok" or transfer_fee.get("status") != "ok" or not preliminary_converted["prices_available"]:
            return await _fail_pending(
                state,
                pending,
                "fee_estimation_failed",
                "Aave withdrawal or transfer Gas could not be estimated.",
                retryable=True,
            )
        projected_stats = project_stats_with_transfer(get_transfer_stats(), amount)
        post_total = wallet + aave - amount
        projected_balances = {**balances, "total": fmt(post_total)}
        liquidity_after = _calculate_liquidity(
            state,
            projected_stats,
            projected_balances,
            estimated_withdraw_gas_asset=preliminary_converted["fee_wbtc"],
        )
        transfer_plan = plan_transfer(
            wallet_available=wallet,
            aave_withdrawable=aave,
            amount=amount,
            post_transfer_liquidity_target=liquidity_after["target"],
        )
        withdraw_amount = str(transfer_plan["withdraw_amount"])
        pending["withdraw_amount"] = withdraw_amount
        pending["liquidity_after_transfer"] = liquidity_after
        pending["estimated_fees"] = {
            "withdraw_preliminary": preliminary_converted,
            "transfer": transfer_fee,
        }
        _save_pending(state, pending)

        internal_pact_id = _find_known_internal_caw_pact_id(
            state,
            asset_amount(withdraw_amount),
        )
        if not internal_pact_id:
            pending_pact = _find_pending_internal_pact(
                state,
                asset_amount(withdraw_amount),
            )
            if not pending_pact:
                pending_pact = await submit_internal_rebalance_pact(
                    fmt(max(asset_amount(withdraw_amount), Decimal("1")))
                )
                state = _load_state()
                pending = state["pending_transfer"]
            pending["aave_pact_id"] = pending_pact.get("caw_pact_id") or pending_pact.get("pact_id")
            pending["stage"] = "waiting_aave_pact"
            _save_pending(state, pending)
            return {
                "status": "waiting_aave_pact",
                "reason": (
                    f"Transfer Pact is active. Aave must withdraw {withdraw_amount} {ASSET}; "
                    "the required Aave Pact now needs owner approval."
                ),
                "pact": pending_pact,
                "pending_transfer": pending,
                "treasury": await get_treasury_state(),
            }

        exact_fee = await estimate_aave_withdraw_fee(amount=withdraw_amount, pact_id=internal_pact_id)
        exact_converted = _convert_single_fee(exact_fee, prices)
        required_native_gas = asset_amount(exact_fee.get("fee_amount", "0")) + asset_amount(
            transfer_fee.get("fee_amount", "0")
        )
        if exact_fee.get("status") != "ok":
            return await _fail_pending(state, pending, "fee_estimation_failed", "Exact Aave withdrawal Gas could not be estimated.", retryable=True)
        if asset_amount(balances["gas_native"]) < required_native_gas:
            return await _fail_pending(
                state,
                pending,
                "insufficient_gas_balance",
                f"Wallet needs about {fmt(required_native_gas)} SETH for withdraw and transfer Gas.",
                retryable=True,
            )
        pending["estimated_fees"] = {
            "withdraw": exact_converted,
            "transfer": transfer_fee,
            "required_native_gas": fmt(required_native_gas),
        }
        if not pending.get("withdraw_request_id"):
            pending["withdraw_request_id"] = f"auto-withdraw-{uuid.uuid4()}"
        pending["stage"] = "withdrawing"
        _save_pending(state, pending)

        if not await _request_completed(str(pending["withdraw_request_id"])):
            withdrawal = await execute_aave_withdraw(
                pact_id=str(internal_pact_id),
                amount=withdraw_amount,
                request_id=str(pending["withdraw_request_id"]),
            )
            pending["withdraw_execution"] = withdrawal
            if not _execution_succeeded(withdrawal):
                return await _fail_pending(state, pending, "withdraw_failed", "Aave withdrawal did not complete.", execution=withdrawal, retryable=True)
            _append_event({"type": "auto_liquidity_withdraw", "amount": withdraw_amount, "execution": withdrawal})
        pending["stage"] = "transferring"
        _save_pending(state, pending)
    else:
        transfer_fee = await estimate_wbtc_transfer_fee(
            destination=destination,
            amount=fmt(amount),
            pact_id=str(transfer_pact["caw_pact_id"]),
        )
        pending["estimated_fees"] = {"transfer": transfer_fee}
        pending["stage"] = "transferring"
        _save_pending(state, pending)

    if not pending.get("transfer_request_id"):
        pending["transfer_request_id"] = f"auto-transfer-{uuid.uuid4()}"
        _save_pending(state, pending)
    if await _request_completed(str(pending["transfer_request_id"])):
        execution = pending.get("transfer_execution") or {"status": "ok", "reason": "Existing request completed."}
    else:
        execution = await execute_wbtc_transfer(
            pact_id=str(transfer_pact["caw_pact_id"]),
            destination=destination,
            amount=fmt(amount),
            request_id=str(pending["transfer_request_id"]),
        )
    pending["transfer_execution"] = execution
    if not _execution_succeeded(execution):
        return await _fail_pending(state, pending, "transfer_failed", "WBTC transfer did not complete.", execution=execution, retryable=True)

    pending["stage"] = "completed"
    pending["completed_at"] = _now_iso()
    _save_pending(state, pending)
    _update_balance_snapshot_from_execution(state, execution)
    _mark_embedded_pending(state, pending)
    _append_event(
        {
            "type": "external_transfer",
            "destination": destination,
            "asset": ASSET,
            "amount": fmt(amount),
            "pact_id": transfer_pact["caw_pact_id"],
            "caw_result": execution,
            "withdraw_amount": pending.get("withdraw_amount", "0"),
        }
    )
    return {
        "status": "completed",
        "execution": execution,
        "pending_transfer": pending,
        "treasury": await get_treasury_state(),
    }


async def get_pending_transfer_status() -> dict[str, Any]:
    state = _restore_latest_transfer_intent(_load_state())
    state = await refresh_pact_statuses(state)
    state = await _reconcile_completed_pending_transfer(state)
    pending = state.get("pending_transfer")
    if not isinstance(pending, dict):
        return {"status": "no_pending_transfer", "treasury": await get_treasury_state()}
    stage = str(pending.get("stage", ""))
    if stage == "waiting_transfer_pact":
        pact = _find_pact_by_any_id(state, str(pending.get("transfer_pact_id") or ""))
        if pact and pact.get("status") == "active":
            pending["stage"] = "checking_balance"
            _save_pending(state, pending)
            return {"status": "ready_to_execute", "pending_transfer": pending, "treasury": await get_treasury_state()}
        if pact and pact.get("status") in {"revoked", "rejected", "expired"}:
            return await _fail_pending(state, pending, "approval_stopped", f"Transfer Pact is {pact['status']}.")
        return {"status": "pending_owner_approval", "pact": pact, "pending_transfer": pending, "treasury": await get_treasury_state()}
    if stage == "waiting_aave_pact":
        pact = _find_pact_by_any_id(state, str(pending.get("aave_pact_id") or ""))
        if pact and pact.get("status") == "active":
            pending["stage"] = "estimating_gas"
            _save_pending(state, pending)
            return {"status": "ready_to_execute", "pending_transfer": pending, "treasury": await get_treasury_state()}
        if pact and pact.get("status") in {"revoked", "rejected", "expired"}:
            return await _fail_pending(state, pending, "approval_stopped", f"Aave Pact is {pact['status']}.")
        return {"status": "waiting_aave_pact", "pact": pact, "pending_transfer": pending, "treasury": await get_treasury_state()}
    if stage in {"checking_balance", "estimating_gas", "withdrawing", "transferring"}:
        return {"status": "ready_to_execute", "pending_transfer": pending, "treasury": await get_treasury_state()}
    return {"status": stage or "no_pending_transfer", "reason": pending.get("reason"), "pending_transfer": pending, "treasury": await get_treasury_state()}


async def approve_local_pact(pact_id: str) -> dict[str, Any]:
    state = _load_state()
    pact = _find_pact_by_any_id(state, pact_id)
    if pact is None:
        return {"status": "not_found", "reason": f"Unknown pact_id: {pact_id}"}
    caw_pact_id = str(pact.get("caw_pact_id") or pact.get("pact_id"))
    caw_status = await get_pact(caw_pact_id) if is_caw_configured() else {"reason": CAW_NOT_CONFIGURED_MESSAGE}
    pact["caw_status"] = caw_status
    pact["status"] = caw_status.get("status", pact.get("status", "unknown"))
    state["updated_at"] = _now_iso()
    _save_state(state)
    return {
        "status": pact["status"],
        "message": "Owner approval must happen in Cobo/CAW. This endpoint refreshes Pact status.",
        "pact": pact,
    }


async def submit_internal_rebalance_pact(max_amount: str = "100") -> dict[str, Any]:
    result = await submit_aave_rebalance_pact(max_amount=max_amount)
    pact = _build_internal_rebalance_pact(
        max_amount=max_amount,
        status="pending_owner_approval" if _extract_caw_pact_id(result) else "caw_submission_failed",
        reason=f"CAW Aave contract-call Pact for Sepolia {ASSET} approve, supply, and withdraw.",
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
    return await refresh_pact_statuses(state)


async def refresh_pact_statuses(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or _load_state()
    if not is_caw_configured():
        return state
    changed = False
    for pact in state.get("pacts", []):
        if not pact.get("caw_pact_id"):
            continue
        if pact.get("status") in {"active", "revoked", "rejected", "expired"}:
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


def calculate_recommendation(
    state: dict[str, Any],
    stats: dict[str, Any],
    balances: dict[str, str],
) -> dict[str, Any]:
    return _legacy_recommendation(_calculate_liquidity(state, stats, balances))


def get_transfer_stats(
    now: datetime | None = None,
    destination: str | None = None,
    history_days: int | None = None,
    classification_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    events = _read_events()
    days = history_days or int(_load_state()["strategy"].get("transfer_history_days", 30))
    current_time = now or datetime.now(timezone.utc)
    start = current_time - timedelta(days=days)
    transfers = [
        event
        for event in events
        if event.get("type") == "external_transfer" and _parse_time(event.get("created_at")) >= start
    ]
    if destination:
        transfers = [event for event in transfers if _same_address(event.get("destination"), destination)]
    amounts = [asset_amount(event.get("amount", "0")) for event in transfers]
    classified = classify_transfer_events(transfers, classification_overrides)
    recurring_amounts = classified.pop("recurring_amounts")
    one_off_amounts = classified.pop("one_off_amounts")
    total = sum(amounts, Decimal("0"))
    count = len(amounts)
    maximum = max(amounts) if amounts else Decimal("0")
    average = total / count if count else Decimal("0")
    return {
        "history_days": days,
        "transfer_count": count,
        "transfer_sum": fmt(total),
        "p95_transfer_amount": fmt(percentile95(amounts)),
        "amounts": [fmt(value) for value in recurring_amounts],
        "raw_amounts": [fmt(value) for value in amounts],
        "recurring_amounts": [fmt(value) for value in recurring_amounts],
        "one_off_amounts": [fmt(value) for value in one_off_amounts],
        "weekly_transfer_count": count,
        "weekly_transfer_sum": fmt(total),
        "weekly_max_single_amount": fmt(maximum),
        "weekly_avg_transfer_amount": fmt(average),
        **classified,
    }


def _calculate_liquidity(
    state: dict[str, Any],
    stats: dict[str, Any],
    balances: dict[str, str],
    *,
    estimated_withdraw_gas_asset: str = "0",
    profile: dict[str, Any] | None = None,
    effective_strategy: dict[str, Any] | None = None,
    profile_impacts: list[dict[str, Any]] | None = None,
    additional_planned_outflows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = profile or load_profile()
    effective_strategy, profile_impacts = (
        (effective_strategy, profile_impacts or [])
        if effective_strategy is not None
        else build_effective_strategy(state["strategy"], profile)
    )
    user_floor = profile.get("user_preferences", {}).get("liquidity_floor") or "0"
    calculation_stats = {
        **stats,
        "planned_outflow_sum": planned_outflow_sum(
            horizon_days=int(effective_strategy.get("liquidity_horizon_days", 7)),
            additional=additional_planned_outflows,
        ),
    }
    result = calculate_liquidity_target(
        total_balance=balances["total"],
        stats=calculation_stats,
        strategy=effective_strategy,
        user_floor=user_floor,
        estimated_withdraw_gas_asset=estimated_withdraw_gas_asset,
    )
    total = asset_amount(balances["total"])
    wallet = asset_amount(balances.get("wallet_available", balances.get("wallet", "0")))
    result["current_ratio"] = fmt(wallet / total if total > 0 else Decimal("0"))
    result["effective_strategy"] = effective_strategy
    result["profile_impacts"] = profile_impacts
    result["candidate_sources"] = _candidate_sources(profile)
    return result


async def preview_profile_liquidity(profile: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    aave_state, wallet_status = await asyncio.gather(get_aave_wallet_state(), get_wallet_status())
    balances = _extract_real_balances(aave_state, wallet_status)
    stats = get_transfer_stats()
    current = _calculate_liquidity(state, stats, balances)
    proposed = _calculate_liquidity(state, stats, balances, profile=profile)
    return {
        "asset": ASSET,
        "before": _compact_liquidity_impact(current),
        "after": _compact_liquidity_impact(proposed),
        "strategy_history": {
            "recurring_transfer_sum": stats.get("recurring_transfer_sum", "0"),
            "recurring_p90_transfer_amount": stats.get(
                "recurring_p90_transfer_amount", "0"
            ),
            "excluded_transfer_count": stats.get("excluded_transfer_count", 0),
            "excluded_transfers": [
                item
                for item in stats.get("transfer_classifications", [])
                if item.get("classification") == "one_off"
            ],
        },
        "changed": current["target"] != proposed["target"]
        or current["target_yield_balance"] != proposed["target_yield_balance"],
    }


async def preview_treasury_scenarios(
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    state = await refresh_pact_statuses(_load_state())
    aave_state, wallet_status = await asyncio.gather(
        get_aave_wallet_state(),
        get_wallet_status(),
    )
    balances = _extract_real_balances(aave_state, wallet_status)
    stats = get_transfer_stats()
    current = _calculate_liquidity(state, stats, balances)
    active_pact_limit = max(
        (
            asset_amount(pact.get("scope", {}).get("max_amount", "0"))
            for pact in state.get("pacts", [])
            if pact.get("pact_type") == "internal_agent_rebalance"
            and pact.get("status") == "active"
        ),
        default=Decimal("0"),
    )
    current_aave = asset_amount(balances.get("aave_withdrawable", "0"))
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        proposed = _calculate_liquidity(
            state,
            stats,
            balances,
            profile=scenario["profile"],
            additional_planned_outflows=scenario.get("planned_outflows", []),
        )
        target_aave = asset_amount(proposed["target_yield_balance"])
        delta = target_aave - current_aave
        if delta > 0:
            action = "supply_to_aave"
            amount = delta
        elif delta < 0:
            action = "withdraw_from_aave"
            amount = -delta
        else:
            action = "hold"
            amount = Decimal("0")
        pact_gap = max(Decimal("0"), amount - active_pact_limit)
        results.append(
            {
                "scenario_id": scenario["scenario_id"],
                "label": scenario["label"],
                "profile_patch": scenario["profile_patch"],
                "planned_outflows": scenario.get("planned_outflows", []),
                "before": _compact_liquidity_impact(current),
                "after": _compact_liquidity_impact(proposed),
                "recurring_statistics": {
                    "recurring_transfer_sum": stats.get("recurring_transfer_sum", "0"),
                    "recurring_p90_transfer_amount": stats.get(
                        "recurring_p90_transfer_amount", "0"
                    ),
                    "excluded_transfer_count": stats.get(
                        "excluded_transfer_count", 0
                    ),
                },
                "expected_action": {
                    "action": action,
                    "amount": fmt(amount),
                },
                "pact_gap": {
                    "active_internal_limit": fmt(active_pact_limit),
                    "additional_limit_required": fmt(pact_gap),
                    "requires_new_pact": pact_gap > 0,
                },
            }
        )
    return results


def _compact_liquidity_impact(liquidity: dict[str, Any]) -> dict[str, Any]:
    dominant_key = max(
        liquidity["components"],
        key=lambda key: asset_amount(liquidity["components"][key]),
    )
    return {
        "recommended_liquidity": liquidity["target"],
        "target_yield_balance": liquidity["target_yield_balance"],
        "candidates": liquidity["components"],
        "effective_strategy": liquidity["effective_strategy"],
        "dominant_candidate": dominant_key,
    }


def _candidate_sources(profile: dict[str, Any]) -> dict[str, str]:
    preferences = profile.get("user_preferences", {})
    risk_level = preferences.get("risk_level", "balanced")
    user_floor = preferences.get("liquidity_floor")
    horizon = preferences.get("liquidity_horizon_days")
    return {
        "user_floor": "PROFILE" if user_floor is not None else "SYSTEM",
        "min_liquidity_ratio": "PROFILE" if risk_level != "balanced" else "SYSTEM",
        "flow_horizon": "PROFILE + HISTORY" if risk_level != "balanced" or horizon else "HISTORY",
        "recurring_single_buffer": (
            "PROFILE + HISTORY" if risk_level != "balanced" else "HISTORY"
        ),
        "planned_outflow": "PROFILE",
        "economic_batch": "SYSTEM",
    }


def _legacy_recommendation(liquidity: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommended_liquidity": liquidity["target"],
        "target_yield_balance": liquidity["target_yield_balance"],
        "candidates": liquidity["components"],
        "formula": liquidity["formula"],
    }


def _extract_real_balances(aave_state: dict[str, Any], wallet_status: dict[str, Any] | None = None) -> dict[str, str]:
    if aave_state.get("reason") or aave_state.get("status") == "error":
        wallet = Decimal("0")
        aave = Decimal("0")
    else:
        wallet = asset_amount(aave_state.get("wallet_balance", "0"))
        aave = asset_amount(aave_state.get("aave_balance", "0"))
    gas_native = _extract_native_gas_balance(wallet_status or {})
    return {
        "wallet_available": fmt(wallet),
        "aave_withdrawable": fmt(aave),
        "gas_native": fmt(gas_native),
        "wallet": fmt(wallet),
        "yield": fmt(aave),
        "aave": fmt(aave),
        "total": fmt(wallet + aave),
    }


def _extract_native_gas_balance(wallet_status: dict[str, Any]) -> Decimal:
    for balance in wallet_status.get("balances", []):
        token_id = str(balance.get("token_id") or balance.get("symbol") or "")
        chain_id = str(balance.get("chain_id") or "")
        if token_id in {"SETH", "ETH"} and chain_id in {"", CHAIN_ID}:
            return asset_amount(
                balance.get("available")
                or balance.get("balance")
                or balance.get("amount")
                or balance.get("total")
                or "0"
            )
    return Decimal("0")


async def _load_asset_prices() -> dict[str, Any]:
    raw = await get_asset_prices("ETH,BTC", "USD")
    eth = _find_price(raw, {"ETH", "SETH", "ethereum"})
    btc = _find_price(raw, {"BTC", "WBTC", "bitcoin"})
    return {
        "status": "ok" if eth > 0 and btc > 0 else "error",
        "SETH_USD": fmt(eth),
        "WBTC_USD": fmt(btc),
        "raw": raw,
    }


def _find_price(value: Any, names: set[str]) -> Decimal:
    lowered = {name.lower() for name in names}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in lowered:
                if isinstance(item, (str, int, float, Decimal)):
                    return asset_amount(item)
                found = _price_from_record(item)
                if found > 0:
                    return found
        record_name = str(
            value.get("symbol")
            or value.get("asset_coin")
            or value.get("coin")
            or value.get("id")
            or value.get("name")
            or ""
        ).lower()
        if record_name in lowered:
            found = _price_from_record(value)
            if found > 0:
                return found
        for item in value.values():
            found = _find_price(item, names)
            if found > 0:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_price(item, names)
            if found > 0:
                return found
    return Decimal("0")


def _price_from_record(value: Any) -> Decimal:
    if not isinstance(value, dict):
        return Decimal("0")
    for key in ("price", "price_usd", "current_price", "value"):
        if value.get(key) not in (None, ""):
            try:
                return asset_amount(value[key])
            except Exception:
                return Decimal("0")
    return Decimal("0")


def _convert_aave_fee_amounts(fees: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    eth_price = asset_amount(prices.get("SETH_USD", "0"))
    btc_price = asset_amount(prices.get("WBTC_USD", "0"))
    available = eth_price > 0 and btc_price > 0
    amounts_native = fees.get("amounts", {}) if isinstance(fees.get("amounts"), dict) else {}
    amounts_wbtc = {
        name: fmt(asset_amount(value) * eth_price / btc_price) if available else "0"
        for name, value in amounts_native.items()
    }
    return {
        "token_id": fees.get("token_id", "SETH"),
        "amounts_native": amounts_native,
        "amounts_wbtc": amounts_wbtc,
        "prices": {key: prices.get(key) for key in ("SETH_USD", "WBTC_USD")},
        "prices_available": available,
        "raw": fees.get("calls", {}),
    }


def _convert_single_fee(fee: dict[str, Any], prices: dict[str, Any]) -> dict[str, Any]:
    eth_price = asset_amount(prices.get("SETH_USD", "0"))
    btc_price = asset_amount(prices.get("WBTC_USD", "0"))
    available = eth_price > 0 and btc_price > 0
    fee_native = asset_amount(fee.get("fee_amount", "0"))
    return {
        "token_id": fee.get("token_id", "SETH"),
        "fee_native": fmt(fee_native),
        "fee_wbtc": fmt(fee_native * eth_price / btc_price) if available else "0",
        "prices": {key: prices.get(key) for key in ("SETH_USD", "WBTC_USD")},
        "prices_available": available,
        "raw": fee.get("estimate", {}),
    }


def _load_state() -> dict[str, Any]:
    if not TREASURY_STATE_PATH.exists():
        return _new_default_state()
    with TREASURY_STATE_PATH.open("r", encoding="utf-8") as state_file:
        return _merge_state_defaults(json.load(state_file))


def _new_default_state() -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_STATE)
    state["updated_at"] = _now_iso()
    _save_state(state)
    return state


def _save_state(state: dict[str, Any]) -> None:
    TREASURY_DIR.mkdir(parents=True, exist_ok=True)
    state_to_save = copy.deepcopy(state)
    if TREASURY_STATE_PATH.exists():
        try:
            with TREASURY_STATE_PATH.open("r", encoding="utf-8") as current_file:
                current_state = json.load(current_file)
            state_to_save["pending_transfer"] = _prefer_latest_pending_transfer(
                current_state.get("pending_transfer"),
                state_to_save.get("pending_transfer"),
            )
        except (OSError, json.JSONDecodeError):
            pass
    with TREASURY_STATE_PATH.open("w", encoding="utf-8") as state_file:
        json.dump(state_to_save, state_file, ensure_ascii=False, indent=2)
        state_file.write("\n")
    state["pending_transfer"] = copy.deepcopy(state_to_save.get("pending_transfer"))


def _merge_state_defaults(state: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_STATE)
    merged.update(state)
    merged["asset"] = ASSET
    merged["chain_id"] = CHAIN_ID
    merged["strategy"] = _migrate_strategy(state.get("strategy", {}))
    merged["pacts"] = [
        _normalize_pact(pact)
        for pact in state.get("pacts", [])
        if _should_keep_pact(pact)
    ]
    return merged


def _migrate_strategy(strategy: dict[str, Any]) -> dict[str, Any]:
    migrated = {**DEFAULT_STRATEGY, **strategy}
    if (
        "recurring_single_multiplier" not in strategy
        and strategy.get("single_tx_multiplier") is not None
    ):
        migrated["recurring_single_multiplier"] = strategy["single_tx_multiplier"]
    return migrated


def _normalize_pact(pact: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(pact)
    if normalized.get("pact_type") == "internal_agent_rebalance" and isinstance(normalized.get("reason"), str):
        normalized["reason"] = normalized["reason"].replace("faucet, ", "")
    return normalized


def _public_pacts(pacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for pact in pacts:
        public.append(
            {
                key: copy.deepcopy(value)
                for key, value in pact.items()
                if key not in {"caw_status", "caw_submission"}
            }
        )
    return public


def _should_keep_pact(pact: dict[str, Any]) -> bool:
    if pact.get("pact_type") != "internal_agent_rebalance":
        return True
    if not pact.get("caw_pact_id"):
        return False
    return "faucet" not in json.dumps(pact, ensure_ascii=False).lower()


def _append_event(event: dict[str, Any]) -> None:
    TREASURY_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "event_id": str(event.get("event_id") or f"event-{uuid.uuid4().hex[:16]}"),
        "created_at": _now_iso(),
        **event,
    }
    with TREASURY_EVENTS_PATH.open("a", encoding="utf-8") as events_file:
        events_file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_events() -> list[dict[str, Any]]:
    if not TREASURY_EVENTS_PATH.exists():
        return []
    events: list[dict[str, Any]] = []
    with TREASURY_EVENTS_PATH.open("r", encoding="utf-8") as events_file:
        for line in events_file:
            if line.strip():
                events.append(json.loads(line))
    return events


def _external_transfer_event_exists(request_id: str) -> bool:
    for event in reversed(_read_events()):
        if event.get("type") != "external_transfer":
            continue
        result = event.get("caw_result")
        if isinstance(result, dict) and str(result.get("request_id") or "") == request_id:
            return True
    return False


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
        "duration": "7d",
        "reason": reason,
        "created_at": _now_iso(),
    }


def _new_pending_transfer(
    *,
    destination: str,
    amount: str,
    transfer_pact_id: str,
    stage: str,
) -> dict[str, Any]:
    return {
        "id": f"transfer-{uuid.uuid4().hex[:12]}",
        "stage": stage,
        "status": stage,
        "destination": destination,
        "amount": amount,
        "asset": ASSET,
        "transfer_pact_id": transfer_pact_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def _prefer_latest_pending_transfer(current: Any, incoming: Any) -> Any:
    if isinstance(current, dict) and incoming is None:
        return current
    if not isinstance(current, dict) or not isinstance(incoming, dict):
        return incoming
    if current.get("id") != incoming.get("id"):
        current_created = _parse_time(current.get("created_at"))
        incoming_created = _parse_time(incoming.get("created_at"))
        return current if current_created > incoming_created else incoming

    current_stage = str(current.get("stage", ""))
    incoming_stage = str(incoming.get("stage", ""))
    if current_stage not in ACTIVE_TRANSFER_STAGES and incoming_stage in ACTIVE_TRANSFER_STAGES:
        return current
    if (
        current_stage in TRANSFER_STAGE_ORDER
        and incoming_stage in TRANSFER_STAGE_ORDER
        and TRANSFER_STAGE_ORDER[current_stage] > TRANSFER_STAGE_ORDER[incoming_stage]
    ):
        return current

    current_updated = _parse_time(current.get("updated_at"))
    incoming_updated = _parse_time(incoming.get("updated_at"))
    return current if current_updated > incoming_updated else incoming


def _restore_latest_transfer_intent(state: dict[str, Any]) -> dict[str, Any]:
    events = _read_events()
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        candidate = event.get("pending_transfer")
        if event.get("type") != "transfer_started" or not isinstance(candidate, dict):
            continue
        later_events = events[index + 1 :]
        completed_later = any(
            later.get("type") == "external_transfer"
            and _same_address(later.get("destination"), candidate.get("destination"))
            and asset_amount(later.get("amount", "0")) == asset_amount(candidate.get("amount", "0"))
            for later in later_events
        )
        failed_later = any(
            later.get("type") == "transfer_flow_failed"
            and later.get("pending_transfer", {}).get("id") == candidate.get("id")
            for later in later_events
            if isinstance(later.get("pending_transfer"), dict)
        )
        if completed_later or failed_later:
            return state

        current = state.get("pending_transfer")
        current_created = _parse_time(current.get("created_at")) if isinstance(current, dict) else _parse_time(None)
        candidate_created = _parse_time(candidate.get("created_at"))
        if candidate_created > current_created:
            state["pending_transfer"] = copy.deepcopy(candidate)
            state["updated_at"] = _now_iso()
            _save_state(state)
            return _load_state()
        return state
    return state


def _save_pending(state: dict[str, Any], pending: dict[str, Any]) -> None:
    pending["status"] = pending.get("stage")
    pending["updated_at"] = _now_iso()
    state["pending_transfer"] = pending
    state["updated_at"] = _now_iso()
    _save_state(state)


async def _reconcile_completed_pending_transfer(state: dict[str, Any]) -> dict[str, Any]:
    pending = state.get("pending_transfer")
    if not isinstance(pending, dict) or pending.get("stage") not in ACTIVE_TRANSFER_STAGES:
        return state
    request_id = str(pending.get("transfer_request_id") or "")
    if not request_id:
        return state
    completed_on_caw = await _request_completed(request_id)
    completed_in_audit = _external_transfer_event_exists(request_id)
    if not completed_on_caw and not completed_in_audit:
        return state

    pending = copy.deepcopy(pending)
    pending["stage"] = "completed"
    pending["status"] = "completed"
    pending["completed_at"] = pending.get("completed_at") or _now_iso()
    pending["transfer_execution"] = pending.get("transfer_execution") or {
        "status": "completed",
        "reason": "Recovered from completed CAW request.",
        "request_id": request_id,
    }
    _save_pending(state, pending)
    _mark_embedded_pending(state, pending)
    if not completed_in_audit:
        _append_event(
            {
                "type": "external_transfer",
                "destination": pending.get("destination"),
                "asset": ASSET,
                "amount": pending.get("amount"),
                "pact_id": pending.get("transfer_pact_id"),
                "caw_result": pending["transfer_execution"],
                "withdraw_amount": pending.get("withdraw_amount", "0"),
                "recovered": True,
            }
        )
    return _load_state()


async def _fail_pending(
    state: dict[str, Any],
    pending: dict[str, Any],
    status: str,
    reason: str,
    *,
    execution: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    pending["stage"] = status
    pending["status"] = status
    pending["reason"] = reason
    pending["retryable"] = retryable
    if execution is not None:
        pending["execution"] = execution
    _save_pending(state, pending)
    _append_event({"type": "transfer_flow_failed", "pending_transfer": pending})
    return {
        "status": status,
        "reason": reason,
        "execution": execution,
        "pending_transfer": pending,
        "treasury": await get_treasury_state(),
    }


def _mark_embedded_pending(state: dict[str, Any], pending: dict[str, Any]) -> None:
    for pact in state.get("pacts", []):
        if str(pact.get("caw_pact_id") or pact.get("pact_id")) == str(pending.get("transfer_pact_id")):
            pact["pending_execution"] = copy.deepcopy(pending)
    state["updated_at"] = _now_iso()
    _save_state(state)


def _update_balance_snapshot_from_execution(state: dict[str, Any], execution: dict[str, Any]) -> None:
    aave_state = execution.get("aave")
    if not isinstance(aave_state, dict) or aave_state.get("wallet_balance") in (None, ""):
        return
    state["balance_snapshot"] = {
        "wallet_available": str(aave_state["wallet_balance"]),
        "aave_withdrawable": str(aave_state.get("aave_balance", "0")),
        "updated_at": _now_iso(),
    }
    state["updated_at"] = _now_iso()
    _save_state(state)


def _find_known_internal_caw_pact_id(
    state: dict[str, Any],
    required_amount: Decimal | None = None,
) -> str | None:
    for pact in reversed(state.get("pacts", [])):
        if (
            pact.get("pact_type") == "internal_agent_rebalance"
            and pact.get("status") == "active"
            and pact.get("caw_pact_id")
        ):
            if required_amount is not None and asset_amount(pact.get("scope", {}).get("max_amount", "0")) < required_amount:
                continue
            return str(pact["caw_pact_id"])
    return None


def _find_pending_internal_pact(
    state: dict[str, Any],
    required_amount: Decimal | None = None,
) -> dict[str, Any] | None:
    for pact in reversed(state.get("pacts", [])):
        if pact.get("pact_type") == "internal_agent_rebalance" and pact.get("status") not in {
            "active",
            "revoked",
            "rejected",
            "expired",
            "caw_submission_failed",
        }:
            if required_amount is not None and asset_amount(pact.get("scope", {}).get("max_amount", "0")) < required_amount:
                continue
            return pact
    return None


def _find_pact_by_any_id(state: dict[str, Any], pact_id: str) -> dict[str, Any] | None:
    for pact in state.get("pacts", []):
        if pact_id in (pact.get("pact_id"), pact.get("caw_pact_id")):
            return pact
    return None


def _find_matching_caw_transfer_pact(state: dict[str, Any], destination: str, amount: Decimal) -> str | None:
    stats = get_transfer_stats(destination=destination)
    for pact in reversed(state.get("pacts", [])):
        scope = pact.get("scope", {})
        if pact.get("pact_type") != "external_transfer" or pact.get("status") != "active":
            continue
        if _is_legacy_usd_capped_transfer_pact(pact):
            continue
        if not _same_address(scope.get("destination_address"), destination):
            continue
        next_count = int(stats["weekly_transfer_count"]) + 1
        next_sum = asset_amount(stats["weekly_transfer_sum"]) + amount
        if (
            amount <= asset_amount(scope.get("max_single_amount", "0"))
            and next_sum <= asset_amount(scope.get("weekly_amount_cap", "0"))
            and next_count <= int(scope.get("weekly_tx_cap", 0))
        ):
            return str(pact.get("caw_pact_id") or "")
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
        return None
    if pact.get("pact_type") != "external_transfer" or pact.get("status") != "active":
        return None
    scope = pact.get("scope", {})
    if _is_legacy_usd_capped_transfer_pact(pact):
        return None
    if not _same_address(scope.get("destination_address"), destination):
        return None
    if amount > asset_amount(scope.get("max_single_amount", "0")):
        return None
    return str(pact.get("caw_pact_id") or "")


async def _request_completed(request_id: str) -> bool:
    detail = await get_transaction_by_request_id(request_id)
    return _transaction_succeeded(detail)


def _transaction_succeeded(value: Any) -> bool:
    if isinstance(value, dict):
        status = value.get("status")
        if status in {900, "900", "success", "Success", "completed", "Completed"}:
            return True
        if value.get("is_success") is True or value.get("sub_status") == "completed":
            return True
        return any(_transaction_succeeded(item) for item in value.values())
    if isinstance(value, list):
        return any(_transaction_succeeded(item) for item in value)
    return False


def _execution_succeeded(execution: dict[str, Any]) -> bool:
    return execution.get("status") in {"ok", "success", "completed"}


def _extract_caw_pact_id(caw_result: dict[str, Any]) -> str | None:
    for key in ("pact_id", "id", "uuid"):
        if caw_result.get(key):
            return str(caw_result[key])
    data = caw_result.get("data")
    return _extract_caw_pact_id(data) if isinstance(data, dict) else None


def _is_legacy_usd_capped_transfer_pact(pact: dict[str, Any]) -> bool:
    serialized = json.dumps(pact, ensure_ascii=False)
    return (
        "amount_usd_gt" in serialized
        or "SETH_WBTC" in serialized
        or '"type": "transfer"' in serialized
        or "'type': 'transfer'" in serialized
    )


def _compact_preview(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        key: preview.get(key)
        for key in ("action", "allowed", "amount", "expected_yield", "net_benefit", "reason")
    }


def _compact_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {key: decision.get(key) for key in ("action", "amount", "reason")}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.fromtimestamp(0, timezone.utc)
    return datetime.fromisoformat(value)


def _same_address(left: Any, right: Any) -> bool:
    return str(left or "").lower() == str(right or "").lower()
