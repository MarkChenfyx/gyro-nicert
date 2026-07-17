from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from backend.core.environment import env


DEFAULT_MODELS = {
    "openai_compatible": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
    "kimi": "moonshot-v1-8k",
}

DEFAULT_BASE_URLS = {
    "openai_compatible": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
}


@dataclass(slots=True)
class LlmConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    timeout: float
    temperature: float

    @classmethod
    def from_options(cls, options: dict[str, Any] | None = None) -> "LlmConfig":
        values = dict(options or {})
        provider = str(values.get("provider") or env("GYRO_LLM_PROVIDER", "openai_compatible")).strip().lower()
        if provider not in DEFAULT_BASE_URLS:
            raise ValueError(f"unsupported LLM provider: {provider}")
        api_key = str(
            values.get("api_key")
            or env("GYRO_LLM_API_KEY")
            or env("OPENAI_API_KEY")
        ).strip()
        base_url = str(
            values.get("base_url")
            or env("GYRO_LLM_BASE_URL")
            or env("OPENAI_BASE_URL")
            or DEFAULT_BASE_URLS[provider]
        ).rstrip("/")
        model = str(
            values.get("model")
            or env("GYRO_LLM_MODEL")
            or env("OPENAI_MODEL")
            or DEFAULT_MODELS[provider]
        ).strip()
        timeout = float(values.get("timeout") or env("GYRO_LLM_TIMEOUT", env("OPENAI_TIMEOUT", "60")) or 60)
        temperature = float(values.get("temperature") or env("GYRO_LLM_TEMPERATURE", "0.1") or 0.1)
        return cls(provider=provider, api_key=api_key, base_url=base_url, model=model, timeout=timeout, temperature=temperature)


class ChatCompletionProvider:
    def __init__(self, config: LlmConfig):
        self.config = config

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.config.api_key:
            raise ValueError("GYRO_LLM_API_KEY is not configured")
        response = httpx.post(
            f"{self.config.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "temperature": self.config.temperature,
                "messages": messages,
                "response_format": {"type": "json_object"},
            },
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload["choices"][0]["message"]["content"])


def build_provider(options: dict[str, Any] | None = None) -> ChatCompletionProvider:
    return ChatCompletionProvider(LlmConfig.from_options(options))
