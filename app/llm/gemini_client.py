# app/llm/gemini_client.py
from __future__ import annotations

import os
from typing import Dict, Any, Optional

from app.llm.base import LLMClient, LLMResult

# NOTE: Placeholder wrapper. Plug in Google GenAI SDK.
# Keep API key in env: GEMINI_API_KEY
# Model in env: GEMINI_MODEL

class GeminiClient(LLMClient):
    name = "gemini"

    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

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
        text = f"[GeminiClient stub] {user[:400]}"
        return LLMResult(text=text, meta={"model": self.model, "provider": self.name})
