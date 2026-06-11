from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.services.caw_service import (
    contract_call_with_pact,
    eth_call,
    estimate_contract_call_fee,
    get_transaction_by_request_id,
    get_wallet_status,
    is_caw_configured,
    submit_contract_call_pact,
)


CHAIN_ID = "SETH"
AAVE_POOL = "0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951"
AAVE_DATA_PROVIDER = "0x3e9708d80f7B3e43118013075F7e95CE3AB31F31"
ASSET_SYMBOL = "WBTC"
ATOKEN_SYMBOL = "aWBTC"
WBTC = "0x29f2d40b0605204364af54ec677bd022da425d03"
AWBTC = "0x1804bf30507dc2eb3bdebbbdd859991eaef6eeff"
ASSET_DECIMALS = 8

SELECTOR_APPROVE = "0x095ea7b3"
SELECTOR_SUPPLY = "0x617ba037"
SELECTOR_WITHDRAW = "0x69328dec"
SELECTOR_TRANSFER = "0xa9059cbb"
SELECTOR_BALANCE_OF = "0x70a08231"
SELECTOR_ALLOWANCE = "0xdd62ed3e"


def aave_config() -> dict[str, Any]:
    return {
        "chain_id": CHAIN_ID,
        "protocol": "Aave V3 Sepolia",
        "pool": AAVE_POOL,
        "data_provider": AAVE_DATA_PROVIDER,
        "asset": {
            "symbol": ASSET_SYMBOL,
            "underlying": WBTC,
            "a_token": AWBTC,
            "decimals": ASSET_DECIMALS,
        },
    }


async def get_aave_wallet_state() -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    wallet_units = await _read_erc20_balance(WBTC, wallet_address)
    aave_units = await _read_erc20_balance(AWBTC, wallet_address)
    allowance_units = await _read_erc20_allowance(WBTC, wallet_address, AAVE_POOL)
    return {
        "status": "ok",
        "wallet_address": wallet_address,
        "asset": ASSET_SYMBOL,
        "a_token_asset": ATOKEN_SYMBOL,
        "wallet_balance": _format_units(wallet_units, ASSET_DECIMALS),
        "aave_balance": _format_units(aave_units, ASSET_DECIMALS),
        "pool_allowance": _format_units(allowance_units, ASSET_DECIMALS),
        "raw": {
            "wallet_balance_units": str(wallet_units),
            "aave_balance_units": str(aave_units),
            "pool_allowance_units": str(allowance_units),
        },
        "config": aave_config(),
    }


async def submit_aave_rebalance_pact(max_amount: str = "100") -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}

    max_units = _parse_units(max_amount, ASSET_DECIMALS)
    spec = build_aave_rebalance_pact_spec(wallet_address=wallet_address, max_amount_units=max_units)
    return await submit_contract_call_pact(
        intent=(
            f"Allow this agent to rebalance Sepolia {ASSET_SYMBOL} with Aave V3 up to {max_amount} {ASSET_SYMBOL} "
            "using approve, supply, and withdraw calls only."
        ),
        name="aave-sepolia-wbtc-rebalance",
        spec=spec,
    )


