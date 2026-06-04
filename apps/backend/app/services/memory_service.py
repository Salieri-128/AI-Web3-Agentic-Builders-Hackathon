from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[4]
PROFILE_PATH = ROOT_DIR / "data" / "users" / "profile.json"

DEFAULT_PROFILE: dict[str, Any] = {
    "user_preferences": {
        "cash_buffer_usdc": None,
        "risk_level": "conservative",
        "preferred_assets": [],
        "blocked_assets": [],
        "whitelisted_addresses": [],
    },
    "transaction_habits": {
        "prefers_low_gas": True,
        "requires_confirmation_before_execution": True,
    },
    "notes": [],
}


def ensure_profile_exists() -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PROFILE_PATH.exists():
        save_profile(copy.deepcopy(DEFAULT_PROFILE))


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    with PROFILE_PATH.open("r", encoding="utf-8") as profile_file:
        profile = json.load(profile_file)
    return _merge_defaults(profile)


def save_profile(profile: dict[str, Any]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROFILE_PATH.open("w", encoding="utf-8") as profile_file:
        json.dump(profile, profile_file, ensure_ascii=False, indent=2)
        profile_file.write("\n")


def append_note(note: str) -> None:
    profile = load_profile()
    notes = profile.setdefault("notes", [])
    if note not in notes:
        notes.append(note)
    save_profile(profile)


def is_memory_loaded() -> bool:
    try:
        load_profile()
        return True
    except (OSError, json.JSONDecodeError):
        return False


def update_memory_from_message(message: str) -> tuple[dict[str, Any], list[str]]:
    profile = load_profile()
    normalized = message.lower()
    updates: list[str] = []

    user_preferences = profile.setdefault("user_preferences", {})
    transaction_habits = profile.setdefault("transaction_habits", {})
    notes = profile.setdefault("notes", [])

    if "保守" in message or "conservative" in normalized:
        user_preferences["risk_level"] = "conservative"
        updates.append("risk_level=conservative")

    if "激进" in message or "aggressive" in normalized:
        user_preferences["risk_level"] = "aggressive"
        updates.append("risk_level=aggressive")

    if "低 gas" in normalized or "low gas" in normalized:
        transaction_habits["prefers_low_gas"] = True
        updates.append("prefers_low_gas=true")

    should_save_note = any(
        keyword in normalized or keyword in message
        for keyword in ("记住", "偏好", "profile", "preference", "以后")
    )
    if should_save_note and message not in notes:
        notes.append(message)
        updates.append("notes+=message")

    save_profile(profile)
    return profile, updates


def _merge_defaults(profile: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(DEFAULT_PROFILE)
    for section, value in profile.items():
        if isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section].update(value)
        else:
            merged[section] = value
    return merged
