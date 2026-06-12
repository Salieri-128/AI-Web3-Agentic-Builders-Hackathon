#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
USER_DIR = ROOT_DIR / "data" / "users" / "demo"
LEGACY_PROFILE_PATH = ROOT_DIR / "data" / "users" / "profile.json"

sys.path.insert(0, str(BACKEND_DIR))

from app.services.memory_service import DEFAULT_PROFILE  # noqa: E402
from app.services.treasury_service import DEFAULT_STATE  # noqa: E402


def reset_demo_state(root_dir: Path = ROOT_DIR) -> list[Path]:
    user_dir = root_dir / "data" / "users" / "demo"
    legacy_profile_path = root_dir / "data" / "users" / "profile.json"
    user_dir.mkdir(parents=True, exist_ok=True)

    profile = copy.deepcopy(DEFAULT_PROFILE)
    state = copy.deepcopy(DEFAULT_STATE)
    state["updated_at"] = None

    payloads: dict[str, Any] = {
        "profile.json": profile,
        "wallet_state.json": state,
        "memory_proposals.json": {},
        "transfer_memory.json": {"classifications": {}},
        "planned_outflows.json": [],
        "planning_sessions.json": {},
        "treasury_plans.json": {},
        "transfer_classification_proposals.json": {},
    }

    written: list[Path] = []
    for filename, payload in payloads.items():
        path = user_dir / filename
        _write_json(path, payload)
        written.append(path)

    events_path = user_dir / "events.jsonl"
    events_path.write_text("", encoding="utf-8")
    written.append(events_path)

    memory_path = user_dir / "memory.md"
    memory_path.write_text(_memory_summary(profile), encoding="utf-8")
    written.append(memory_path)

    if legacy_profile_path.exists():
        legacy_profile_path.unlink()

    return written


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _memory_summary(profile: dict[str, Any]) -> str:
    preferences = profile["user_preferences"]
    habits = profile["transaction_habits"]
    return "\n".join(
        [
            "# Treasury Liquidity Memory",
            "",
            f"- Risk level: {preferences['risk_level']}",
            f"- Liquidity floor: {preferences['liquidity_floor'] or 'not set'} WBTC",
            f"- Liquidity horizon: {preferences['liquidity_horizon_days'] or 'system default'} days",
            f"- Prefer fewer low-value rebalances: {'yes' if habits['prefers_low_gas'] else 'no'}",
            "",
            "These preferences affect liquidity recommendations only. CAW Pact controls execution permission.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reset local demo profile, strategy state, history, proposals, and planner sessions. "
            "This does not revoke remote CAW Pacts or move on-chain funds."
        )
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive deletion of the current local demo state.",
    )
    args = parser.parse_args()

    if not args.yes:
        parser.error("Pass --yes after confirming remote CAW Pacts and on-chain positions separately.")

    written = reset_demo_state()
    print("Local demo state reset:")
    for path in written:
        print(f"- {path.relative_to(ROOT_DIR)}")
    print("- removed data/users/profile.json" if not LEGACY_PROFILE_PATH.exists() else "")
    print("Remote CAW Pacts and on-chain wallet/Aave balances were not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
