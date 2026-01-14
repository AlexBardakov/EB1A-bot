# app/llm/gemini_client.py
from __future__ import annotations

import os
from typing import Dict, Any, Optional

# НОВЫЙ ИМПОРТ
from google import genai
from google.genai import types

from app.llm.base import LLMClient, LLMResult

class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self, model_name: Optional[str] = None) -> None:
        """
        Инициализация клиента Google Gen AI (v1.0+).
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("⚠️ WARNING: GEMINI_API_KEY is not set.")
            return

        # Создаем клиента (он теперь stateless, хранит только ключ)
        self.client = genai.Client(api_key=api_key)

        # Определяем модель (Flash для скорости, Pro для ума)
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    def generate(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.3,
            max_output_tokens: int = 2000,
            timeout_s: int = 60,
            extra: Optional[Dict[str, Any]] = None,
    ) -> LLMResult:
        try:
            # Конфигурация генерации
            config = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                system_instruction=system  # Системный промпт теперь здесь
            )

            # Вызов API
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user,
                config=config
            )

            # В новом SDK .text может бросить ошибку, если ответ пустой/заблокирован
            # Поэтому безопасно извлекаем текст
            if not response.text:
                return LLMResult(
                    text="[Gemini Error] Ответ пуст или заблокирован фильтрами.",
                    meta={"error": True, "provider": self.name}
                )

            return LLMResult(
                text=response.text,
                meta={"model": self.model_name, "provider": self.name}
            )

        except Exception as e:
            print(f"[Gemini Error] {e}")
            return LLMResult(
                text=f"[Gemini Error] {str(e)}",
                meta={"error": True, "provider": self.name}
            )