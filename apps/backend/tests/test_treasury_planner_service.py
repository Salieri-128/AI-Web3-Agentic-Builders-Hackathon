from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services import treasury_planner_service


PROFILE = {
    "user_preferences": {
        "risk_level": "balanced",
        "liquidity_floor": None,
        "liquidity_horizon_days": None,
    },
    "transaction_habits": {"prefers_low_gas": False},
}

TRANSFER = {
    "event_id": "event-large",
    "amount": "0.3",
    "created_at": "2026-06-11T10:00:00+00:00",
    "destination": "0x1111111111111111111111111111111111111111",
    "classification": "one_off",
    "source": "automatic",
    "reason": "outlier",
}


class TreasuryPlannerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.path_patches = [
            patch.object(treasury_planner_service, "USER_DIR", root),
            patch.object(
                treasury_planner_service,
                "PLANNING_SESSIONS_PATH",
                root / "planning_sessions.json",
            ),
            patch.object(
                treasury_planner_service,
                "TREASURY_PLANS_PATH",
                root / "treasury_plans.json",
            ),
            patch.object(
                treasury_planner_service,
                "TRANSFER_PROPOSALS_PATH",
                root / "classification_proposals.json",
            ),
        ]
        for current in self.path_patches:
            current.start()

    async def asyncTearDown(self) -> None:
        for current in reversed(self.path_patches):
            current.stop()
        self.temp_dir.cleanup()

    async def test_mock_llm_complex_goal_creates_backend_scenarios(self) -> None:
        llm_result = {
            "intent": "treasury_goal",
            "profile_patch": {
                "risk_level": "balanced",
                "liquidity_horizon_days": 10,
                "prefers_low_gas": True,
                "risk_multiplier": "99",
                "pact_limit": "1000",
            },
            "planned_outflows": [
                {
                    "amount": "0.2",
                    "due_in_days": 7,
                    "description": "Supplier payment",
                }
            ],
            "confidence": 0.95,
            "missing_information": [],
            "needs_clarification": False,
            "clarification_question": "",
            "complex_goal": True,
            "llm_used": True,
        }

        async def preview(inputs):
            return [
                {
                    "scenario_id": item["scenario_id"],
                    "label": item["label"],
                    "profile_patch": item["profile_patch"],
                    "planned_outflows": item["planned_outflows"],
                    "before": {
                        "recommended_liquidity": "0.1",
                        "target_yield_balance": "0.9",
                        "candidates": {},
                        "effective_strategy": {},
                    },
                    "after": {
                        "recommended_liquidity": "0.2",
                        "target_yield_balance": "0.8",
                        "candidates": {},
                        "effective_strategy": {},
                    },
                    "recurring_statistics": {
                        "recurring_transfer_sum": "0.08",
                        "recurring_p90_transfer_amount": "0.02",
                        "excluded_transfer_count": 1,
                    },
                    "expected_action": {
                        "action": "withdraw_from_aave",
                        "amount": "0.1",
                    },
                    "pact_gap": {
                        "active_internal_limit": "0",
                        "additional_limit_required": "0.1",
                        "requires_new_pact": True,
                    },
                }
                for item in inputs
            ]

        with (
            patch.object(treasury_planner_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_planner_service,
                "get_transfer_stats",
                return_value={"transfer_classifications": [TRANSFER]},
            ),
            patch.object(treasury_planner_service, "is_llm_configured", return_value=True),
            patch.object(
                treasury_planner_service,
                "interpret_treasury_goal",
                AsyncMock(return_value=llm_result),
            ),
            patch.object(
                treasury_planner_service,
                "preview_profile_patch",
                side_effect=lambda current: {
                    **PROFILE,
                    "scenario_patch": current,
                },
            ),
            patch.object(
                treasury_planner_service,
                "preview_treasury_scenarios",
                AsyncMock(side_effect=preview),
            ),
            patch.object(
                treasury_planner_service,
                "explain_treasury_plan",
                AsyncMock(return_value="LLM explanation from backend numbers."),
            ),
        ):
            result = await treasury_planner_service.plan_treasury_message(
                message="下周要付款 0.2 WBTC，提高收益但不要频繁操作。"
            )

        self.assertIsNotNone(result)
        plan = result["treasury_plan"]
        self.assertEqual(len(plan["scenarios"]), 3)
        for scenario in plan["scenarios"]:
            self.assertNotIn("risk_multiplier", scenario["profile_patch"])
            self.assertNotIn("pact_limit", scenario["profile_patch"])
        self.assertEqual(result["reply"], "LLM explanation from backend numbers.")

    async def test_soft_risk_request_asks_for_clarification(self) -> None:
        with (
            patch.object(treasury_planner_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_planner_service,
                "get_transfer_stats",
                return_value={"transfer_classifications": []},
            ),
            patch.object(treasury_planner_service, "is_llm_configured", return_value=False),
        ):
            result = await treasury_planner_service.plan_treasury_message(
                message="策略更激进一点"
            )

        self.assertIsNotNone(result["clarification"])
        self.assertIn("降低最低保留比例", result["reply"])
        self.assertTrue(result["planning_session_id"].startswith("planning-"))

    async def test_unique_transfer_match_creates_confirmation_proposal(self) -> None:
        before = {
            "transfer_classifications": [TRANSFER],
            "recurring_transfer_sum": "0.08",
            "recurring_p90_transfer_amount": "0.02",
            "one_off_transfer_sum": "0.3",
            "excluded_transfer_count": 1,
        }
        after = {
            **before,
            "recurring_transfer_sum": "0.38",
            "recurring_p90_transfer_amount": "0.138",
            "one_off_transfer_sum": "0",
            "excluded_transfer_count": 0,
        }
        with (
            patch.object(treasury_planner_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_planner_service,
                "get_transfer_stats",
                side_effect=[before, before, after],
            ),
            patch.object(treasury_planner_service, "is_llm_configured", return_value=False),
        ):
            result = await treasury_planner_service.plan_treasury_message(
                message="刚才 0.3 WBTC 这类转账以后会经常发生"
            )

        proposal = result["transfer_classification_proposal"]
        self.assertEqual(proposal["event"]["event_id"], "event-large")
        self.assertEqual(proposal["classification"], "recurring")
        self.assertEqual(
            proposal["statistics_after"]["recurring_transfer_sum"],
            "0.38",
        )

    async def test_ambiguous_transfer_match_returns_clarification(self) -> None:
        duplicate = {**TRANSFER, "event_id": "event-large-2"}
        stats = {"transfer_classifications": [TRANSFER, duplicate]}
        with (
            patch.object(treasury_planner_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_planner_service,
                "get_transfer_stats",
                side_effect=[stats, stats],
            ),
            patch.object(treasury_planner_service, "is_llm_configured", return_value=False),
        ):
            result = await treasury_planner_service.plan_treasury_message(
                message="0.3 WBTC 是一次性的"
            )

        self.assertIsNotNone(result["clarification"])
        self.assertIn("匹配到多笔", result["reply"])

    async def test_time_hint_disambiguates_same_amount(self) -> None:
        earlier = {
            **TRANSFER,
            "event_id": "event-earlier",
            "created_at": "2026-06-10T10:00:00+00:00",
        }
        later = {
            **TRANSFER,
            "event_id": "event-later",
            "created_at": "2026-06-11T10:00:00+00:00",
        }
        before = {
            "transfer_classifications": [earlier, later],
            "recurring_transfer_sum": "0.08",
            "recurring_p90_transfer_amount": "0.02",
            "one_off_transfer_sum": "0.6",
            "excluded_transfer_count": 2,
        }
        llm_result = {
            "intent": "transfer_classification",
            "profile_patch": {},
            "planned_outflows": [],
            "transfer_classification": {
                "classification": "recurring",
                "amount": "0.3",
                "time_hint": "2026-06-11T10:05:00+00:00",
            },
            "confidence": 0.9,
            "missing_information": [],
            "needs_clarification": False,
            "clarification_question": "",
            "complex_goal": False,
            "llm_used": True,
        }
        with (
            patch.object(treasury_planner_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_planner_service,
                "get_transfer_stats",
                side_effect=[before, before, before],
            ),
            patch.object(treasury_planner_service, "is_llm_configured", return_value=True),
            patch.object(
                treasury_planner_service,
                "interpret_treasury_goal",
                AsyncMock(return_value=llm_result),
            ),
        ):
            result = await treasury_planner_service.plan_treasury_message(
                message="把 6 月 11 日那笔 0.3 WBTC 改成经常性"
            )

        self.assertEqual(
            result["transfer_classification_proposal"]["event"]["event_id"],
            "event-later",
        )

    async def test_invalid_llm_output_falls_back_to_regex_parser(self) -> None:
        with (
            patch.object(treasury_planner_service, "load_profile", return_value=PROFILE),
            patch.object(
                treasury_planner_service,
                "get_transfer_stats",
                return_value={"transfer_classifications": []},
            ),
            patch.object(treasury_planner_service, "is_llm_configured", return_value=True),
            patch.object(
                treasury_planner_service,
                "interpret_treasury_goal",
                AsyncMock(side_effect=ValueError("invalid JSON")),
            ),
            patch.object(
                treasury_planner_service,
                "build_profile_proposal_from_patch",
                return_value={"proposal_id": "memory-fallback"},
            ),
        ):
            result = await treasury_planner_service.plan_treasury_message(
                message="改成保守策略"
            )

        self.assertEqual(result["memory_draft"]["proposal_id"], "memory-fallback")
        self.assertFalse(result["llm_used"])


if __name__ == "__main__":
    unittest.main()
