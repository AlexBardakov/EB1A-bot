# app/llm/openai_client.py
from __future__ import annotations

import os
from typing import Dict, Any, Optional

from openai import OpenAI, OpenAIError
from app.llm.base import LLMClient, LLMResult


class OpenAIClient(LLMClient):
    name = "openai"

    def __init__(self) -> None:
        # Библиотека сама ищет OPENAI_API_KEY в переменных окружения,
        # но для явности передадим, если он задан.
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            # Можно логировать предупреждение, но не будем ронять приложение при старте
            pass

        self.client = OpenAI(api_key=api_key)
        # Модель по умолчанию, если не задана в env
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o")

    def generate(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.2,
            max_output_tokens: int = 1200,
            timeout_s: int = 60,
            extra: Optional[Dict[str, Any]] = None,
    ) -> LLMResult:
        try:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

            # Делаем синхронный вызов (для FastAPI лучше асинхронный,
            # но в текущей архитектуре методы синхронные, оставляем так для простоты)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_output_tokens,
                timeout=timeout_s,
            )

            content = response.choices[0].message.content or ""

            # Сохраняем метаданные о реальном использовании токенов
            usage = response.usage
            meta = {
                "model": self.model,
                "provider": self.name,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
            }

            return LLMResult(text=content, meta=meta)

        except OpenAIError as e:
            # В случае ошибки возвращаем текст ошибки, чтобы бот не "падал" молча,
            # а Аналитик/Судья видели проблему.
            return LLMResult(
                text=f"[OpenAI Error] {str(e)}",
                meta={"error": True, "provider": self.name}
            )