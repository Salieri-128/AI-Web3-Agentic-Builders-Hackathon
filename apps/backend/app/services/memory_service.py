from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[4]
USER_DIR = ROOT_DIR / "data" / "users" / "demo"
PROFILE_PATH = USER_DIR / "profile.json"
LEGACY_PROFILE_PATH = ROOT_DIR / "data" / "users" / "profile.json"
MEMORY_PATH = USER_DIR / "memory.md"
PROPOSALS_PATH = USER_DIR / "memory_proposals.json"
EVENTS_PATH = USER_DIR / "events.jsonl"

DEFAULT_PROFILE: dict[str, Any] = {
    "user_preferences": {
        "risk_level": "balanced",
        "liquidity_floor": None,
        "liquidity_horizon_days": None,
    },
    "transaction_habits": {
        "prefers_low_gas": False,
    },
}

RISK_ALIASES = {
    "保守": "conservative",
    "conservative": "conservative",
    "稳健": "conservative",
    "平衡": "balanced",
    "均衡": "balanced",
    "balanced": "balanced",
    "激进": "aggressive",
    "aggressive": "aggressive",
}


def ensure_profile_exists() -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    if PROFILE_PATH.exists():
        return
    if LEGACY_PROFILE_PATH.exists():
        try:
            with LEGACY_PROFILE_PATH.open("r", encoding="utf-8") as profile_file:
                save_profile(_sanitize_profile(json.load(profile_file)))
                return
        except (OSError, json.JSONDecodeError):
            pass
    save_profile(copy.deepcopy(DEFAULT_PROFILE))


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    with PROFILE_PATH.open("r", encoding="utf-8") as profile_file:
        return _sanitize_profile(json.load(profile_file))


def save_profile(profile: dict[str, Any]) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_profile(profile)
    with PROFILE_PATH.open("w", encoding="utf-8") as profile_file:
        json.dump(sanitized, profile_file, ensure_ascii=False, indent=2)
        profile_file.write("\n")
    _write_memory_summary(sanitized)


def is_memory_loaded() -> bool:
    try:
        load_profile()
        return True
    except (OSError, json.JSONDecodeError):
        return False


def parse_profile_patch(message: str) -> dict[str, Any]:
    normalized = message.lower()
    patch: dict[str, Any] = {}

    for keyword, risk_level in RISK_ALIASES.items():
        if keyword in normalized or keyword in message:
            patch["risk_level"] = risk_level
            break

    floor_match = re.search(
        r"(?:至少|最低|最少|minimum|at least)\s*(?:保留|留出|keep|reserve)?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:wbtc|btc)",
        normalized,
        re.IGNORECASE,
    )
    if not floor_match:
        floor_match = re.search(
            r"(?:流动性(?:下限|底线)|liquidity\s*floor)\s*(?:为|是|=|:)?\s*"
            r"([0-9]+(?:\.[0-9]+)?)",
            normalized,
            re.IGNORECASE,
        )
    if floor_match:
        patch["liquidity_floor"] = _normalize_amount(floor_match.group(1))

    horizon_match = re.search(
        r"(?:覆盖|保留|流动性周期|liquidity\s*horizon|cover)\s*"
        r"([0-9]+)\s*(?:天|day|days)",
        normalized,
        re.IGNORECASE,
    )
    if horizon_match:
        patch["liquidity_horizon_days"] = max(1, min(90, int(horizon_match.group(1))))

    if any(keyword in normalized for keyword in ("低 gas", "low gas", "减少 gas", "节省 gas", "省 gas")):
        patch["prefers_low_gas"] = True
    if any(keyword in normalized for keyword in ("不考虑 gas", "不在意 gas", "disable low gas", "关闭低 gas")):
        patch["prefers_low_gas"] = False

    if any(keyword in normalized for keyword in ("清除最低保留", "取消最低保留", "clear liquidity floor")):
        patch["liquidity_floor"] = None
    if any(keyword in normalized for keyword in ("清除流动性周期", "取消流动性周期", "clear liquidity horizon")):
        patch["liquidity_horizon_days"] = None

    return patch


def build_profile_proposal(message: str) -> dict[str, Any] | None:
    patch = parse_profile_patch(message)
    if not patch:
        return None

    current = load_profile()
    proposed = _apply_patch(current, patch)
    changes = _build_changes(current, proposed, patch)
    if not changes:
        return None

    return {
        "proposal_id": f"memory-{uuid.uuid4().hex[:12]}",
        "status": "pending_confirmation",
        "message": message,
        "patch": patch,
        "changes": changes,
        "before_profile": current,
        "proposed_profile": proposed,
        "created_at": _now_iso(),
    }