async def execute_aave_supply(
    pact_id: str,
    amount: str,
    *,
    request_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, ASSET_DECIMALS)
    approve_calldata = encode_approve(AAVE_POOL, amount_units)
    supply_calldata = encode_supply(WBTC, amount_units, wallet_address)
    starting_aave_units = await _read_erc20_balance(AWBTC, wallet_address)
    allowance_units = await _read_erc20_allowance(WBTC, wallet_address, AAVE_POOL)
    approve_result: dict[str, Any] = {"status": "skipped", "reason": "Existing Aave Pool allowance is sufficient."}
    if allowance_units < amount_units:
        approve_result = await contract_call_with_pact(
            pact_id=pact_id,
            chain_id=CHAIN_ID,
            contract_addr=WBTC,
            src_addr=wallet_address,
            calldata=approve_calldata,
            request_id=(request_ids or {}).get("approve"),
            description=f"Approve Aave Pool to pull {amount} {ASSET_SYMBOL}",
        )
        if approve_result.get("status") == "pact_not_active" or approve_result.get("status") == "error":
            return {"status": "approve_failed", "approve": approve_result}
        allowance_units = await _wait_for_allowance(wallet_address, amount_units)
        if allowance_units < amount_units:
            return {
                "status": "approval_pending",
                "operation": "aave_supply",
                "amount": amount,
                "calldata": {"approve": approve_calldata, "supply": supply_calldata},
                "approve": approve_result,
                "aave": await get_aave_wallet_state(),
                "reason": "Approval was submitted, but allowance has not updated yet.",
            }
    supply_result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        src_addr=wallet_address,
        calldata=supply_calldata,
        request_id=(request_ids or {}).get("supply"),
        description=f"Supply {amount} {ASSET_SYMBOL} to Aave V3 Sepolia",
    )
    final_aave_units = await _wait_for_aave_balance(wallet_address, starting_aave_units + amount_units)
    final_state = await get_aave_wallet_state()
    return {
        "status": "ok" if final_aave_units >= starting_aave_units + amount_units else str(supply_result.get("status", "submitted")),
        "operation": "aave_supply",
        "amount": amount,
        "calldata": {"approve": approve_calldata, "supply": supply_calldata},
        "approve": approve_result,
        "supply": supply_result,
        "aave": final_state,
    }


async def execute_aave_withdraw(
    pact_id: str,
    amount: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, ASSET_DECIMALS)
    withdraw_calldata = encode_withdraw(WBTC, amount_units, wallet_address)
    starting_wallet_units = await _read_erc20_balance(WBTC, wallet_address)
    withdraw_result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        src_addr=wallet_address,
        calldata=withdraw_calldata,
        request_id=request_id,
        description=f"Withdraw {amount} {ASSET_SYMBOL} from Aave V3 Sepolia",
    )
    if withdraw_result.get("status") in {
        "error",
        "pact_not_active",
        "missing_pact_api_key",
    }:
        return {
            "status": "withdraw_failed",
            "reason": withdraw_result.get("reason")
            or withdraw_result.get("error")
            or "CAW rejected the Aave withdraw request.",
            "operation": "aave_withdraw",
            "amount": amount,
            "calldata": {"withdraw": withdraw_calldata},
            "withdraw": withdraw_result,
        }
    final_wallet_units = await _wait_for_token_balance(
        WBTC,
        wallet_address,
        starting_wallet_units + amount_units,
    )
    return {
        "status": "ok" if final_wallet_units >= starting_wallet_units + amount_units else str(
            withdraw_result.get("status", "submitted")
        ),
        "operation": "aave_withdraw",
        "amount": amount,
        "calldata": {"withdraw": withdraw_calldata},
        "withdraw": withdraw_result,
        "aave": await get_aave_wallet_state(),
    }


async def submit_wbtc_transfer_pact(*, destination: str, max_amount: str, tx_count: int) -> dict[str, Any]:
    max_units = _parse_units(max_amount, ASSET_DECIMALS)
    spec = build_wbtc_transfer_pact_spec(destination=destination, max_amount_units=max_units, tx_count=tx_count)
    return await submit_contract_call_pact(
        intent=(
            f"Allow up to {tx_count} Sepolia {ASSET_SYMBOL} transfer(s) to {destination}, "
            f"with each transfer capped at {max_amount} {ASSET_SYMBOL}."
        ),
        name="sepolia-wbtc-external-transfer",
        spec=spec,
    )


