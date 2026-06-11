from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


ASSET_QUANTUM = Decimal("0.00000001")

RISK_STRATEGY_OVERRIDES: dict[str, dict[str, Any]] = {
    "conservative": {
        "min_liquidity_ratio": "0.15",
        "risk_multiplier": "1.50",
        "single_tx_multiplier": "2.00",
    },
    "balanced": {},
    "aggressive": {
        "min_liquidity_ratio": "0.07",
        "risk_multiplier": "1.00",
        "single_tx_multiplier": "1.20",
    },
}

SYSTEM_SAFETY_FLOORS = {
    "min_liquidity_ratio": Decimal("0.05"),
    "risk_multiplier": Decimal("1.00"),
    "single_tx_multiplier": Decimal("1.00"),
}


def build_effective_strategy(
    base_strategy: dict[str, Any],
    profile: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    effective = dict(base_strategy)
    impacts: list[dict[str, Any]] = []
    preferences = (profile or {}).get("user_preferences", {})
    habits = (profile or {}).get("transaction_habits", {})
    risk_level = str(preferences.get("risk_level") or "balanced").lower()

    for field, value in RISK_STRATEGY_OVERRIDES.get(risk_level, {}).items():
        before = effective.get(field)
        floor = SYSTEM_SAFETY_FLOORS.get(field)
        adjusted = max(decimal(value), floor) if floor is not None else decimal(value)
        effective[field] = fmt(adjusted) if field == "min_liquidity_ratio" else str(adjusted)
        if str(before) != str(effective[field]):
            impacts.append(
                {
                    "profile_field": "risk_level",
                    "strategy_field": field,
                    "before": before,
                    "after": effective[field],
                }
            )

    horizon = preferences.get("liquidity_horizon_days")
    if horizon is not None:
        before = effective.get("liquidity_horizon_days")
        effective["liquidity_horizon_days"] = max(1, min(90, int(horizon)))
        if before != effective["liquidity_horizon_days"]:
            impacts.append(
                {
                    "profile_field": "liquidity_horizon_days",
                    "strategy_field": "liquidity_horizon_days",
                    "before": before,
                    "after": effective["liquidity_horizon_days"],
                }
            )

    if habits.get("prefers_low_gas"):
        low_gas_overrides = {
            "gas_safety_multiplier": max(
                decimal(effective.get("gas_safety_multiplier", "1")), Decimal("1.50")
            ),
            "min_rebalance_amount": max(
                asset_amount(effective.get("min_rebalance_amount", "0")), Decimal("0.01")
            ),
        }
        for field, value in low_gas_overrides.items():
            before = effective.get(field)
            effective[field] = fmt(value)
            if str(before) != str(effective[field]):
                impacts.append(
                    {
                        "profile_field": "prefers_low_gas",
                        "strategy_field": field,
                        "before": before,
                        "after": effective[field],
                    }
                )

    return effective, impacts


def calculate_liquidity_target(
    *,
    total_balance: Any,
    stats: dict[str, Any],
    strategy: dict[str, Any],
    user_floor: Any = "0",
    estimated_withdraw_gas_asset: Any = "0",
) -> dict[str, Any]:
    total = asset_amount(total_balance)
    apy = decimal(strategy.get("aave_apy", "0"))
    history_days = max(1, int(stats.get("history_days", 7)))
    transfer_sum = asset_amount(stats.get("transfer_sum", stats.get("weekly_transfer_sum", "0")))
    average_daily_outflow = transfer_sum / Decimal(history_days)
    annual_outflow = average_daily_outflow * Decimal("365")
    withdraw_gas = asset_amount(estimated_withdraw_gas_asset)

    economic_batch = Decimal("0")
    if withdraw_gas > 0 and annual_outflow > 0 and apy > 0:
        economic_batch = decimal((Decimal("2") * withdraw_gas * annual_outflow / apy).sqrt())

    p95_transfer = asset_amount(
        stats.get("p95_transfer_amount", stats.get("weekly_max_single_amount", "0"))
    )
    candidates = {
        "user_floor": max(asset_amount(user_floor), asset_amount(strategy.get("base_buffer", "0"))),
        "min_liquidity_ratio": total * decimal(strategy.get("min_liquidity_ratio", "0")),
        "flow_horizon": (
            average_daily_outflow
            * decimal(strategy.get("liquidity_horizon_days", strategy.get("rebalance_horizon_days", 7)))
            * decimal(strategy.get("risk_multiplier", "1"))
        ),
        "p95_transfer": p95_transfer * decimal(strategy.get("single_tx_multiplier", "1")),
        "economic_batch": economic_batch,
    }
    target = min(total, max(candidates.values())) if total > 0 else Decimal("0")
    return {
        "target": fmt(target),
        "target_yield_balance": fmt(max(Decimal("0"), total - target)),
        "components": {key: fmt(value) for key, value in candidates.items()},
        "average_daily_outflow": fmt(average_daily_outflow),
        "annual_outflow": fmt(annual_outflow),
        "formula": (
            "min(total, max(user_floor, total * min_liquidity_ratio, "
            "avg_daily_outflow * liquidity_horizon_days * risk_multiplier, "
            "p95_transfer * single_tx_multiplier, economic_batch))"
        ),
    }


def plan_transfer(
    *,
    wallet_available: Any,
    aave_withdrawable: Any,
    amount: Any,
    post_transfer_liquidity_target: Any,
) -> dict[str, Any]:
    wallet = asset_amount(wallet_available)
    aave = asset_amount(aave_withdrawable)
    requested = asset_amount(amount)
    total = wallet + aave

    if requested <= 0:
        return {"action": "reject", "reason": "Transfer amount must be positive.", "withdraw_amount": "0"}
    if total < requested:
        return {
            "action": "reject",
            "reason": "Total wallet and Aave balance cannot cover this transfer.",
            "withdraw_amount": "0",
        }
    if wallet >= requested:
        return {"action": "transfer", "reason": "Wallet liquidity covers the transfer.", "withdraw_amount": "0"}

    target_after = min(max(Decimal("0"), total - requested), asset_amount(post_transfer_liquidity_target))
    withdraw = requested + target_after - wallet
    withdraw = min(aave, max(Decimal("0"), withdraw))
    return {
        "action": "withdraw_then_transfer",
        "reason": "Wallet liquidity is low, so withdraw enough for this transfer and the next liquidity buffer.",
        "withdraw_amount": fmt(withdraw),
        "post_transfer_liquidity_target": fmt(target_after),
    }


def calculate_rebalance_economics(
    *,
    wallet_available: Any,
    liquidity_target: Any,
    stats: dict[str, Any],
    strategy: dict[str, Any],
    approve_gas_asset: Any = "0",
    supply_gas_asset: Any = "0",
    withdraw_gas_asset: Any = "0",
    prices_available: bool = True,
) -> dict[str, Any]:
    wallet = asset_amount(wallet_available)
    target = asset_amount(liquidity_target)
    excess = max(Decimal("0"), wallet - target)
    min_rebalance = asset_amount(strategy.get("min_rebalance_amount", "0"))
    history_days = max(1, int(stats.get("history_days", 7)))
    transfer_sum = asset_amount(stats.get("transfer_sum", stats.get("weekly_transfer_sum", "0")))
    average_daily_outflow = transfer_sum / Decimal(history_days)
    minimum_holding_days = decimal(
        strategy.get("liquidity_horizon_days", strategy.get("rebalance_horizon_days", 7))
    )
    if average_daily_outflow > 0:
        holding_days = max(minimum_holding_days, target / average_daily_outflow)
    else:
        holding_days = decimal(strategy.get("max_holding_days", "30"))
    holding_days = min(holding_days, decimal(strategy.get("max_holding_days", "30")))

    expected_yield = (
        excess * decimal(strategy.get("aave_apy", "0")) * holding_days / Decimal("365")
    )
    round_trip_gas = (
        asset_amount(approve_gas_asset)
        + asset_amount(supply_gas_asset)
        + asset_amount(withdraw_gas_asset)
    )
    guarded_gas = round_trip_gas * decimal(strategy.get("gas_safety_multiplier", "1"))
    net_benefit = expected_yield - guarded_gas

    allowed = True
    reason = "Supply is expected to earn more than its estimated round-trip Gas cost."
    if excess < min_rebalance:
        allowed = False
        reason = "Excess liquidity is below the minimum rebalance amount."
    elif not prices_available:
        allowed = False
        reason = "Gas could not be converted to WBTC, so supply is disabled."
    elif net_benefit <= 0:
        allowed = False
        reason = "Estimated Aave yield does not cover the round-trip Gas cost."

    return {
        "action": "supply_to_aave" if allowed else "hold",
        "allowed": allowed,
        "amount": fmt(excess),
        "expected_holding_days": fmt(holding_days),
        "expected_yield": fmt(expected_yield),
        "round_trip_gas": fmt(round_trip_gas),
        "guarded_gas": fmt(guarded_gas),
        "net_benefit": fmt(net_benefit),
        "reason": reason,
    }


def project_stats_with_transfer(stats: dict[str, Any], amount: Any) -> dict[str, Any]:
    projected = dict(stats)
    requested = asset_amount(amount)
    amounts = [asset_amount(value) for value in stats.get("amounts", [])]
    amounts.append(requested)
    transfer_sum = sum(amounts, Decimal("0"))
    projected.update(
        {
            "transfer_count": len(amounts),
            "transfer_sum": fmt(transfer_sum),
            "p95_transfer_amount": fmt(percentile95(amounts)),
            "weekly_transfer_count": len(amounts),
            "weekly_transfer_sum": fmt(transfer_sum),
            "weekly_max_single_amount": fmt(max(amounts) if amounts else Decimal("0")),
            "amounts": [fmt(value) for value in amounts],
        }
    )
    return projected


def percentile95(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    ordered = sorted(values)
    index = max(0, (len(ordered) * 95 + 99) // 100 - 1)
    return ordered[min(index, len(ordered) - 1)]


def asset_amount(value: Any) -> Decimal:
    return decimal(value).quantize(ASSET_QUANTUM, rounding=ROUND_HALF_UP)


def decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def fmt(value: Decimal) -> str:
    normalized = asset_amount(value).normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
