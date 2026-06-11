from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import memory_service


class MemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.user_dir = root / "demo"
        self.patches = [
            patch.object(memory_service, "USER_DIR", self.user_dir),
            patch.object(memory_service, "PROFILE_PATH", self.user_dir / "profile.json"),
            patch.object(memory_service, "LEGACY_PROFILE_PATH", root / "legacy-profile.json"),
            patch.object(memory_service, "MEMORY_PATH", self.user_dir / "memory.md"),
            patch.object(memory_service, "PROPOSALS_PATH", self.user_dir / "memory_proposals.json"),
            patch.object(memory_service, "EVENTS_PATH", self.user_dir / "events.jsonl"),
        ]
        for current_patch in self.patches:
            current_patch.start()

    def tearDown(self) -> None:
        for current_patch in reversed(self.patches):
            current_patch.stop()
        self.temp_dir.cleanup()

    def test_profile_change_waits_for_confirmation(self) -> None:
        initial = memory_service.load_profile()
        proposal = memory_service.build_profile_proposal(
            "以后保守一点，至少保留 0.2 WBTC，并尽量减少 Gas"
        )

        self.assertIsNotNone(proposal)
        self.assertEqual(memory_service.load_profile(), initial)
        self.assertEqual(proposal["proposed_profile"]["user_preferences"]["risk_level"], "conservative")
        self.assertEqual(proposal["proposed_profile"]["user_preferences"]["liquidity_floor"], "0.2")
        self.assertTrue(
            proposal["proposed_profile"]["transaction_habits"]["prefers_low_gas"]
        )

        stored = memory_service.store_profile_proposal(proposal, {"changed": True})
        memory_service.confirm_profile_proposal(stored["proposal_id"])
        applied = memory_service.load_profile()

        self.assertEqual(applied["user_preferences"]["risk_level"], "conservative")
        self.assertEqual(applied["user_preferences"]["liquidity_floor"], "0.2")
        self.assertTrue(applied["transaction_habits"]["prefers_low_gas"])
        self.assertTrue(memory_service.MEMORY_PATH.exists())

    def test_profile_query_does_not_create_a_proposal(self) -> None:
        self.assertIsNone(memory_service.build_profile_proposal("查看我最近的资金管理偏好"))
        self.assertFalse(memory_service.PROPOSALS_PATH.exists())

    def test_profile_persistence_contains_no_authorization_fields(self) -> None:
        memory_service.save_profile(
            {
                "user_preferences": {
                    "risk_level": "aggressive",
                    "liquidity_floor": "0.1",
                    "whitelisted_addresses": ["0x123"],
                },
                "transaction_habits": {
                    "prefers_low_gas": False,
                    "requires_confirmation_before_execution": False,
                },
            }
        )

        payload = json.loads(memory_service.PROFILE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("whitelisted_addresses", payload["user_preferences"])
        self.assertNotIn(
            "requires_confirmation_before_execution",
            payload["transaction_habits"],
        )


if __name__ == "__main__":
    unittest.main()