async def execute_wbtc_transfer(
    pact_id: str,
    destination: str,
    amount: str,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, ASSET_DECIMALS)
    starting_destination_units = await _read_erc20_balance(WBTC, destination)
    calldata = encode_transfer(destination, amount_units)
    request_id = request_id or f"agentic-treasury-{uuid.uuid4()}"
    transfer_result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=WBTC,
        src_addr=wallet_address,
        calldata=calldata,
        request_id=request_id,
        description=f"Transfer {amount} {ASSET_SYMBOL} to {destination}",
    )
    final_destination_units = await _wait_for_token_balance(WBTC, destination, starting_destination_units + amount_units)
    transaction = await _wait_for_caw_transaction_detail(request_id)
    gas_fee = _extract_caw_gas_fee(transaction)
    return {
        "status": "ok" if final_destination_units >= starting_destination_units + amount_units else str(transfer_result.get("status", "submitted")),
        "operation": "wbtc_transfer",
        "amount": amount,
        "destination": destination,
        "request_id": request_id,
        "transaction": transaction,
        "gas_fee": gas_fee,
        "calldata": {"transfer": calldata},
        "transfer": transfer_result,
        "aave": await get_aave_wallet_state(),
    }


async def estimate_aave_fees(
    *,
    amount: str,
    pact_id: str | None = None,
) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "error", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, ASSET_DECIMALS)
    allowance_units = await _read_erc20_allowance(WBTC, wallet_address, AAVE_POOL)
    call_specs: dict[str, Any] = {}
    if allowance_units < amount_units:
        call_specs["approve"] = estimate_contract_call_fee(
            pact_id=pact_id,
            chain_id=CHAIN_ID,
            contract_addr=WBTC,
            src_addr=wallet_address,
            calldata=encode_approve(AAVE_POOL, amount_units),
        )
    call_specs["supply"] = estimate_contract_call_fee(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        src_addr=wallet_address,
        calldata=encode_supply(WBTC, amount_units, wallet_address),
    )
    call_specs["withdraw"] = estimate_contract_call_fee(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        src_addr=wallet_address,
        calldata=encode_withdraw(WBTC, amount_units, wallet_address),
    )
    names = list(call_specs)
    results = await asyncio.gather(*(call_specs[name] for name in names))
    calls = dict(zip(names, results))
    return {
        "status": "ok" if all(_fee_estimate_amount(value) is not None for value in calls.values()) else "error",
        "token_id": _first_fee_token(calls),
        "calls": calls,
        "amounts": {
            name: _fee_estimate_amount(value) or "0"
            for name, value in calls.items()
        },
    }


async def estimate_wbtc_transfer_fee(
    *,
    destination: str,
    amount: str,
    pact_id: str | None = None,
) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "error", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, ASSET_DECIMALS)
    estimate = await estimate_contract_call_fee(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=WBTC,
        src_addr=wallet_address,
        calldata=encode_transfer(destination, amount_units),
    )
    fee_amount = _fee_estimate_amount(estimate)
    return {
        "status": "ok" if fee_amount is not None else "error",
        "token_id": str(estimate.get("token_id") or "SETH"),
        "fee_amount": fee_amount or "0",
        "estimate": estimate,
    }


async def estimate_aave_withdraw_fee(
    *,
    amount: str,
    pact_id: str | None = None,
) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "error", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, ASSET_DECIMALS)
    estimate = await estimate_contract_call_fee(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        src_addr=wallet_address,
        calldata=encode_withdraw(WBTC, amount_units, wallet_address),
    )
    fee_amount = _fee_estimate_amount(estimate)
    return {
        "status": "ok" if fee_amount is not None else "error",
        "token_id": str(estimate.get("token_id") or "SETH"),
        "fee_amount": fee_amount or "0",
        "estimate": estimate,
    }


