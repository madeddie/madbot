import logging
from enum import Enum

import openai as _openai_lib
from ai_sdk import anthropic as _ant
from ai_sdk import openai as _oai

from bot.config import settings

logger = logging.getLogger(__name__)

_OPENCODEGO_BASE = "https://opencode.ai/zen/go/v1"
_OPENCODEZEN_BASE = "https://opencode.ai/zen/v1"


class Protocol(Enum):
    OPENAI_CHAT = "openai_chat"          # → /chat/completions
    OPENAI_RESPONSES = "openai_responses"  # → /responses (GPT models on Zen)
    ANTHROPIC = "anthropic"              # → /messages
    GOOGLE = "google"                    # → /models/{id} (not yet supported)


# Zen: checked in order, first prefix match wins; unmatched → OPENAI_CHAT
_ZEN_PREFIX_MAP: list[tuple[str, Protocol]] = [
    ("claude-",   Protocol.ANTHROPIC),
    ("gpt-",      Protocol.OPENAI_RESPONSES),
    ("gemini-",   Protocol.GOOGLE),
    ("minimax-",  Protocol.OPENAI_CHAT),
]

# Go: checked in order, first prefix match wins; unmatched → OPENAI_CHAT
_GO_PREFIX_MAP: list[tuple[str, Protocol]] = [
    ("minimax-", Protocol.ANTHROPIC),
]


def _resolve_protocol(model_id: str, prefix_map: list[tuple[str, Protocol]]) -> Protocol:
    for prefix, protocol in prefix_map:
        if model_id.startswith(prefix):
            return protocol
    return Protocol.OPENAI_CHAT


def _make_model(model_id: str, protocol: Protocol, base_url: str, api_key: str):
    logger.debug("_make_model: model_id=%r protocol=%s base_url=%r", model_id, protocol.value, base_url)
    if protocol == Protocol.ANTHROPIC:
        return _ant(model_id, base_url=base_url, api_key=api_key)
    if protocol == Protocol.GOOGLE:
        raise NotImplementedError(
            f"Gemini models ({model_id!r}) require Google SDK support — not yet wired up."
        )
    # OPENAI_CHAT and OPENAI_RESPONSES both use the openai factory.
    # ai_sdk's openai() doesn't accept base_url as a named param — passing it
    # causes it to leak into **default_kwargs and then into completions.create(),
    # which rejects it.  Build without base_url and patch the client directly.
    model = _oai(model_id, api_key=api_key)
    model._client = _openai_lib.OpenAI(base_url=base_url, api_key=api_key)
    return model


def opencodego(model_id: str):
    """
    Return an ai_sdk model for OpenCode Go.

    Go endpoint: https://opencode.ai/zen/go/v1
    Model routing:
      minimax-*  → Anthropic-compatible (/messages)
      everything else → OpenAI-compatible (/chat/completions)

    Usage: model = opencodego("glm-5.1")
    """
    protocol = _resolve_protocol(model_id, _GO_PREFIX_MAP)
    return _make_model(model_id, protocol, _OPENCODEGO_BASE, settings.opencode_api_key)


def opencodezen(model_id: str):
    """
    Return an ai_sdk model for OpenCode Zen.

    Zen endpoint: https://opencode.ai/zen/v1
    Model routing:
      claude-*   → Anthropic-compatible (/messages)
      gpt-*      → OpenAI responses (/responses)
      gemini-*   → Google protocol (not yet supported)
      minimax-*  → OpenAI-compatible (/chat/completions)
      everything else → OpenAI-compatible (/chat/completions)

    Usage: model = opencodezen("claude-sonnet-4-6")
    """
    protocol = _resolve_protocol(model_id, _ZEN_PREFIX_MAP)
    return _make_model(model_id, protocol, _OPENCODEZEN_BASE, settings.opencode_api_key)


def get_default_model():
    """Instantiate the default model from AI_PROVIDER and AI_MODEL env vars."""
    provider = settings.ai_provider.lower()
    model_id = settings.ai_model
    logger.debug("get_default_model: provider=%r model_id=%r", provider, model_id)
    if provider == "opencodego":
        return opencodego(model_id)
    if provider == "opencodezen":
        return opencodezen(model_id)
    raise ValueError(
        f"Unknown AI_PROVIDER {provider!r}. Use 'opencodego' or 'opencodezen'."
    )