def store_profile_proposal(proposal: dict[str, Any], impact: dict[str, Any]) -> dict[str, Any]:
    stored = copy.deepcopy(proposal)
    stored["liquidity_impact"] = impact
    proposals = _load_proposals()
    proposals[stored["proposal_id"]] = stored
    _save_proposals(proposals)
    _append_event(
        {
            "type": "memory_proposal_created",
            "proposal_id": stored["proposal_id"],
            "patch": stored["patch"],
            "liquidity_impact": impact,
        }
    )
    return stored


def confirm_profile_proposal(proposal_id: str) -> dict[str, Any]:
    proposals = _load_proposals()
    proposal = proposals.get(proposal_id)
    if not proposal:
        raise KeyError(f"Unknown memory proposal: {proposal_id}")
    if proposal.get("status") != "pending_confirmation":
        return proposal

    current = load_profile()
    updated = _apply_patch(current, proposal.get("patch", {}))
    save_profile(updated)
    proposal["status"] = "applied"
    proposal["applied_at"] = _now_iso()
    proposal["profile"] = updated
    proposals[proposal_id] = proposal
    _save_proposals(proposals)
    _append_event(
        {
            "type": "memory_proposal_applied",
            "proposal_id": proposal_id,
            "patch": proposal.get("patch", {}),
        }
    )
    return proposal


def reject_profile_proposal(proposal_id: str) -> dict[str, Any]:
    proposals = _load_proposals()
    proposal = proposals.get(proposal_id)
    if not proposal:
        raise KeyError(f"Unknown memory proposal: {proposal_id}")
    if proposal.get("status") == "pending_confirmation":
        proposal["status"] = "rejected"
        proposal["rejected_at"] = _now_iso()
        proposals[proposal_id] = proposal
        _save_proposals(proposals)
        _append_event({"type": "memory_proposal_rejected", "proposal_id": proposal_id})
    return proposal


def _sanitize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(DEFAULT_PROFILE)
    preferences = profile.get("user_preferences", {}) if isinstance(profile, dict) else {}
    habits = profile.get("transaction_habits", {}) if isinstance(profile, dict) else {}

    risk_level = str(preferences.get("risk_level", "balanced")).lower()
    sanitized["user_preferences"]["risk_level"] = (
        risk_level if risk_level in {"conservative", "balanced", "aggressive"} else "balanced"
    )
    sanitized["user_preferences"]["liquidity_floor"] = _optional_amount(
        preferences.get("liquidity_floor")
    )
    sanitized["user_preferences"]["liquidity_horizon_days"] = _optional_days(
        preferences.get("liquidity_horizon_days")
    )
    sanitized["transaction_habits"]["prefers_low_gas"] = bool(
        habits.get("prefers_low_gas", False)
    )
    return sanitized


def _apply_patch(profile: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    updated = _sanitize_profile(profile)
    preferences = updated["user_preferences"]
    habits = updated["transaction_habits"]
    for key in ("risk_level", "liquidity_floor", "liquidity_horizon_days"):
        if key in patch:
            preferences[key] = patch[key]
    if "prefers_low_gas" in patch:
        habits["prefers_low_gas"] = bool(patch["prefers_low_gas"])
    return _sanitize_profile(updated)


def _build_changes(
    current: dict[str, Any],
    proposed: dict[str, Any],
    patch: dict[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in patch:
        section = "transaction_habits" if field == "prefers_low_gas" else "user_preferences"
        before = current[section].get(field)
        after = proposed[section].get(field)
        if before != after:
            changes.append({"field": field, "before": before, "after": after})
    return changes


def _write_memory_summary(profile: dict[str, Any]) -> None:
    preferences = profile["user_preferences"]
    habits = profile["transaction_habits"]
    lines = [
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
    MEMORY_PATH.write_text("\n".join(lines), encoding="utf-8")


def _load_proposals() -> dict[str, dict[str, Any]]:
    if not PROPOSALS_PATH.exists():
        return {}
    try:
        with PROPOSALS_PATH.open("r", encoding="utf-8") as proposals_file:
            payload = json.load(proposals_file)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_proposals(proposals: dict[str, dict[str, Any]]) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    with PROPOSALS_PATH.open("w", encoding="utf-8") as proposals_file:
        json.dump(proposals, proposals_file, ensure_ascii=False, indent=2)
        proposals_file.write("\n")


def _append_event(event: dict[str, Any]) -> None:
    USER_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as events_file:
        events_file.write(json.dumps({"created_at": _now_iso(), **event}, ensure_ascii=False) + "\n")


def _optional_amount(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return _normalize_amount(str(value))
    except ValueError:
        return None


def _normalize_amount(value: str) -> str:
    amount = float(value)
    if amount < 0:
        raise ValueError("Liquidity floor cannot be negative.")
    return f"{amount:.8f}".rstrip("0").rstrip(".") or "0"


def _optional_days(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(1, min(90, int(value)))
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