def build_aave_rebalance_pact_spec(*, wallet_address: str, max_amount_units: int) -> dict[str, Any]:
    approve_abi = [
        {
            "type": "function",
            "name": "approve",
            "selector": SELECTOR_APPROVE,
            "inputs": [
                {"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
        }
    ]
    supply_abi = [
        {
            "type": "function",
            "name": "supply",
            "selector": SELECTOR_SUPPLY,
            "inputs": [
                {"name": "asset", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "onBehalfOf", "type": "address"},
                {"name": "referralCode", "type": "uint16"},
            ],
        }
    ]
    withdraw_abi = [
        {
            "type": "function",
            "name": "withdraw",
            "selector": SELECTOR_WITHDRAW,
            "inputs": [
                {"name": "asset", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "to", "type": "address"},
            ],
        }
    ]
    return {
        "policies": [
            {
                "name": "aave-wbtc-approve",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": approve_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": WBTC, "function_id": SELECTOR_APPROVE}],
                        "params_match": [
                            {"param_name": "spender", "op": "eq", "value": AAVE_POOL},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 6}}},
                },
            },
            {
                "name": "aave-wbtc-supply",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": supply_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": AAVE_POOL, "function_id": SELECTOR_SUPPLY}],
                        "params_match": [
                            {"param_name": "asset", "op": "eq", "value": WBTC},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                            {"param_name": "onBehalfOf", "op": "eq", "value": wallet_address},
                            {"param_name": "referralCode", "op": "eq", "value": "0"},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 3}}},
                },
            },
            {
                "name": "aave-wbtc-withdraw",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": withdraw_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": AAVE_POOL, "function_id": SELECTOR_WITHDRAW}],
                        "params_match": [
                            {"param_name": "asset", "op": "eq", "value": WBTC},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                            {"param_name": "to", "op": "eq", "value": wallet_address},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 3}}},
                },
            },
        ],
        "completion_conditions": [
            {"type": "tx_count", "threshold": "12"},
            {"type": "time_elapsed", "threshold": "604800"},
        ],
        "execution_plan": (
            "# Summary\n"
            f"Allow strategy-scoped Aave V3 Sepolia {ASSET_SYMBOL} operations.\n\n"
            "# Operations\n"
            f"- Approve the Aave Pool to pull {ASSET_SYMBOL}\n"
            f"- Supply {ASSET_SYMBOL} to Aave V3 on behalf of the CAW wallet\n"
            f"- Withdraw {ASSET_SYMBOL} back to the same CAW wallet\n\n"
            "# Risk Controls\n"
            f"- Asset allowlist: {ASSET_SYMBOL} {WBTC}\n"
            f"- Pool allowlist: {AAVE_POOL}\n"
            f"- Wallet recipient/onBehalfOf: {wallet_address}\n"
            f"- Max amount per call: {max_amount_units} raw {ASSET_SYMBOL} units\n"
            "- 7 day pact duration"
        ),
    }


def build_wbtc_transfer_pact_spec(*, destination: str, max_amount_units: int, tx_count: int) -> dict[str, Any]:
    transfer_abi = [
        {
            "type": "function",
            "name": "transfer",
            "selector": SELECTOR_TRANSFER,
            "inputs": [
                {"name": "to", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
        }
    ]
    return {
        "policies": [
            {
                "name": "sepolia-wbtc-transfer",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": transfer_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": WBTC, "function_id": SELECTOR_TRANSFER}],
                        "params_match": [
                            {"param_name": "to", "op": "eq", "value": destination},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                        ],
                    },
                },
            }
        ],
        "completion_conditions": [
            {"type": "tx_count", "threshold": str(max(1, tx_count))},
            {"type": "time_elapsed", "threshold": "604800"},
        ],
        "execution_plan": (
            "# Summary\n"
            f"Allow Sepolia {ASSET_SYMBOL} transfer to {destination}.\n\n"
            "# Operations\n"
            f"- Call {ASSET_SYMBOL}.transfer(to, amount) on {WBTC}\n\n"
            "# Risk Controls\n"
            f"- Asset contract: {ASSET_SYMBOL} {WBTC}\n"
            f"- Destination allowlist: {destination}\n"
            f"- Max amount per transfer: {max_amount_units} raw {ASSET_SYMBOL} units\n"
            f"- Transfer count cap: {max(1, tx_count)} transaction(s)\n"
            "- Pact duration: 7 days"
        ),
    }


