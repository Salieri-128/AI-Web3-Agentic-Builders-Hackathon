from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any

from app.services.caw_service import (
    contract_call_with_pact,
    eth_call,
    get_wallet_status,
    is_caw_configured,
    submit_contract_call_pact,
)


CHAIN_ID = "SETH"
AAVE_POOL = "0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951"
AAVE_DATA_PROVIDER = "0x3e9708d80f7B3e43118013075F7e95CE3AB31F31"
AAVE_FAUCET = "0xC959483DBa39aa9E78757139af0e9a2EDEb3f42D"
USDC = "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8"
AUSDC = "0x16dA4541aD1807f4443d92D26044C1147406EB80"
USDC_DECIMALS = 6

SELECTOR_APPROVE = "0x095ea7b3"
SELECTOR_SUPPLY = "0x617ba037"
SELECTOR_WITHDRAW = "0x69328dec"
SELECTOR_BALANCE_OF = "0x70a08231"
SELECTOR_ALLOWANCE = "0xdd62ed3e"
SELECTOR_FAUCET_MINT = "0xc6c3bbe6"


def aave_config() -> dict[str, Any]:
    return {
        "chain_id": CHAIN_ID,
        "protocol": "Aave V3 Sepolia",
        "pool": AAVE_POOL,
        "data_provider": AAVE_DATA_PROVIDER,
        "faucet": AAVE_FAUCET,
        "asset": {
            "symbol": "USDC",
            "underlying": USDC,
            "a_token": AUSDC,
            "decimals": USDC_DECIMALS,
        },
    }


async def get_aave_wallet_state() -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    usdc_units = await _read_erc20_balance(USDC, wallet_address)
    ausdc_units = await _read_erc20_balance(AUSDC, wallet_address)
    allowance_units = await _read_erc20_allowance(USDC, wallet_address, AAVE_POOL)
    return {
        "status": "ok",
        "wallet_address": wallet_address,
        "asset": "USDC",
        "wallet_balance": _format_units(usdc_units, USDC_DECIMALS),
        "aave_balance": _format_units(ausdc_units, USDC_DECIMALS),
        "pool_allowance": _format_units(allowance_units, USDC_DECIMALS),
        "raw": {
            "wallet_balance_units": str(usdc_units),
            "aave_balance_units": str(ausdc_units),
            "pool_allowance_units": str(allowance_units),
        },
        "config": aave_config(),
    }


async def submit_aave_rebalance_pact(max_amount: str = "100") -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}

    max_units = _parse_units(max_amount, USDC_DECIMALS)
    spec = build_aave_rebalance_pact_spec(wallet_address=wallet_address, max_amount_units=max_units)
    return await submit_contract_call_pact(
        intent=(
            f"Allow this agent to rebalance Sepolia USDC with Aave V3 up to {max_amount} USDC "
            "using approve, supply, withdraw, and official Aave faucet mint calls only."
        ),
        name="aave-sepolia-usdc-rebalance",
        spec=spec,
    )


async def execute_aave_supply(pact_id: str, amount: str) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, USDC_DECIMALS)
    approve_calldata = encode_approve(AAVE_POOL, amount_units)
    supply_calldata = encode_supply(USDC, amount_units, wallet_address)
    approve_result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=USDC,
        calldata=approve_calldata,
        description=f"Approve Aave Pool to pull {amount} USDC",
    )
    if approve_result.get("status") == "pact_not_active" or approve_result.get("status") == "error":
        return {"status": "approve_failed", "approve": approve_result}
    supply_result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        calldata=supply_calldata,
        description=f"Supply {amount} USDC to Aave V3 Sepolia",
    )
    return {
        "status": str(supply_result.get("status", "submitted")),
        "operation": "aave_supply",
        "amount": amount,
        "calldata": {"approve": approve_calldata, "supply": supply_calldata},
        "approve": approve_result,
        "supply": supply_result,
        "aave": await get_aave_wallet_state(),
    }


async def execute_aave_withdraw(pact_id: str, amount: str) -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, USDC_DECIMALS)
    withdraw_calldata = encode_withdraw(USDC, amount_units, wallet_address)
    withdraw_result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_POOL,
        calldata=withdraw_calldata,
        description=f"Withdraw {amount} USDC from Aave V3 Sepolia",
    )
    return {
        "status": str(withdraw_result.get("status", "submitted")),
        "operation": "aave_withdraw",
        "amount": amount,
        "calldata": {"withdraw": withdraw_calldata},
        "withdraw": withdraw_result,
        "aave": await get_aave_wallet_state(),
    }


