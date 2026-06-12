from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.services.llm_service import (
    explain_treasury_plan,
    interpret_treasury_goal,
    is_llm_configured,
)
from app.services.memory_service import (
    apply_profile_patch,
    build_profile_proposal_from_patch,
    load_profile,
    parse_profile_patch,
    preview_profile_patch,
)
from app.services.treasury_memory_service import (
    add_planned_outflow,
    set_transfer_classification,
)
from app.services.treasury_policy import asset_amount, fmt
from app.services.treasury_service import (
    get_transfer_stats,
    preview_treasury_scenarios,
)


ROOT_DIR = Path(__file__).resolve().parents[4]
USER_DIR = ROOT_DIR / "data" / "users" / "demo"
PLANNING_SESSIONS_PATH = USER_DIR / "planning_sessions.json"
TREASURY_PLANS_PATH = USER_DIR / "treasury_plans.json"
TRANSFER_PROPOSALS_PATH = USER_DIR / "transfer_classification_proposals.json"

SESSION_TTL_MINUTES = 30
RISK_SCENARIOS = [
    ("robust", "稳健方案", "conservative"),
    ("balanced", "平衡方案", "balanced"),
    ("yield_focused", "收益优先", "aggressive"),
]


async def plan_treasury_message(
    *,
    message: str,
    planning_session_id: str | None = None,
) -> dict[str, Any] | None:
    profile = load_profile()
    session = _get_active_session(planning_session_id)
    recent_transfers = get_transfer_stats().get("transfer_classifications", [])
    raw = await _interpret_with_fallback(
        message=message,
        profile=profile,
        session=session,
        recent_transfers=recent_transfers,
    )
    parsed = _sanitize_interpretation(raw)
    if session:
        parsed = _merge_interpretations(session.get("draft", {}), parsed)
    if parsed["intent"] == "none":
        return None

    session_id = planning_session_id or f"planning-{uuid.uuid4().hex[:12]}"
    parsed = _enforce_backend_clarifications(message, parsed)

    if parsed["needs_clarification"]:
        clarification = {
            "planning_session_id": session_id,
            "question": parsed["clarification_question"],
            "missing_information": parsed["missing_information"],
            "confidence": parsed["confidence"],
        }
        _save_session(session_id, parsed, "awaiting_clarification")
        return {
            "handled": True,
            "llm_used": bool(raw.get("llm_used")),
            "planning_session_id": session_id,
            "clarification": clarification,
            "reply": clarification["question"],
        }

    if parsed["intent"] == "transfer_classification":
        result = _build_transfer_classification_proposal(
            parsed["transfer_classification"],
            message=message,
            planning_session_id=session_id,
        )
        if result.get("clarification"):
            _save_session(session_id, parsed, "awaiting_clarification")
        else:
            _save_session(session_id, parsed, "proposal_created")
        return {
            "handled": True,
            "llm_used": bool(raw.get("llm_used")),
            "planning_session_id": session_id,
            **result,
        }

    profile_patch = parsed["profile_patch"]
    planned_outflows = parsed["planned_outflows"]
    is_complex = parsed["complex_goal"] or (
        len(profile_patch) + len(planned_outflows) > 1
    )
    if not is_complex:
        draft = build_profile_proposal_from_patch(message, profile_patch)
        if draft is None and planned_outflows:
            is_complex = True
        elif draft is None:
            return None
        else:
            _save_session(session_id, parsed, "proposal_created")
            return {
                "handled": True,
                "llm_used": bool(raw.get("llm_used")),
                "planning_session_id": session_id,
                "memory_draft": draft,
            }

    treasury_plan = await _build_treasury_plan(
        message=message,
        profile_patch=profile_patch,
        planned_outflows=planned_outflows,
        planning_session_id=session_id,
    )
    explanation = _deterministic_plan_explanation(treasury_plan)
    explanation_llm_used = False
    if is_llm_configured():
        try:
            llm_explanation = await explain_treasury_plan(
                message=message,
                treasury_plan=treasury_plan,
            )
            if llm_explanation:
                explanation = _plain_text_explanation(llm_explanation)
                explanation_llm_used = True
        except Exception:
            pass
    treasury_plan["explanation"] = explanation
    _store_record(TREASURY_PLANS_PATH, treasury_plan["plan_id"], treasury_plan)
    _save_session(session_id, parsed, "plan_created")
    return {
        "handled": True,
        "llm_used": bool(raw.get("llm_used") or explanation_llm_used),
        "planning_session_id": session_id,
        "treasury_plan": treasury_plan,
        "reply": explanation,
    }


