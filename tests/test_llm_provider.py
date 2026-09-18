"""Tests for the LLM provider module."""

from app.ml.llm_provider import LLMProvider, LLMResponse


class TestLLMResponse:
    def test_ok_response(self):
        resp = LLMResponse(content="Hello", model="test")
        assert resp.ok is True

    def test_error_response(self):
        resp = LLMResponse(content="", model="test", error="Connection failed")
        assert resp.ok is False


class TestLLMProvider:
    def test_provider_init_defaults(self):
        """Provider should initialize with default settings."""
        provider = LLMProvider()
        assert provider.provider == "ollama"
        assert "11434" in provider.base_url
        assert provider.model is not None

    async def test_unknown_provider(self):
        """Unknown provider should return an error."""
        provider = LLMProvider()
        provider.provider = "unknown_provider"

        result = await provider.generate("test prompt")
        assert result.ok is False
        assert "Unknown provider" in result.error
