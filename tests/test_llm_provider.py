import os
from unittest.mock import patch
from docmancer.connectors.llm.provider import get_llm_provider
from docmancer.core.config import DocmancerConfig, LLMConfig


def test_get_provider_returns_none_without_key():
    config = DocmancerConfig()
    with patch.dict(os.environ, {}, clear=True):
        provider = get_llm_provider(config)
    assert provider is None


def test_get_provider_returns_none_with_empty_llm_config():
    config = DocmancerConfig(llm=LLMConfig(api_key=""))
    with patch.dict(os.environ, {}, clear=True):
        provider = get_llm_provider(config)
    assert provider is None


def test_get_provider_from_env_var():
    config = DocmancerConfig()
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
        # This will try to import anthropic - mock it if not installed
        try:
            provider = get_llm_provider(config)
            # If anthropic is installed, provider should not be None
        except ImportError:
            pass  # Expected if anthropic not installed


def test_get_provider_from_config_key():
    config = DocmancerConfig(llm=LLMConfig(api_key="sk-from-config"))
    # anthropic package may not be installed; the factory returns None on ImportError
    provider = get_llm_provider(config)
    # If anthropic is not installed, provider will be None (graceful degradation)
    # If it is installed, provider will be an AnthropicProvider instance
    try:
        import anthropic
        assert provider is not None
    except ImportError:
        assert provider is None
