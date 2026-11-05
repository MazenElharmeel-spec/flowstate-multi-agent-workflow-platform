"""LLM Gateway factory selecting between real and scripted fake providers."""

from backend.app.core.config import get_settings
from backend.app.llm.anthropic import AnthropicLLMProvider
from backend.app.llm.base import BaseLLMProvider
from backend.app.llm.fake import ScriptedFakeLLM

settings = get_settings()


def get_llm_provider(
    provider_override: str | None = None,
    scenario: str = "happy_path",
) -> BaseLLMProvider:
    provider = provider_override or settings.DEFAULT_LLM_PROVIDER

    if provider == "anthropic" and settings.ANTHROPIC_API_KEY:
        return AnthropicLLMProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.DEFAULT_MODEL_NAME,
        )

    # Default to deterministic scripted fake LLM for tests and zero-key demo
    return ScriptedFakeLLM(scenario=scenario)