def select_treasury_plan(plan_id: str, scenario_id: str) -> dict[str, Any]:
    plans = _load_records(TREASURY_PLANS_PATH)
    plan = plans.get(plan_id)
    if not plan:
        raise KeyError(f"Unknown treasury plan: {plan_id}")
    if plan.get("status") != "pending_selection":
        return plan
    scenario = next(
        (
            item
            for item in plan.get("scenarios", [])
            if item.get("scenario_id") == scenario_id
        ),
        None,
    )
    if not scenario:
        raise KeyError(f"Unknown treasury scenario: {scenario_id}")

    profile = apply_profile_patch(scenario.get("profile_patch", {}))
    applied_outflows = [
        add_planned_outflow(
            amount=item["amount"],
            due_at=item["due_at"],
            description=item.get("description", ""),
            source="treasury_plan",
        )
        for item in scenario.get("planned_outflows", [])
    ]
    plan["status"] = "selected"
    plan["selected_scenario_id"] = scenario_id
    plan["selected_at"] = _now_iso()
    plan["profile"] = profile
    plan["applied_planned_outflows"] = applied_outflows
    plans[plan_id] = plan
    _save_records(TREASURY_PLANS_PATH, plans)
    return plan


def confirm_transfer_classification(proposal_id: str) -> dict[str, Any]:
    proposals = _load_records(TRANSFER_PROPOSALS_PATH)
    proposal = proposals.get(proposal_id)
    if not proposal:
        raise KeyError(f"Unknown transfer classification proposal: {proposal_id}")
    if proposal.get("status") != "pending_confirmation":
        return proposal
    set_transfer_classification(
        event_id=proposal["event"]["event_id"],
        classification=proposal["classification"],
        reason=f"Confirmed from chat: {proposal.get('message', '')}",
    )
    proposal["status"] = "applied"
    proposal["applied_at"] = _now_iso()
    proposals[proposal_id] = proposal
    _save_records(TRANSFER_PROPOSALS_PATH, proposals)
    return proposal


def reject_transfer_classification(proposal_id: str) -> dict[str, Any]:
    proposals = _load_records(TRANSFER_PROPOSALS_PATH)
    proposal = proposals.get(proposal_id)
    if not proposal:
        raise KeyError(f"Unknown transfer classification proposal: {proposal_id}")
    if proposal.get("status") == "pending_confirmation":
        proposal["status"] = "rejected"
        proposal["rejected_at"] = _now_iso()
        proposals[proposal_id] = proposal
        _save_records(TRANSFER_PROPOSALS_PATH, proposals)
    return proposal


async def _interpret_with_fallback(
    *,
    message: str,
    profile: dict[str, Any],
    session: dict[str, Any] | None,
    recent_transfers: list[dict[str, Any]],
) -> dict[str, Any]:
    if is_llm_configured():
        try:
            result = await interpret_treasury_goal(
                message=message,
                profile=profile,
                planning_context=session or {},
                recent_transfers=recent_transfers[-12:],
            )
            if isinstance(result, dict):
                if result.get("intent") == "none":
                    fallback = _fallback_interpretation(message)
                    if fallback.get("intent") != "none":
                        fallback["llm_used"] = True
                        return fallback
                return result
        except Exception:
            pass
    return _fallback_interpretation(message)