async def get_caw_evm_address() -> str | None:
    wallet_status = await get_wallet_status()
    for address in wallet_status.get("addresses", []):
        value = str(address.get("address", ""))
        if value.startswith("0x") and len(value) == 42:
            return value
    return None


def encode_approve(spender: str, amount_units: int) -> str:
    return SELECTOR_APPROVE + _encode_address(spender) + _encode_uint(amount_units)


def encode_supply(asset: str, amount_units: int, on_behalf_of: str) -> str:
    return SELECTOR_SUPPLY + _encode_address(asset) + _encode_uint(amount_units) + _encode_address(on_behalf_of) + _encode_uint(0)


def encode_withdraw(asset: str, amount_units: int, to: str) -> str:
    return SELECTOR_WITHDRAW + _encode_address(asset) + _encode_uint(amount_units) + _encode_address(to)


def encode_transfer(to: str, amount_units: int) -> str:
    return SELECTOR_TRANSFER + _encode_address(to) + _encode_uint(amount_units)


def encode_balance_of(owner: str) -> str:
    return SELECTOR_BALANCE_OF + _encode_address(owner)


def encode_allowance(owner: str, spender: str) -> str:
    return SELECTOR_ALLOWANCE + _encode_address(owner) + _encode_address(spender)


async def _read_erc20_balance(token: str, owner: str) -> int:
    result = await eth_call(chain_id=CHAIN_ID, to=token, data=encode_balance_of(owner), from_address=owner)
    return _decode_uint_result(result)


async def _read_erc20_allowance(token: str, owner: str, spender: str) -> int:
    result = await eth_call(chain_id=CHAIN_ID, to=token, data=encode_allowance(owner, spender), from_address=owner)
    return _decode_uint_result(result)


async def _wait_for_allowance(owner: str, required_units: int, *, attempts: int = 24, delay_seconds: int = 5) -> int:
    allowance_units = await _read_erc20_allowance(WBTC, owner, AAVE_POOL)
    for _ in range(attempts):
        if allowance_units >= required_units:
            return allowance_units
        await asyncio.sleep(delay_seconds)
        allowance_units = await _read_erc20_allowance(WBTC, owner, AAVE_POOL)
    return allowance_units


async def _wait_for_aave_balance(owner: str, required_units: int, *, attempts: int = 24, delay_seconds: int = 5) -> int:
    aave_units = await _read_erc20_balance(AWBTC, owner)
    for _ in range(attempts):
        if aave_units >= required_units:
            return aave_units
        await asyncio.sleep(delay_seconds)
        aave_units = await _read_erc20_balance(AWBTC, owner)
    return aave_units


async def _wait_for_token_balance(
    token: str, owner: str, required_units: int, *, attempts: int = 24, delay_seconds: int = 5
) -> int:
    balance_units = await _read_erc20_balance(token, owner)
    for _ in range(attempts):
        if balance_units >= required_units:
            return balance_units
        await asyncio.sleep(delay_seconds)
        balance_units = await _read_erc20_balance(token, owner)
    return balance_units


async def _wait_for_caw_transaction_detail(request_id: str, *, attempts: int = 12, delay_seconds: int = 3) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for _ in range(attempts):
        detail = await get_transaction_by_request_id(request_id)
        if _transaction_has_final_fee(detail):
            return detail
        await asyncio.sleep(delay_seconds)
    return detail


def _transaction_has_final_fee(detail: dict[str, Any]) -> bool:
    if not detail or detail.get("status") == "error":
        return False
    tracker_metadata = _read_nested_dict(detail, ("tracker_result", "chain_tx", "metadata"))
    if tracker_metadata.get("gas_used") not in (None, "") and tracker_metadata.get("effective_gas_price") not in (None, ""):
        return True
    for fee in _caw_fee_candidates(detail):
        if any(fee.get(key) not in (None, "") for key in ("fee_used", "gas_used")):
            return True
    return False


