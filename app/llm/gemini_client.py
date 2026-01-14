# app/llm/gemini_client.py
from __future__ import annotations

import os
from typing import Dict, Any, Optional

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

from app.llm.base import LLMClient, LLMResult


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self, model_name: Optional[str] = None) -> None:
        """
        model_name: Если указано, принудительно используем эту модель.
                    Иначе берем из .env (GEMINI_MODEL).
                    Иначе fallback на 'gemini-2.5-flash'.
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)

        # Приоритет: Аргумент -> ENV -> Default
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
            # Создаем модель с системной инструкцией
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system
            )

            config = GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

            response = model.generate_content(
                user,
                generation_config=config,
            )

            if not response.parts:
                return LLMResult(
                    text="[Gemini Error] Ответ заблокирован фильтрами безопасности.",
                    meta={"error": True, "provider": self.name}
                )

            return LLMResult(
                text=response.text,
                meta={"model": self.model_name, "provider": self.name}
            )

        except Exception as e:
            # Если ошибка - выводим в лог, но не роняем бота
            print(f"[Gemini Error] {e}")
            return LLMResult(
                text=f"[Gemini Error] {str(e)}",
                meta={"error": True, "provider": self.name}
            )