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


class TestProviderHttp:
    """The provider's HTTP paths, answered by an httpx mock transport."""

    def _provider(self, handler, provider="ollama", api_key=None):
        import httpx

        instance = LLMProvider(transport=httpx.MockTransport(handler))
        instance.provider = provider
        instance.base_url = "http://llm.test"
        instance.model = "test-model"
        instance.api_key = api_key
        return instance

    async def test_ollama_generate(self):
        import httpx

        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["json"] = request.read() and __import__("json").loads(request.content)
            return httpx.Response(
                200, json={"response": '{"comments": []}', "model": "test-model", "eval_count": 12}
            )

        response = await self._provider(handler).generate("prompt", system_prompt="sys")
        assert response.ok and response.content == '{"comments": []}'
        assert response.tokens_used == 12
        assert seen["url"] == "http://llm.test/api/generate"
        assert seen["json"]["system"] == "sys" and seen["json"]["stream"] is False

    async def test_ollama_unreachable(self):
        import httpx

        def handler(request):
            raise httpx.ConnectError("refused")

        response = await self._provider(handler).generate("prompt")
        assert response.ok is False
        assert "not reachable" in response.error

    async def test_ollama_http_error(self):
        import httpx

        response = await self._provider(lambda r: httpx.Response(500, text="x")).generate("p")
        assert response.ok is False
        assert "500" in response.error

    async def test_openai_compatible_generate(self):
        import httpx

        seen = {}

        def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            seen["url"] = str(request.url)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "hello"}}],
                    "model": "gpt-x",
                    "usage": {"total_tokens": 7},
                },
            )

        provider = self._provider(handler, provider="openai", api_key="sk-test")
        response = await provider.generate("prompt", system_prompt="sys")
        assert response.ok and response.content == "hello"
        assert response.model == "gpt-x" and response.tokens_used == 7
        assert seen["auth"] == "Bearer sk-test"
        assert seen["url"] == "http://llm.test/v1/chat/completions"

    async def test_availability_and_models(self):
        import httpx

        def handler(request):
            assert request.url.path == "/api/tags"
            return httpx.Response(200, json={"models": [{"name": "codellama:7b"}]})

        provider = self._provider(handler)
        assert await provider.is_available() is True
        assert await provider.list_models() == ["codellama:7b"]

        def down(request):
            raise httpx.ConnectError("refused")

        provider = self._provider(down)
        assert await provider.is_available() is False
        assert await provider.list_models() == []