def _fallback_interpretation(message: str) -> dict[str, Any]:
    normalized = message.lower()
    classification = None
    if any(
        phrase in normalized
        for phrase in ("一次性", "one-off", "one off", "偶发", "不会再发生")
    ):
        classification = "one_off"
    elif any(
        phrase in normalized
        for phrase in ("经常发生", "经常性", "recurring", "规律性", "以后会经常")
    ):
        classification = "recurring"
    if classification:
        amount_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:wbtc|btc)", normalized)
        destination_match = re.search(r"0x[a-f0-9]{40}", normalized)
        return {
            "intent": "transfer_classification",
            "profile_patch": {},
            "planned_outflows": [],
            "transfer_classification": {
                "classification": classification,
                "amount": amount_match.group(1) if amount_match else None,
                "destination": destination_match.group(0) if destination_match else None,
                "time_hint": (
                    "latest"
                    if any(word in normalized for word in ("刚才", "最近", "latest", "last"))
                    else None
                ),
            },
            "confidence": 0.75,
            "missing_information": [],
            "needs_clarification": False,
            "clarification_question": "",
            "complex_goal": False,
            "llm_used": False,
        }

    profile_patch = parse_profile_patch(message)
    planned_outflows: list[dict[str, Any]] = []
    outflow_context = re.search(
        r"(?:支出|付款|付一笔|支付|outflow|expense|bill)[^0-9]{0,20}"
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:wbtc|btc)",
        normalized,
    )
    if not outflow_context:
        outflow_context = re.search(
            r"([0-9]+(?:\.[0-9]+)?)\s*(?:wbtc|btc)[^。,.]{0,20}"
            r"(?:支出|付款|支付|outflow|expense|bill)",
            normalized,
        )
    if outflow_context:
        due_days = _extract_due_days(normalized)
        planned_outflows.append(
            {
                "amount": outflow_context.group(1),
                "due_in_days": due_days,
                "description": "User-described future outflow",
            }
        )
    intent = "treasury_goal" if profile_patch or planned_outflows else "none"
    return {
        "intent": intent,
        "profile_patch": profile_patch,
        "planned_outflows": planned_outflows,
        "transfer_classification": {},
        "confidence": 0.7 if intent != "none" else 0,
        "missing_information": [],
        "needs_clarification": bool(planned_outflows and due_days is None),
        "clarification_question": (
            "这笔计划支出预计哪一天发生？"
            if planned_outflows and due_days is None
            else ""
        ),
        "complex_goal": len(profile_patch) + len(planned_outflows) > 1,
        "llm_used": False,
    }


def _sanitize_interpretation(raw: dict[str, Any]) -> dict[str, Any]:
    intent = (
        raw.get("intent")
        if raw.get("intent") in {"treasury_goal", "transfer_classification", "none"}
        else "none"
    )
    raw_patch = raw.get("profile_patch")
    raw_patch = raw_patch if isinstance(raw_patch, dict) else {}
    patch: dict[str, Any] = {}
    if raw_patch.get("risk_level") in {
        "conservative",
        "balanced",
        "aggressive",
    }:
        patch["risk_level"] = raw_patch["risk_level"]
    if "liquidity_floor" in raw_patch:
        amount = _positive_or_zero_amount(raw_patch.get("liquidity_floor"))
        if amount is not None:
            patch["liquidity_floor"] = amount
    if "liquidity_horizon_days" in raw_patch:
        try:
            patch["liquidity_horizon_days"] = max(
                1, min(90, int(raw_patch["liquidity_horizon_days"]))
            )
        except (TypeError, ValueError):
            pass
    if isinstance(raw_patch.get("prefers_low_gas"), bool):
        patch["prefers_low_gas"] = raw_patch["prefers_low_gas"]

    planned = []
    raw_planned = raw.get("planned_outflows")
    if isinstance(raw_planned, list):
        for item in raw_planned[:5]:
            normalized = _normalize_planned_outflow(item)
            if normalized:
                planned.append(normalized)

    raw_classification = raw.get("transfer_classification")
    raw_classification = (
        raw_classification if isinstance(raw_classification, dict) else {}
    )
    classification: dict[str, Any] = {}
    if raw_classification.get("classification") in {"one_off", "recurring"}:
        classification["classification"] = raw_classification["classification"]
    amount = _positive_or_zero_amount(raw_classification.get("amount"))
    if amount not in (None, "0"):
        classification["amount"] = amount
    destination = str(raw_classification.get("destination") or "").strip()
    if re.fullmatch(r"0x[a-fA-F0-9]{40}", destination):
        classification["destination"] = destination
    time_hint = str(raw_classification.get("time_hint") or "").strip()
    if time_hint:
        classification["time_hint"] = time_hint

    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    missing = raw.get("missing_information")
    missing = [str(value)[:80] for value in missing[:5]] if isinstance(missing, list) else []
    question = str(raw.get("clarification_question") or "").strip()[:300]
    return {
        "intent": intent,
        "profile_patch": patch,
        "planned_outflows": planned,
        "transfer_classification": classification,
        "confidence": confidence,
        "missing_information": missing,
        "needs_clarification": bool(raw.get("needs_clarification")),
        "clarification_question": question,
        "complex_goal": bool(raw.get("complex_goal")),
    }


