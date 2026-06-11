from __future__ import annotations

import unittest
from decimal import Decimal

from app.services.treasury_policy import (
    build_effective_strategy,
    calculate_liquidity_target,
    calculate_rebalance_economics,
    plan_transfer,
    project_stats_with_transfer,
)


STRATEGY = {
    "base_buffer": "0.05",
    "min_liquidity_ratio": "0.10",
    "liquidity_horizon_days": 7,
    "risk_multiplier": "1.20",
    "single_tx_multiplier": "1.50",
    "gas_safety_multiplier": "1.20",
    "min_rebalance_amount": "0.001",
    "aave_apy": "0.02",
    "max_holding_days": 30,
}


class TreasuryPolicyTests(unittest.TestCase):
    def test_conservative_profile_increases_liquidity_buffers(self) -> None:
        effective, impacts = build_effective_strategy(
            STRATEGY,
            {
                "user_preferences": {
                    "risk_level": "conservative",
                    "liquidity_horizon_days": 14,
                },
                "transaction_habits": {"prefers_low_gas": False},
            },
        )

        self.assertEqual(effective["min_liquidity_ratio"], "0.15")
        self.assertEqual(effective["risk_multiplier"], "1.50")
        self.assertEqual(effective["single_tx_multiplier"], "2.00")
        self.assertEqual(effective["liquidity_horizon_days"], 14)
        self.assertTrue(impacts)

    def test_aggressive_profile_never_crosses_system_safety_floors(self) -> None:
        effective, _ = build_effective_strategy(
            STRATEGY,
            {
                "user_preferences": {"risk_level": "aggressive"},
                "transaction_habits": {"prefers_low_gas": False},
            },
        )

        self.assertGreaterEqual(Decimal(effective["min_liquidity_ratio"]), Decimal("0.05"))
        self.assertGreaterEqual(Decimal(effective["risk_multiplier"]), Decimal("1"))
        self.assertGreaterEqual(Decimal(effective["single_tx_multiplier"]), Decimal("1"))

    def test_low_gas_profile_raises_rebalance_threshold(self) -> None:
        effective, impacts = build_effective_strategy(
            STRATEGY,
            {
                "user_preferences": {"risk_level": "balanced"},
                "transaction_habits": {"prefers_low_gas": True},
            },
        )

        self.assertEqual(effective["min_rebalance_amount"], "0.01")
        self.assertEqual(effective["gas_safety_multiplier"], "1.5")
        self.assertTrue(
            any(impact["profile_field"] == "prefers_low_gas" for impact in impacts)
        )

    def test_liquidity_target_uses_largest_constraint(self) -> None:
        result = calculate_liquidity_target(
            total_balance="1",
            stats={
                "history_days": 7,
                "transfer_sum": "0.14",
                "p95_transfer_amount": "0.03",
            },
            strategy=STRATEGY,
            user_floor="0.02",
            estimated_withdraw_gas_asset="0.00001",
        )

        self.assertEqual(result["components"]["min_liquidity_ratio"], "0.1")
        self.assertGreaterEqual(Decimal(result["target"]), Decimal("0.1"))

    def test_projected_transfer_is_included_in_future_buffer(self) -> None:
        projected = project_stats_with_transfer(
            {
                "history_days": 7,
                "amounts": ["0.01", "0.02"],
                "transfer_sum": "0.03",
            },
            "0.05",
        )

        self.assertEqual(projected["transfer_sum"], "0.08")
        self.assertEqual(projected["p95_transfer_amount"], "0.05")

    def test_transfer_uses_wallet_without_withdraw(self) -> None:
        result = plan_transfer(
            wallet_available="0.2",
            aave_withdrawable="0.8",
            amount="0.1",
            post_transfer_liquidity_target="0.1",
        )

        self.assertEqual(result["action"], "transfer")
        self.assertEqual(result["withdraw_amount"], "0")

    def test_transfer_withdraws_current_amount_and_future_buffer(self) -> None:
        result = plan_transfer(
            wallet_available="0.02",
            aave_withdrawable="0.98",
            amount="0.05",
            post_transfer_liquidity_target="0.1",
        )

        self.assertEqual(result["action"], "withdraw_then_transfer")
        self.assertEqual(result["withdraw_amount"], "0.13")

    def test_transfer_rejects_when_total_is_insufficient(self) -> None:
        result = plan_transfer(
            wallet_available="0.02",
            aave_withdrawable="0.03",
            amount="0.06",
            post_transfer_liquidity_target="0",
        )

        self.assertEqual(result["action"], "reject")

    def test_supply_is_blocked_when_gas_exceeds_yield(self) -> None:
        result = calculate_rebalance_economics(
            wallet_available="0.2",
            liquidity_target="0.1",
            stats={"history_days": 7, "transfer_sum": "0.07"},
            strategy=STRATEGY,
            approve_gas_asset="0.001",
            supply_gas_asset="0.001",
            withdraw_gas_asset="0.001",
            prices_available=True,
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["action"], "hold")

    def test_supply_is_blocked_without_prices(self) -> None:
        result = calculate_rebalance_economics(
            wallet_available="1",
            liquidity_target="0.1",
            stats={"history_days": 7, "transfer_sum": "0"},
            strategy=STRATEGY,
            approve_gas_asset="0",
            supply_gas_asset="0",
            withdraw_gas_asset="0",
            prices_available=False,
        )

        self.assertFalse(result["allowed"])
        self.assertIn("converted", result["reason"])

    def test_supply_is_allowed_when_yield_clearly_exceeds_gas(self) -> None:
        result = calculate_rebalance_economics(
            wallet_available="1",
            liquidity_target="0.1",
            stats={"history_days": 7, "transfer_sum": "0"},
            strategy=STRATEGY,
            approve_gas_asset="0.000001",
            supply_gas_asset="0.000001",
            withdraw_gas_asset="0.000001",
            prices_available=True,
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["action"], "supply_to_aave")


if __name__ == "__main__":
    unittest.main()
