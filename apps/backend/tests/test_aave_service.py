from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services import aave_service


class AaveServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_withdraw_rejection_does_not_wait_for_balance_change(self) -> None:
        wait_for_balance = AsyncMock()
        with (
            patch.object(
                aave_service,
                "get_caw_evm_address",
                AsyncMock(return_value="0x1111111111111111111111111111111111111111"),
            ),
            patch.object(aave_service, "_read_erc20_balance", AsyncMock(return_value=100_000_000)),
            patch.object(
                aave_service,
                "contract_call_with_pact",
                AsyncMock(
                    return_value={
                        "status": "pact_not_active",
                        "reason": "Pact is not active.",
                    }
                ),
            ),
            patch.object(aave_service, "_wait_for_token_balance", wait_for_balance),
        ):
            result = await aave_service.execute_aave_withdraw(
                "caw-pact",
                "0.5",
            )

        self.assertEqual(result["status"], "withdraw_failed")
        self.assertEqual(result["reason"], "Pact is not active.")
        wait_for_balance.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
