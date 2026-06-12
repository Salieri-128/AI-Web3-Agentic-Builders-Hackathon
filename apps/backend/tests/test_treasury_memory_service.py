from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.services import treasury_memory_service


def transfer(amount: str, index: int = 0) -> dict[str, str]:
    return {
        "type": "external_transfer",
        "amount": amount,
        "destination": f"0x{index:040x}",
        "created_at": f"2026-06-{index + 1:02d}T10:00:00+00:00",
    }


class TreasuryMemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.patches = [
            patch.object(treasury_memory_service, "USER_DIR", root),
            patch.object(
                treasury_memory_service,
                "TRANSFER_MEMORY_PATH",
                root / "transfer_memory.json",
            ),
            patch.object(
                treasury_memory_service,
                "PLANNED_OUTFLOWS_PATH",
                root / "planned_outflows.json",
            ),
        ]
        for current in self.patches:
            current.start()

    def tearDown(self) -> None:
        for current in reversed(self.patches):
            current.stop()
        self.temp_dir.cleanup()

    def test_demo_outlier_is_excluded_from_recurring_model(self) -> None:
        events = [transfer("0.01", index) for index in range(5)]
        events.extend([transfer("0.03", 5), transfer("0.3", 6)])

        result = treasury_memory_service.classify_transfer_events(events)

        self.assertEqual(result["excluded_transfer_count"], 1)
        self.assertEqual(result["one_off_transfer_sum"], "0.3")
        self.assertEqual(result["recurring_transfer_sum"], "0.08")
        self.assertEqual(result["recurring_p90_transfer_amount"], "0.02")
        excluded = [
            item
            for item in result["transfer_classifications"]
            if item["classification"] == "one_off"
        ]
        self.assertEqual(excluded[0]["amount"], "0.3")

    def test_fewer_than_five_samples_stays_conservative(self) -> None:
        result = treasury_memory_service.classify_transfer_events(
            [transfer("0.01"), transfer("0.3", 1)]
        )

        self.assertEqual(result["excluded_transfer_count"], 0)
        self.assertEqual(result["recurring_transfer_sum"], "0.31")

    def test_iqr_zero_still_excludes_clear_outlier(self) -> None:
        events = [transfer("0.01", index) for index in range(5)]
        events.append(transfer("0.3", 5))

        result = treasury_memory_service.classify_transfer_events(events)

        self.assertEqual(result["excluded_transfer_count"], 1)
        self.assertEqual(result["automatic_outlier_threshold"], "0.03")

    def test_repeated_large_transfers_are_not_outliers(self) -> None:
        result = treasury_memory_service.classify_transfer_events(
            [transfer("0.3", index) for index in range(6)]
        )

        self.assertEqual(result["excluded_transfer_count"], 0)
        self.assertEqual(result["recurring_p90_transfer_amount"], "0.3")

    def test_normal_distribution_keeps_all_transfers(self) -> None:
        result = treasury_memory_service.classify_transfer_events(
            [
                transfer(amount, index)
                for index, amount in enumerate(
                    ["0.01", "0.012", "0.014", "0.016", "0.018", "0.02"]
                )
            ]
        )

        self.assertEqual(result["excluded_transfer_count"], 0)
        self.assertEqual(result["recurring_transfer_sum"], "0.09")

    def test_user_classification_overrides_automatic_result(self) -> None:
        events = [transfer("0.01", index) for index in range(5)]
        large = transfer("0.3", 5)
        events.append(large)
        event_id = treasury_memory_service.stable_transfer_id(large)
        treasury_memory_service.set_transfer_classification(
            event_id=event_id,
            classification="recurring",
        )

        result = treasury_memory_service.classify_transfer_events(events)

        classified = next(
            item
            for item in result["transfer_classifications"]
            if item["event_id"] == event_id
        )
        self.assertEqual(classified["classification"], "recurring")
        self.assertEqual(classified["source"], "user")
        self.assertEqual(result["excluded_transfer_count"], 0)

    def test_legacy_fingerprint_is_stable(self) -> None:
        event = transfer("0.03", 2)

        self.assertEqual(
            treasury_memory_service.stable_transfer_id(event),
            treasury_memory_service.stable_transfer_id(dict(event)),
        )
        self.assertTrue(
            treasury_memory_service.stable_transfer_id(event).startswith("legacy-")
        )

    def test_planned_outflow_expires_after_due_time(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=timezone.utc)
        treasury_memory_service.add_planned_outflow(
            amount="0.2",
            due_at=(now + timedelta(days=3)).isoformat(),
            description="Vendor payment",
        )

        self.assertEqual(
            treasury_memory_service.planned_outflow_sum(now=now, horizon_days=7),
            "0.2",
        )
        self.assertEqual(
            treasury_memory_service.planned_outflow_sum(
                now=now + timedelta(days=4),
                horizon_days=7,
            ),
            "0",
        )

    def test_planned_outflow_outside_horizon_is_not_reserved_yet(self) -> None:
        now = datetime(2026, 6, 12, tzinfo=timezone.utc)
        treasury_memory_service.add_planned_outflow(
            amount="0.2",
            due_at=(now + timedelta(days=10)).isoformat(),
        )

        self.assertEqual(
            treasury_memory_service.planned_outflow_sum(now=now, horizon_days=7),
            "0",
        )
        self.assertEqual(
            treasury_memory_service.planned_outflow_sum(now=now, horizon_days=14),
            "0.2",
        )


if __name__ == "__main__":
    unittest.main()
