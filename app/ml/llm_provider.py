"""Pluggable LLM provider abstraction."""
import httpx
import logging
from dataclasses import dataclass
from typing import Optional
from app.config import get_settings

logger = logging.getLogger(__name__)

@dataclass
class LLMResponse:
    """Structured response from an LLM provider."""
    content: str
    model: str
    tokens_used: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

class LLMProvider:
    """Unified LLM interface. Defaults to Ollama running locally."""

    def __init__(self):
        settings = get_settings()
        self.provider = settings.llm_provider
        self.base_url = settings.llm_base_url
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key
        self.timeout = settings.llm_timeout

    async def generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Generate a completion from the LLM."""
        if self.provider == "ollama":
            return await self._ollama_generate(prompt, system_prompt)
        elif self.provider == "openai":
            return await self._openai_generate(prompt, system_prompt)
        else:
            return LLMResponse(content="", model=self.model, error=f"Unknown provider: {self.provider}")

    async def _ollama_generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Call Ollama's /api/generate endpoint."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 1024,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return LLMResponse(
                    content=data.get("response", ""),
                    model=data.get("model", self.model),
                    tokens_used=data.get("eval_count"),
                )
        except httpx.ConnectError:
            logger.warning("Ollama not reachable at %s — is it running?", self.base_url)
            return LLMResponse(content="", model=self.model, error="Ollama not reachable. Ensure the Ollama service is running.")
        except Exception as e:
            logger.error("Ollama error: %s", str(e))
            return LLMResponse(content="", model=self.model, error=str(e))

    async def _openai_generate(self, prompt: str, system_prompt: Optional[str] = None) -> LLMResponse:
        """Call an OpenAI-compatible /v1/chat/completions endpoint."""
        url = f"{self.base_url}/v1/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 1024,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                usage = data.get("usage", {})
                return LLMResponse(
                    content=choice["message"]["content"],
                    model=data.get("model", self.model),
                    tokens_used=usage.get("total_tokens"),
                )
        except Exception as e:
            logger.error("OpenAI-compatible API error: %s", str(e))
            return LLMResponse(content="", model=self.model, error=str(e))

    async def is_available(self) -> bool:
        """Check if the LLM service is reachable."""
        try:
            if self.provider == "ollama":
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(f"{self.base_url}/api/tags")
                    return resp.status_code == 200
            return True
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available models (Ollama only)."""
        if self.provider != "ollama":
            return [self.model]
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

# Singleton
_provider: Optional[LLMProvider] = None

def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = LLMProvider()
    return _provider
