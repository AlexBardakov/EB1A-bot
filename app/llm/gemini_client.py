# app/llm/gemini_client.py
from __future__ import annotations

import os
from typing import Dict, Any, Optional

import google.generativeai as genai
from google.generativeai.types import GenerationConfig

from app.llm.base import LLMClient, LLMResult


class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            genai.configure(api_key=api_key)

        # Рекомендуемая модель сейчас - gemini-1.5-flash (быстрая/дешевая) или gemini-1.5-pro (умная)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

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
            # Gemini поддерживает system_instruction при создании объекта модели
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system
            )

            config = GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

            # Вызов генерации
            response = model.generate_content(
                user,
                generation_config=config,
                # request_options={"timeout": timeout_s} # можно добавить если нужно жесткое ограничение
            )

            # Gemini может блокировать ответ по безопасности, проверяем
            if not response.parts:
                return LLMResult(
                    text="[Gemini Error] Response was blocked by safety filters or empty.",
                    meta={"error": True, "provider": self.name}
                )

            return LLMResult(
                text=response.text,
                meta={"model": self.model_name, "provider": self.name}
            )

        except Exception as e:
            return LLMResult(
                text=f"[Gemini Error] {str(e)}",
                meta={"error": True, "provider": self.name}
            )