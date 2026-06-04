from __future__ import annotations

import os


def get_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def caw_api_url() -> str | None:
    return get_env("AGENT_WALLET_API_URL", "CAW_API_URL", "COBO_AGENTIC_WALLET_API_URL", "COBO_API_URL")


def caw_api_key() -> str | None:
    return get_env("AGENT_WALLET_API_KEY", "CAW_API_KEY", "COBO_AGENTIC_WALLET_API_KEY", "COBO_API_KEY")


def caw_wallet_id() -> str | None:
    return get_env(
        "AGENT_WALLET_WALLET_ID",
        "CAW_WALLET_ID",
        "COBO_AGENTIC_WALLET_ID",
        "COBO_WALLET_ID",
        "WALLET_ID",
    )


def llm_api_key() -> str | None:
    base_url = llm_api_base_url()
    if "api.openai.com" not in base_url:
        return get_env("api_key", "LLM_API_KEY", "API_KEY", "OPENAI_API_KEY")
    return get_env("LLM_API_KEY", "OPENAI_API_KEY", "api_key", "API_KEY")


def llm_api_base_url() -> str:
    return (
        get_env(
            "LLM_API_BASE_URL",
            "LLM_BASE_URL",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE_URL",
            "API_BASE_URL",
            "BASE_URL",
            "API_URL",
        )
        or "https://api.openai.com/v1"
    )


def llm_chat_completions_url() -> str | None:
    return get_env("LLM_CHAT_COMPLETIONS_URL", "CHAT_COMPLETIONS_URL", "OPENAI_CHAT_COMPLETIONS_URL")


def llm_model() -> str:
    return get_env("LLM_MODEL", "OPENAI_MODEL", "MODEL", "MODEL_NAME", "model") or "deepseek-v4-pro"


def llm_fallback_models() -> list[str]:
    raw_value = get_env("LLM_FALLBACK_MODELS", "FALLBACK_MODELS")
    if not raw_value:
        return []
    return [model.strip() for model in raw_value.split(",") if model.strip()]