def _enforce_backend_clarifications(
    message: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    result = dict(parsed)
    if result["intent"] == "treasury_goal":
        missing_due = any(not item.get("due_at") for item in result["planned_outflows"])
        risk_only = set(result["profile_patch"]) == {"risk_level"}
        soft_risk_language = any(
            phrase in message.lower()
            for phrase in ("一点", "a bit", "稍微", "更激进", "更保守")
        )
        if missing_due:
            result["needs_clarification"] = True
            result["missing_information"] = ["planned_outflow_due_at"]
            result["clarification_question"] = "这笔计划支出预计哪一天发生？"
        elif risk_only and soft_risk_language:
            result["needs_clarification"] = True
            result["missing_information"] = ["risk_adjustment_priority"]
            result["clarification_question"] = (
                "你更希望降低最低保留比例，还是缩短流动性覆盖周期？"
            )
    elif result["intent"] == "transfer_classification":
        if not result["transfer_classification"].get("classification"):
            result["needs_clarification"] = True
            result["missing_information"] = ["transfer_classification"]
            result["clarification_question"] = "这笔转账应标记为一次性，还是经常性？"
    if result["needs_clarification"] and not result["clarification_question"]:
        result["clarification_question"] = "请补充一下你希望调整的具体资金目标。"
    return result


async def _build_treasury_plan(
    *,
    message: str,
    profile_patch: dict[str, Any],
    planned_outflows: list[dict[str, Any]],
    planning_session_id: str,
) -> dict[str, Any]:
    scenario_inputs = []
    for scenario_id, label, risk_level in RISK_SCENARIOS:
        scenario_patch = {**profile_patch, "risk_level": risk_level}
        scenario_inputs.append(
            {
                "scenario_id": scenario_id,
                "label": label,
                "profile_patch": scenario_patch,
                "profile": preview_profile_patch(scenario_patch),
                "planned_outflows": planned_outflows,
            }
        )
    scenarios = await preview_treasury_scenarios(scenario_inputs)
    return {
        "plan_id": f"plan-{uuid.uuid4().hex[:12]}",
        "planning_session_id": planning_session_id,
        "status": "pending_selection",
        "message": message,
        "created_at": _now_iso(),
        "scenarios": scenarios,
        "safety_boundary": (
            "Selecting a scenario updates profile and planned-outflow inputs only. "
            "It does not modify or approve any CAW Pact and does not execute a transaction."
        ),
    }


def _build_transfer_classification_proposal(
    intent: dict[str, Any],
    *,
    message: str,
    planning_session_id: str,
) -> dict[str, Any]:
    stats = get_transfer_stats()
    candidates = list(stats.get("transfer_classifications", []))
    amount = intent.get("amount")
    destination = str(intent.get("destination") or "")
    if amount:
        candidates = [item for item in candidates if item.get("amount") == amount]
    if destination:
        candidates = [
            item
            for item in candidates
            if str(item.get("destination") or "").lower() == destination.lower()
        ]
    if intent.get("time_hint") == "latest" and candidates:
        candidates = [max(candidates, key=lambda item: str(item.get("created_at") or ""))]
    elif intent.get("time_hint"):
        try:
            hinted_time = _parse_time(intent["time_hint"])
            candidates = [
                item
                for item in candidates
                if abs((_parse_time(item.get("created_at")) - hinted_time).total_seconds())
                <= 15 * 60
            ]
        except (TypeError, ValueError):
            candidates = []

    if len(candidates) != 1:
        question = (
            "没有找到匹配的历史转账，请补充金额、时间或地址。"
            if not candidates
            else "匹配到多笔转账，请补充时间或收款地址以便唯一确认。"
        )
        return {
            "clarification": {
                "planning_session_id": planning_session_id,
                "question": question,
                "missing_information": ["unique_transfer_match"],
                "confidence": 0.5,
                "candidates": candidates[:5],
            },
            "reply": question,
        }

    event = candidates[0]
    classification = intent["classification"]
    override = {
        event["event_id"]: {
            "classification": classification,
            "reason": "Pending user confirmation.",
        }
    }
    after_stats = get_transfer_stats(classification_overrides=override)
    proposal = {
        "proposal_id": f"classification-{uuid.uuid4().hex[:12]}",
        "planning_session_id": planning_session_id,
        "status": "pending_confirmation",
        "message": message,
        "classification": classification,
        "event": event,
        "statistics_before": _compact_strategy_stats(stats),
        "statistics_after": _compact_strategy_stats(after_stats),
        "created_at": _now_iso(),
        "safety_boundary": (
            "This proposal only changes how history informs liquidity strategy. "
            "The original audit event remains unchanged and no Pact or transfer is created."
        ),
    }
    _store_record(
        TRANSFER_PROPOSALS_PATH,
        proposal["proposal_id"],
        proposal,
    )
    label = "一次性" if classification == "one_off" else "经常性"
    return {
        "transfer_classification_proposal": proposal,
        "reply": (
            f"我匹配到 {event['amount']} WBTC 的转账，并准备标记为{label}。"
            "确认后只会更新流动性模型，原始审计记录不会改变。"
        ),
    }


def _compact_strategy_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "recurring_transfer_sum": stats.get("recurring_transfer_sum", "0"),
        "recurring_p90_transfer_amount": stats.get(
            "recurring_p90_transfer_amount", "0"
        ),
        "one_off_transfer_sum": stats.get("one_off_transfer_sum", "0"),
        "excluded_transfer_count": stats.get("excluded_transfer_count", 0),
    }