async def execute_aave_faucet_claim(pact_id: str, amount: str = "100") -> dict[str, Any]:
    wallet_address = await get_caw_evm_address()
    if not wallet_address:
        return {"status": "missing_wallet_address", "reason": "No EVM address returned by CAW wallet status."}
    amount_units = _parse_units(amount, USDC_DECIMALS)
    calldata = encode_faucet_mint(USDC, wallet_address, amount_units)
    result = await contract_call_with_pact(
        pact_id=pact_id,
        chain_id=CHAIN_ID,
        contract_addr=AAVE_FAUCET,
        calldata=calldata,
        description=f"Claim {amount} test USDC from official Aave Sepolia faucet",
    )
    return {
        "status": str(result.get("status", "submitted")),
        "operation": "aave_faucet_claim",
        "amount": amount,
        "calldata": calldata,
        "claim": result,
        "aave": await get_aave_wallet_state(),
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
    faucet_abi = [
        {
            "type": "function",
            "name": "mint",
            "selector": SELECTOR_FAUCET_MINT,
            "inputs": [
                {"name": "token", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
        }
    ]
    return {
        "policies": [
            {
                "name": "aave-usdc-approve",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": approve_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": USDC, "function_id": SELECTOR_APPROVE}],
                        "params_match": [
                            {"param_name": "spender", "op": "eq", "value": AAVE_POOL},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 6}}},
                },
            },
            {
                "name": "aave-usdc-supply",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": supply_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": AAVE_POOL, "function_id": SELECTOR_SUPPLY}],
                        "params_match": [
                            {"param_name": "asset", "op": "eq", "value": USDC},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                            {"param_name": "onBehalfOf", "op": "eq", "value": wallet_address},
                            {"param_name": "referralCode", "op": "eq", "value": "0"},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 3}}},
                },
            },
            {
                "name": "aave-usdc-withdraw",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": withdraw_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [{"chain_id": CHAIN_ID, "contract_addr": AAVE_POOL, "function_id": SELECTOR_WITHDRAW}],
                        "params_match": [
                            {"param_name": "asset", "op": "eq", "value": USDC},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                            {"param_name": "to", "op": "eq", "value": wallet_address},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 3}}},
                },
            },
            {
                "name": "aave-usdc-faucet",
                "type": "contract_call",
                "rules": {
                    "effect": "allow",
                    "function_abis": faucet_abi,
                    "when": {
                        "chain_in": [CHAIN_ID],
                        "target_in": [
                            {"chain_id": CHAIN_ID, "contract_addr": AAVE_FAUCET, "function_id": SELECTOR_FAUCET_MINT}
                        ],
                        "params_match": [
                            {"param_name": "token", "op": "eq", "value": USDC},
                            {"param_name": "to", "op": "eq", "value": wallet_address},
                            {"param_name": "amount", "op": "lte", "value": str(max_amount_units)},
                        ],
                    },
                    "deny_if": {"usage_limits": {"rolling_24h": {"tx_count_gt": 2}}},
                },
            },
        ],
        "completion_conditions": [
            {"type": "tx_count", "threshold": "12"},
            {"type": "time_elapsed", "threshold": "604800"},
        ],
        "execution_plan": (
            "# Summary\n"
            "Allow strategy-scoped Aave V3 Sepolia USDC operations.\n\n"
            "# Operations\n"
            "- Claim test USDC from the official Aave Sepolia faucet\n"
            "- Approve the Aave Pool to pull USDC\n"
            "- Supply USDC to Aave V3 on behalf of the CAW wallet\n"
            "- Withdraw USDC back to the same CAW wallet\n\n"
            "# Risk Controls\n"
            f"- Asset allowlist: USDC {USDC}\n"
            f"- Pool allowlist: {AAVE_POOL}\n"
            f"- Wallet recipient/onBehalfOf: {wallet_address}\n"
            f"- Max amount per call: {max_amount_units} raw USDC units\n"
            "- 7 day pact duration"
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


def encode_faucet_mint(token: str, to: str, amount_units: int) -> str:
    return SELECTOR_FAUCET_MINT + _encode_address(token) + _encode_address(to) + _encode_uint(amount_units)


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
