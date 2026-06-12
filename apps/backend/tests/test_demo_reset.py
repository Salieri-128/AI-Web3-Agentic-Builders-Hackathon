from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.reset_demo_state import reset_demo_state


class DemoResetTests(unittest.TestCase):
    def test_reset_clears_local_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            user_dir = root / "data" / "users" / "demo"
            user_dir.mkdir(parents=True)
            (user_dir / "wallet_state.json").write_text(
                json.dumps({"pacts": [{"pact_id": "old"}], "pending_transfer": {"id": "old"}}),
                encoding="utf-8",
            )
            (user_dir / "events.jsonl").write_text('{"type":"old"}\n', encoding="utf-8")
            legacy_profile = root / "data" / "users" / "profile.json"
            legacy_profile.write_text('{"old":true}\n', encoding="utf-8")

            reset_demo_state(root)

            state = json.loads((user_dir / "wallet_state.json").read_text(encoding="utf-8"))
            profile = json.loads((user_dir / "profile.json").read_text(encoding="utf-8"))
            transfer_memory = json.loads(
                (user_dir / "transfer_memory.json").read_text(encoding="utf-8")
            )

            self.assertEqual(state["pacts"], [])
            self.assertIsNone(state["pending_transfer"])
            self.assertEqual(profile["user_preferences"]["risk_level"], "balanced")
            self.assertIsNone(profile["user_preferences"]["liquidity_floor"])
            self.assertFalse(profile["transaction_habits"]["prefers_low_gas"])
            self.assertEqual(transfer_memory, {"classifications": {}})
            self.assertEqual((user_dir / "events.jsonl").read_text(encoding="utf-8"), "")
            self.assertFalse(legacy_profile.exists())


if __name__ == "__main__":
    unittest.main()