def _deterministic_plan_explanation(plan: dict[str, Any]) -> str:
    scenarios = plan.get("scenarios", [])
    if not scenarios:
        return "后端没有生成可用方案。"
    parts = []
    for scenario in scenarios:
        after = scenario["after"]
        parts.append(
            f"{scenario['label']}保留 {after['recommended_liquidity']} WBTC，"
            f"Aave 目标 {after['target_yield_balance']} WBTC"
        )
    excluded = scenarios[0].get("recurring_statistics", {}).get(
        "excluded_transfer_count", 0
    )
    suffix = (
        f" 历史模型已排除 {excluded} 笔一次性大额。"
        if excluded
        else ""
    )
    return "；".join(parts) + "。" + suffix + " 选择方案不会修改 CAW Pact 或执行交易。"


def _merge_interpretations(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    if not previous:
        return current
    intent = (
        current["intent"]
        if current["intent"] != "none"
        else previous.get("intent", "none")
    )
    return {
        **previous,
        **current,
        "intent": intent,
        "profile_patch": {
            **previous.get("profile_patch", {}),
            **current.get("profile_patch", {}),
        },
        "planned_outflows": (
            current["planned_outflows"]
            if current.get("planned_outflows")
            else previous.get("planned_outflows", [])
        ),
        "transfer_classification": {
            **previous.get("transfer_classification", {}),
            **current.get("transfer_classification", {}),
        },
        "needs_clarification": current.get("needs_clarification", False),
    }


def _normalize_planned_outflow(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    amount = _positive_or_zero_amount(item.get("amount"))
    if amount in (None, "0"):
        return None
    due_at = None
    if item.get("due_at"):
        try:
            due_at = _parse_time(item["due_at"])
        except (TypeError, ValueError):
            pass
    if due_at is None and item.get("due_in_days") is not None:
        try:
            days = max(1, min(365, int(item["due_in_days"])))
            due_at = datetime.now(timezone.utc) + timedelta(days=days)
        except (TypeError, ValueError):
            pass
    if due_at is not None and due_at <= datetime.now(timezone.utc):
        due_at = None
    result = {
        "amount": amount,
        "description": str(item.get("description") or "")[:160],
    }
    if due_at is not None:
        result["due_at"] = due_at.isoformat()
    return result


def _positive_or_zero_amount(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        amount = asset_amount(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return fmt(amount) if amount >= Decimal("0") else None


def _extract_due_days(normalized: str) -> int | None:
    day_match = re.search(r"(?:未来|接下来|in)\s*([0-9]+)\s*(?:天|days?)", normalized)
    if day_match:
        return max(1, min(365, int(day_match.group(1))))
    if "明天" in normalized or "tomorrow" in normalized:
        return 1
    if "下周" in normalized or "next week" in normalized:
        return 7
    return None


def _get_active_session(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    session = _load_records(PLANNING_SESSIONS_PATH).get(session_id)
    if not session:
        return None
    try:
        updated_at = _parse_time(session.get("updated_at"))
    except (TypeError, ValueError):
        return None
    if datetime.now(timezone.utc) - updated_at > timedelta(minutes=SESSION_TTL_MINUTES):
        return None
    return session


def _save_session(session_id: str, draft: dict[str, Any], status: str) -> None:
    sessions = _load_records(PLANNING_SESSIONS_PATH)
    sessions[session_id] = {
        "planning_session_id": session_id,
        "status": status,
        "draft": draft,
        "updated_at": _now_iso(),
    }
    _save_records(PLANNING_SESSIONS_PATH, sessions)


def _store_record(path: Path, key: str, value: dict[str, Any]) -> None:
    records = _load_records(path)
    records[key] = value
    _save_records(path, records)


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as source_file:
            payload = json.load(source_file)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_records(path: Path, records: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as target_file:
        json.dump(records, target_file, ensure_ascii=False, indent=2)
        target_file.write("\n")


def _parse_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain_text_explanation(value: str) -> str:
    return (
        value.replace("**", "")
        .replace("###", "")
        .replace("##", "")
        .replace("# ", "")
        .strip()
    )
