from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.treasury_policy import asset_amount, fmt, percentile_linear


ROOT_DIR = Path(__file__).resolve().parents[4]
USER_DIR = ROOT_DIR / "data" / "users" / "demo"
TRANSFER_MEMORY_PATH = USER_DIR / "transfer_memory.json"
PLANNED_OUTFLOWS_PATH = USER_DIR / "planned_outflows.json"

VALID_TRANSFER_CLASSIFICATIONS = {"one_off", "recurring"}


def classify_transfer_events(
    events: list[dict[str, Any]],
    override_updates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    overrides = load_transfer_memory().get("classifications", {})
    overrides = {**overrides, **(override_updates or {})}
    records = [_transfer_record(event, overrides) for event in events]
    unclassified = [record for record in records if record["classification"] is None]

    threshold: Decimal | None = None
    if len(unclassified) >= 5:
        amounts = [asset_amount(record["amount"]) for record in unclassified]
        median = percentile_linear(amounts, Decimal("0.5"))
        q1 = percentile_linear(amounts, Decimal("0.25"))
        q3 = percentile_linear(amounts, Decimal("0.75"))
        threshold = max(q3 + Decimal("1.5") * (q3 - q1), Decimal("3") * median)
        for record in unclassified:
            amount = asset_amount(record["amount"])
            if amount > threshold:
                record.update(
                    {
                        "classification": "one_off",
                        "source": "automatic",
                        "reason": (
                            f"Amount exceeds robust outlier threshold {fmt(threshold)} WBTC "
                            "(max of Q3 + 1.5 x IQR and 3 x median)."
                        ),
                    }
                )

    for record in records:
        if record["classification"] is None:
            record.update(
                {
                    "classification": "recurring",
                    "source": "automatic",
                    "reason": (
                        "Kept as recurring because fewer than 5 unclassified transfers are available."
                        if len(unclassified) < 5
                        else "Amount is within the robust recurring range."
                    ),
                }
            )

    recurring = [
        asset_amount(record["amount"])
        for record in records
        if record["classification"] == "recurring"
    ]
    one_off = [
        asset_amount(record["amount"])
        for record in records
        if record["classification"] == "one_off"
    ]
    return {
        "recurring_amounts": recurring,
        "one_off_amounts": one_off,
        "recurring_transfer_sum": fmt(sum(recurring, Decimal("0"))),
        "recurring_p90_transfer_amount": fmt(
            percentile_linear(recurring, Decimal("0.9"))
        ),
        "one_off_transfer_sum": fmt(sum(one_off, Decimal("0"))),
        "excluded_transfer_count": len(one_off),
        "transfer_classifications": records,
        "automatic_outlier_threshold": fmt(threshold) if threshold is not None else None,
    }


def stable_transfer_id(event: dict[str, Any]) -> str:
    event_id = str(event.get("event_id") or "").strip()
    if event_id:
        return event_id
    fingerprint_input = "|".join(
        [
            str(event.get("created_at") or ""),
            str(event.get("amount") or ""),
            str(event.get("destination") or "").lower(),
        ]
    )
    return f"legacy-{hashlib.sha256(fingerprint_input.encode('utf-8')).hexdigest()[:16]}"


def load_transfer_memory() -> dict[str, Any]:
    payload = _load_json(TRANSFER_MEMORY_PATH, {})
    if not isinstance(payload, dict):
        return {"classifications": {}}
    classifications = payload.get("classifications")
    return {
        **payload,
        "classifications": classifications if isinstance(classifications, dict) else {},
    }


def set_transfer_classification(
    *,
    event_id: str,
    classification: str,
    reason: str = "Confirmed by user.",
) -> dict[str, Any]:
    if classification not in VALID_TRANSFER_CLASSIFICATIONS:
        raise ValueError(f"Unsupported transfer classification: {classification}")
    memory = load_transfer_memory()
    memory["classifications"][event_id] = {
        "classification": classification,
        "reason": reason,
        "updated_at": _now_iso(),
    }
    _save_json(TRANSFER_MEMORY_PATH, memory)
    return memory["classifications"][event_id]


def list_active_planned_outflows(
    *,
    now: datetime | None = None,
    horizon_days: int | None = None,
) -> list[dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    horizon_end = None
    if horizon_days is not None:
        from datetime import timedelta

        horizon_end = current + timedelta(days=max(1, horizon_days))

    active: list[dict[str, Any]] = []
    for item in load_planned_outflows():
        try:
            due_at = _parse_time(item.get("due_at"))
        except (TypeError, ValueError):
            continue
        if item.get("status", "active") != "active" or due_at < current:
            continue
        if horizon_end is not None and due_at > horizon_end:
            continue
        active.append(item)
    return active


def planned_outflow_sum(
    *,
    now: datetime | None = None,
    horizon_days: int | None = None,
    additional: list[dict[str, Any]] | None = None,
) -> str:
    items = list_active_planned_outflows(now=now, horizon_days=horizon_days)
    if additional:
        current = now or datetime.now(timezone.utc)
        for item in additional:
            try:
                due_at = _parse_time(item.get("due_at"))
            except (TypeError, ValueError):
                continue
            if due_at < current:
                continue
            if horizon_days is not None:
                from datetime import timedelta

                if due_at > current + timedelta(days=max(1, horizon_days)):
                    continue
            items.append(item)
    return fmt(sum((asset_amount(item.get("amount", "0")) for item in items), Decimal("0")))


def add_planned_outflow(
    *,
    amount: str,
    due_at: str,
    description: str = "",
    source: str = "user_confirmed",
) -> dict[str, Any]:
    parsed_due = _parse_time(due_at)
    item = {
        "planned_outflow_id": f"outflow-{uuid.uuid4().hex[:12]}",
        "amount": fmt(asset_amount(amount)),
        "due_at": parsed_due.isoformat(),
        "description": description,
        "source": source,
        "status": "active",
        "created_at": _now_iso(),
    }
    items = load_planned_outflows()
    items.append(item)
    _save_json(PLANNED_OUTFLOWS_PATH, items)
    return item


def load_planned_outflows() -> list[dict[str, Any]]:
    payload = _load_json(PLANNED_OUTFLOWS_PATH, [])
    return payload if isinstance(payload, list) else []


def _transfer_record(
    event: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    event_id = stable_transfer_id(event)
    override = overrides.get(event_id)
    classification = None
    source = None
    reason = None
    if isinstance(override, dict) and override.get("classification") in VALID_TRANSFER_CLASSIFICATIONS:
        classification = override["classification"]
        source = "user"
        reason = str(override.get("reason") or "Confirmed by user.")
    return {
        "event_id": event_id,
        "amount": fmt(asset_amount(event.get("amount", "0"))),
        "created_at": event.get("created_at"),
        "destination": event.get("destination"),
        "classification": classification,
        "source": source,
        "reason": reason,
    }


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as source_file:
            return json.load(source_file)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as target_file:
        json.dump(payload, target_file, ensure_ascii=False, indent=2)
        target_file.write("\n")


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