def _extract_caw_gas_fee(detail: dict[str, Any]) -> str:
    tracker_metadata = _read_nested_dict(detail, ("tracker_result", "chain_tx", "metadata"))
    gas_used = tracker_metadata.get("gas_used")
    effective_gas_price = tracker_metadata.get("effective_gas_price")
    if gas_used not in (None, "") and effective_gas_price not in (None, ""):
        fee_used = (Decimal(str(gas_used)) * Decimal(str(effective_gas_price))) / Decimal("1000000000000000000")
        return f"{fee_used.normalize()} SETH"
    for fee in _caw_fee_candidates(detail):
        token_id = fee.get("token_id")
        fee_used = fee.get("fee_used")
        if fee_used not in (None, ""):
            return f"{fee_used} {token_id or ''}".strip()
        estimated_fee_used = fee.get("estimated_fee_used")
        if estimated_fee_used not in (None, ""):
            return f"{estimated_fee_used} {token_id or ''} estimated".strip()
        gas_used = fee.get("gas_used")
        effective_gas_price = fee.get("effective_gas_price")
        if gas_used not in (None, "") and effective_gas_price not in (None, ""):
            return f"gas_used={gas_used}, effective_gas_price={effective_gas_price}"
    status = detail.get("status_display") or detail.get("status")
    if status and detail.get("status") != "error":
        return f"CAW 交易详情暂未返回 fee（交易状态：{status}）"
    return ""


def _caw_fee_candidates(detail: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for path in (
        ("fee",),
        ("data", "fee"),
        ("prepared_tx", "fee"),
        ("prepared_tx", "data", "fee"),
    ):
        fee = _read_nested_dict(detail, path)
        if fee:
            candidates.append(fee)
    for ext_transaction in detail.get("ext_transactions", []):
        if not isinstance(ext_transaction, dict):
            continue
        fee = _read_nested_dict(ext_transaction, ("data", "fee"))
        if fee:
            candidates.append(fee)
    return candidates


def _read_nested_dict(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _fee_estimate_amount(estimate: dict[str, Any]) -> str | None:
    recommended = estimate.get("recommended")
    if isinstance(recommended, dict) and recommended.get("fee_amount") not in (None, ""):
        return str(recommended["fee_amount"])
    if isinstance(recommended, dict):
        max_fee_per_gas = recommended.get("max_fee_per_gas")
        gas_limit = recommended.get("gas_limit")
        if max_fee_per_gas not in (None, "") and gas_limit not in (None, ""):
            fee = Decimal(str(max_fee_per_gas)) * Decimal(str(gas_limit)) / Decimal("1000000000000000000")
            return format(fee.normalize(), "f")
    if estimate.get("fee_amount") not in (None, ""):
        return str(estimate["fee_amount"])
    return None


def _first_fee_token(calls: dict[str, dict[str, Any]]) -> str:
    for estimate in calls.values():
        token_id = estimate.get("token_id")
        if token_id:
            return str(token_id)
    return "SETH"


def _decode_uint_result(result: dict[str, Any]) -> int:
    raw = result.get("result") or result.get("data") or "0x0"
    if isinstance(raw, dict):
        raw = raw.get("result") or "0x0"
    try:
        return int(str(raw), 16)
    except ValueError:
        return 0


def _parse_units(amount: str, decimals: int) -> int:
    value = Decimal(str(amount)).quantize(Decimal(1) / (Decimal(10) ** decimals), rounding=ROUND_DOWN)
    return int(value * (Decimal(10) ** decimals))


def _format_units(units: int, decimals: int) -> str:
    value = Decimal(units) / (Decimal(10) ** decimals)
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _encode_address(value: str) -> str:
    clean = value.lower().removeprefix("0x")
    if len(clean) != 40:
        raise ValueError(f"Invalid EVM address: {value}")
    return clean.rjust(64, "0")


def _encode_uint(value: int) -> str:
    if value < 0:
        raise ValueError("uint cannot be negative")
    return hex(value).removeprefix("0x").rjust(64, "0")
