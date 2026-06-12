from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import agent_service, treasury_service


PROFILE = {
    "user_preferences": {
        "risk_level": "balanced",
        "liquidity_floor": None,
        "liquidity_horizon_days": None,
    },
    "transaction_habits": {"prefers_low_gas": False},
}


class WalletModeTests(unittest.TestCase):
    def test_simple_wallet_actions_skip_treasury_planner(self) -> None:
        cases = [
            ("查看钱包余额", "wallet_status"),
            ("我要收款地址", "wallet_status"),
            (
                "转账 0.01 WBTC 到 0x1111111111111111111111111111111111111111",
                "treasury_transfer",
            ),
        ]
        for message, action in cases:
            normalized = message.lower()
            self.assertEqual(agent_service._infer_action(message, normalized), action)
            self.assertFalse(
                agent_service._should_use_treasury_planner(
                    message=message,
                    normalized=normalized,
                    inferred_action=action,
                    planning_session_id=None,
                )
            )

    def test_explicit_optimization_goal_uses_planner(self) -> None:
        message = "下周有一笔 0.2 WBTC 支出，我想提高收益"
        normalized = message.lower()
        action = agent_service._infer_action(message, normalized)

        self.assertTrue(
            agent_service._should_use_treasury_planner(
                message=message,
                normalized=normalized,
                inferred_action=action,
                planning_session_id=None,
            )
        )

    def test_classification_attention_only_returns_material_impact(self) -> None:
        state = {
            "strategy": dict(treasury_service.DEFAULT_STRATEGY),
            "pacts": [],
        }
        balances = {
            "total": "1",
            "wallet": "1",
            "wallet_available": "1",
            "aave_withdrawable": "0",
        }
        current_stats = {
            "history_days": 30,
            "recurring_transfer_sum": "0.08",
            "recurring_p90_transfer_amount": "0.02",
            "transfer_classifications": [
                {
                    "event_id": "event-large",
                    "amount": "0.3",
                    "classification": "one_off",
                    "source": "automatic",
                    "reason": "robust outlier",
                }
            ],
        }
        alternate_stats = {
            **current_stats,
            "recurring_transfer_sum": "0.38",
            "recurring_p90_transfer_amount": "0.138",
        }
        with (
            patch.object(treasury_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_service,
                "planned_outflow_sum",
                return_value="0",
            ),
            patch.object(
                treasury_service,
                "get_transfer_stats",
                return_value=alternate_stats,
            ),
        ):
            current = treasury_service._calculate_liquidity(
                state,
                current_stats,
                balances,
            )
            attention = treasury_service._build_classification_attention(
                state=state,
                balances=balances,
                stats=current_stats,
                current_liquidity=current,
            )

        self.assertIsNotNone(attention)
        self.assertEqual(attention["event"]["event_id"], "event-large")
        self.assertGreaterEqual(
            float(attention["impact"]["liquidity_delta"]),
            0.01,
        )

    def test_classification_attention_stays_silent_when_floor_dominates(self) -> None:
        profile = {
            **PROFILE,
            "user_preferences": {
                **PROFILE["user_preferences"],
                "liquidity_floor": "0.65",
            },
        }
        state = {
            "strategy": dict(treasury_service.DEFAULT_STRATEGY),
            "pacts": [],
        }
        balances = {
            "total": "1",
            "wallet": "1",
            "wallet_available": "1",
            "aave_withdrawable": "0",
        }
        current_stats = {
            "history_days": 30,
            "recurring_transfer_sum": "0.08",
            "recurring_p90_transfer_amount": "0.02",
            "transfer_classifications": [
                {
                    "event_id": "event-large",
                    "amount": "0.3",
                    "classification": "one_off",
                    "source": "automatic",
                    "reason": "robust outlier",
                }
            ],
        }
        alternate_stats = {
            **current_stats,
            "recurring_transfer_sum": "0.38",
            "recurring_p90_transfer_amount": "0.138",
        }
        with (
            patch.object(treasury_service, "load_profile", return_value=profile),
            patch.object(
                treasury_service,
                "planned_outflow_sum",
                return_value="0",
            ),
            patch.object(
                treasury_service,
                "get_transfer_stats",
                return_value=alternate_stats,
            ),
        ):
            current = treasury_service._calculate_liquidity(
                state,
                current_stats,
                balances,
            )
            attention = treasury_service._build_classification_attention(
                state=state,
                balances=balances,
                stats=current_stats,
                current_liquidity=current,
            )

        self.assertIsNone(attention)


if __name__ == "__main__":
    unittest.main()
