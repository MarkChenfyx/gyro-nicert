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
            raise ValueError("AI API 密钥未配置（GYRO_LLM_API_KEY）")
        try:
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
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"AI API 请求超时（{self.config.timeout:g} 秒）") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"AI API 网络错误：{exc}") from exc

        if not response.is_success:
            error_message = response.reason_phrase or "请求失败"
            error_type = ""
            try:
                error_payload = response.json().get("error", {})
                if isinstance(error_payload, dict):
                    error_message = str(error_payload.get("message") or error_message)
                    error_type = str(error_payload.get("type") or error_payload.get("code") or "")
                elif error_payload:
                    error_message = str(error_payload)
            except (ValueError, AttributeError):
                pass
            error_message = error_message.replace(self.config.api_key, "[已隐藏]")
            type_suffix = f"，{error_type}" if error_type else ""
            raise RuntimeError(f"AI API 返回 {response.status_code}{type_suffix}：{error_message}")

        try:
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("AI API 返回格式错误：缺少模型回复内容") from exc


def build_provider(options: dict[str, Any] | None = None) -> ChatCompletionProvider:
    return ChatCompletionProvider(LlmConfig.from_options(options))
