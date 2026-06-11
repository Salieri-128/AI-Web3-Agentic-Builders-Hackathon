from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services import treasury_service


ACTIVE_TRANSFER_PACT = {
    "pact_id": "local-transfer",
    "caw_pact_id": "caw-transfer",
    "pact_type": "external_transfer",
    "status": "active",
    "scope": {
        "destination_address": "0x1111111111111111111111111111111111111111",
        "max_single_amount": "1",
        "weekly_amount_cap": "10",
        "weekly_tx_cap": 10,
    },
}

ACTIVE_AAVE_PACT = {
    "pact_id": "local-aave",
    "caw_pact_id": "caw-aave",
    "pact_type": "internal_agent_rebalance",
    "status": "active",
    "scope": {"max_amount": "1"},
}


class TransferFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.state_path = root / "wallet_state.json"
        self.events_path = root / "events.jsonl"
        self.path_patches = [
            patch.object(treasury_service, "TREASURY_DIR", root),
            patch.object(treasury_service, "TREASURY_STATE_PATH", self.state_path),
            patch.object(treasury_service, "TREASURY_EVENTS_PATH", self.events_path),
        ]
        for current in self.path_patches:
            current.start()

    async def asyncTearDown(self) -> None:
        for current in reversed(self.path_patches):
            current.stop()
        self.temp_dir.cleanup()

    def save_state(self, *, wallet_stage: str = "checking_balance", include_aave: bool = True) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        state["pacts"] = [copy.deepcopy(ACTIVE_TRANSFER_PACT)]
        if include_aave:
            state["pacts"].append(copy.deepcopy(ACTIVE_AAVE_PACT))
        state["pending_transfer"] = {
            "id": "pending-1",
            "stage": wallet_stage,
            "status": wallet_stage,
            "destination": ACTIVE_TRANSFER_PACT["scope"]["destination_address"],
            "amount": "0.05",
            "asset": "WBTC",
            "transfer_pact_id": "caw-transfer",
        }
        treasury_service._save_state(state)

    async def test_wallet_balance_sends_without_aave_withdraw(self) -> None:
        self.save_state()
        transfer = AsyncMock(return_value={"status": "ok", "gas_fee": "0.001 SETH"})
        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda state: state)),
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "0.2", "aave_balance": "0.8"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
            patch.object(
                treasury_service,
                "estimate_wbtc_transfer_fee",
                AsyncMock(return_value={"status": "ok", "fee_amount": "0.001", "token_id": "SETH"}),
            ),
            patch.object(treasury_service, "_request_completed", AsyncMock(return_value=False)),
            patch.object(treasury_service, "execute_wbtc_transfer", transfer),
            patch.object(treasury_service, "get_treasury_state", AsyncMock(return_value={"status": "ok"})),
        ):
            result = await treasury_service.execute_ready_pending_transfer()

        self.assertEqual(result["status"], "completed")
        transfer.assert_awaited_once()

    async def test_low_wallet_withdraws_before_transfer(self) -> None:
        self.save_state()
        withdraw = AsyncMock(return_value={"status": "ok"})
        transfer = AsyncMock(return_value={"status": "ok"})
        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda state: state)),
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "0.02", "aave_balance": "0.98"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
            patch.object(
                treasury_service,
                "estimate_aave_withdraw_fee",
                AsyncMock(
                    return_value={
                        "status": "ok",
                        "token_id": "SETH",
                        "fee_amount": "0.001",
                        "estimate": {},
                    }
                ),
            ),
            patch.object(
                treasury_service,
                "estimate_wbtc_transfer_fee",
                AsyncMock(return_value={"status": "ok", "fee_amount": "0.001", "token_id": "SETH"}),
            ),
            patch.object(
                treasury_service,
                "_load_asset_prices",
                AsyncMock(return_value={"status": "ok", "SETH_USD": "2000", "WBTC_USD": "100000"}),
            ),
            patch.object(treasury_service, "_request_completed", AsyncMock(return_value=False)),
            patch.object(treasury_service, "execute_aave_withdraw", withdraw),
            patch.object(treasury_service, "execute_wbtc_transfer", transfer),
            patch.object(treasury_service, "get_treasury_state", AsyncMock(return_value={"status": "ok"})),
        ):
            result = await treasury_service.execute_ready_pending_transfer()

        self.assertEqual(result["status"], "completed")
        withdraw.assert_awaited_once()
        transfer.assert_awaited_once()
        self.assertGreater(float(withdraw.await_args.kwargs["amount"]), 0.03)

    async def test_low_wallet_calculates_withdraw_before_requesting_aave_pact(self) -> None:
        self.save_state(include_aave=False)
        submitted_pact = {
            **copy.deepcopy(ACTIVE_AAVE_PACT),
            "status": "pending_owner_approval",
        }
        submit = AsyncMock(return_value=submitted_pact)
        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda state: state)),
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "0.02", "aave_balance": "0.98"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
            patch.object(
                treasury_service,
                "estimate_aave_withdraw_fee",
                AsyncMock(
                    return_value={
                        "status": "ok",
                        "token_id": "SETH",
                        "fee_amount": "0.001",
                        "estimate": {},
                    }
                ),
            ),
            patch.object(
                treasury_service,
                "estimate_wbtc_transfer_fee",
                AsyncMock(return_value={"status": "ok", "fee_amount": "0.001", "token_id": "SETH"}),
            ),
            patch.object(
                treasury_service,
                "_load_asset_prices",
                AsyncMock(return_value={"status": "ok", "SETH_USD": "2000", "WBTC_USD": "100000"}),
            ),
            patch.object(treasury_service, "submit_internal_rebalance_pact", submit),
            patch.object(treasury_service, "get_treasury_state", AsyncMock(return_value={"status": "ok"})),
        ):
            result = await treasury_service.execute_ready_pending_transfer()

        self.assertEqual(result["status"], "waiting_aave_pact")
        self.assertGreater(float(result["pending_transfer"]["withdraw_amount"]), 0.03)
        submit.assert_awaited_once()

    async def test_unknown_transfer_pact_id_submits_real_destination_pact(self) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        state["pending_transfer"] = {
            "id": "pending-invalid-pact",
            "stage": "checking_balance",
            "status": "checking_balance",
            "destination": ACTIVE_TRANSFER_PACT["scope"]["destination_address"],
            "amount": "0.3",
            "asset": "WBTC",
            "transfer_pact_id": "None",
            "created_at": "2026-06-11T10:00:00+00:00",
            "updated_at": "2026-06-11T10:00:00+00:00",
        }
        treasury_service._save_state(state)
        proposal = {
            **copy.deepcopy(ACTIVE_TRANSFER_PACT),
            "status": "pending_owner_approval",
            "pending_execution": {"stage": "waiting_transfer_pact"},
        }
        create_pact = AsyncMock(return_value=proposal)
        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda current: current)),
            patch.object(treasury_service, "create_external_transfer_pact", create_pact),
            patch.object(treasury_service, "get_treasury_state", AsyncMock(return_value={"status": "ok"})),
        ):
            result = await treasury_service.execute_ready_pending_transfer()

        self.assertEqual(result["status"], "pact_required")
        create_pact.assert_awaited_once_with(
            ACTIVE_TRANSFER_PACT["scope"]["destination_address"],
            "0.3",
        )

    async def test_total_balance_shortfall_fails_before_execution(self) -> None:
        self.save_state()
        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda state: state)),
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "0.01", "aave_balance": "0.01"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
            patch.object(treasury_service, "get_treasury_state", AsyncMock(return_value={"status": "ok"})),
        ):
            result = await treasury_service.execute_ready_pending_transfer()

        self.assertEqual(result["status"], "insufficient_total_balance")

    async def test_completed_request_id_is_not_submitted_twice(self) -> None:
        self.save_state(wallet_stage="transferring")
        state = treasury_service._load_state()
        state["pending_transfer"]["transfer_request_id"] = "existing-request"
        state["pending_transfer"]["transfer_execution"] = {"status": "ok"}
        treasury_service._save_state(state)
        transfer = AsyncMock(return_value={"status": "ok"})
        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda current: current)),
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "0.2", "aave_balance": "0.8"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
            patch.object(
                treasury_service,
                "estimate_wbtc_transfer_fee",
                AsyncMock(return_value={"status": "ok", "fee_amount": "0.001", "token_id": "SETH"}),
            ),
            patch.object(treasury_service, "_request_completed", AsyncMock(return_value=True)),
            patch.object(treasury_service, "execute_wbtc_transfer", transfer),
            patch.object(treasury_service, "get_treasury_state", AsyncMock(return_value={"status": "ok"})),
        ):
            result = await treasury_service.execute_ready_pending_transfer()

        self.assertEqual(result["status"], "completed")
        transfer.assert_not_awaited()

    async def test_completed_pending_request_does_not_block_next_transfer(self) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        pact = copy.deepcopy(ACTIVE_TRANSFER_PACT)
        pact["scope"]["max_single_amount"] = "1"
        pact["scope"]["weekly_amount_cap"] = "10"
        state["pacts"] = [pact]
        state["pending_transfer"] = {
            "id": "completed-on-chain",
            "stage": "transferring",
            "status": "transferring",
            "destination": pact["scope"]["destination_address"],
            "amount": "0.03",
            "asset": "WBTC",
            "transfer_pact_id": pact["caw_pact_id"],
            "transfer_request_id": "completed-request",
            "created_at": "2026-06-11T09:57:03+00:00",
            "updated_at": "2026-06-11T09:57:34+00:00",
        }
        treasury_service._save_state(state)
        execute_pending = AsyncMock(return_value={"status": "accepted"})

        with (
            patch.object(treasury_service, "refresh_pact_statuses", AsyncMock(side_effect=lambda current: current)),
            patch.object(treasury_service, "_request_completed", AsyncMock(return_value=True)),
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "1", "aave_balance": "0"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
            patch.object(treasury_service, "execute_ready_pending_transfer", execute_pending),
        ):
            result = await treasury_service.send_asset(
                destination=pact["scope"]["destination_address"],
                amount="0.2",
            )

        self.assertEqual(result["status"], "accepted")
        execute_pending.assert_awaited_once()
        saved = treasury_service._load_state()
        self.assertEqual(saved["pending_transfer"]["amount"], "0.2")
        self.assertEqual(saved["pending_transfer"]["stage"], "checking_balance")
        self.assertNotEqual(saved["pending_transfer"]["id"], "completed-on-chain")

    async def test_audit_event_recovers_pending_when_caw_status_is_unavailable(self) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        state["pending_transfer"] = {
            "id": "completed-in-audit",
            "stage": "transferring",
            "status": "transferring",
            "destination": ACTIVE_TRANSFER_PACT["scope"]["destination_address"],
            "amount": "0.03",
            "asset": "WBTC",
            "transfer_pact_id": ACTIVE_TRANSFER_PACT["caw_pact_id"],
            "transfer_request_id": "audit-request",
            "created_at": "2026-06-11T09:57:03+00:00",
            "updated_at": "2026-06-11T09:57:34+00:00",
        }
        treasury_service._save_state(state)
        treasury_service._append_event(
            {
                "type": "external_transfer",
                "amount": "0.03",
                "caw_result": {"status": "ok", "request_id": "audit-request"},
            }
        )

        with patch.object(treasury_service, "_request_completed", AsyncMock(return_value=False)):
            result = await treasury_service._reconcile_completed_pending_transfer(
                treasury_service._load_state()
            )

        self.assertEqual(result["pending_transfer"]["stage"], "completed")

    def test_stale_state_cannot_regress_completed_transfer(self) -> None:
        completed = copy.deepcopy(treasury_service.DEFAULT_STATE)
        completed["pending_transfer"] = {
            "id": "pending-1",
            "stage": "completed",
            "status": "completed",
            "updated_at": "2026-06-11T10:00:00+00:00",
        }
        treasury_service._save_state(completed)

        stale = copy.deepcopy(completed)
        stale["pending_transfer"] = {
            "id": "pending-1",
            "stage": "transferring",
            "status": "transferring",
            "updated_at": "2026-06-11T10:01:00+00:00",
        }
        treasury_service._save_state(stale)

        saved = treasury_service._load_state()
        self.assertEqual(saved["pending_transfer"]["stage"], "completed")

    def test_stale_previous_transfer_cannot_replace_new_transfer(self) -> None:
        old_state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        old_state["pending_transfer"] = {
            "id": "old-transfer",
            "stage": "completed",
            "status": "completed",
            "created_at": "2026-06-11T10:00:00+00:00",
            "updated_at": "2026-06-11T10:01:00+00:00",
        }
        treasury_service._save_state(old_state)

        new_state = copy.deepcopy(old_state)
        new_state["pending_transfer"] = {
            "id": "new-transfer",
            "stage": "checking_balance",
            "status": "checking_balance",
            "created_at": "2026-06-11T11:00:00+00:00",
            "updated_at": "2026-06-11T11:00:00+00:00",
        }
        treasury_service._save_state(new_state)
        treasury_service._save_state(old_state)

        saved = treasury_service._load_state()
        self.assertEqual(saved["pending_transfer"]["id"], "new-transfer")

    def test_unknown_pact_id_is_never_treated_as_authorization(self) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)

        result = treasury_service._resolve_external_transfer_caw_pact_id(
            state,
            "None",
            ACTIVE_TRANSFER_PACT["scope"]["destination_address"],
            treasury_service.asset_amount("0.3"),
        )

        self.assertIsNone(result)

    async def test_aave_interest_is_not_reported_as_incoming_wallet_funds(self) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        state["balance_snapshot"] = {
            "wallet_available": "0.1",
            "aave_withdrawable": "0.8",
        }
        treasury_service._save_state(state)
        with (
            patch.object(
                treasury_service,
                "get_aave_wallet_state",
                AsyncMock(return_value={"status": "ok", "wallet_balance": "0.1", "aave_balance": "0.81"}),
            ),
            patch.object(
                treasury_service,
                "get_wallet_status",
                AsyncMock(return_value={"balances": [{"chain_id": "SETH", "token_id": "SETH", "balance": "1"}]}),
            ),
        ):
            result = await treasury_service.sync_treasury()

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["incoming_amount"], "0")

    def test_internal_pact_must_cover_required_amount(self) -> None:
        state = copy.deepcopy(treasury_service.DEFAULT_STATE)
        pact = copy.deepcopy(ACTIVE_AAVE_PACT)
        pact["scope"]["max_amount"] = "0.1"
        state["pacts"] = [pact]

        self.assertIsNone(treasury_service._find_known_internal_caw_pact_id(state, treasury_service.asset_amount("0.2")))


if __name__ == "__main__":
    unittest.main()
