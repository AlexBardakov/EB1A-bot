# app/llm/openai_client.py
from __future__ import annotations

import os
from typing import Dict, Any, Optional

from app.llm.base import LLMClient, LLMResult

# NOTE: This is a placeholder wrapper. Plug in the official OpenAI SDK in your project.
# Keep your API key in env: OPENAI_API_KEY
# Model name likewise in env: OPENAI_MODEL

class OpenAIClient(LLMClient):
    name = "openai"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL", "gpt-5")  # choose your deployed model

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
        # Replace with real SDK call:
        # resp = client.responses.create(...)
        # text = resp.output_text
        text = f"[OpenAIClient stub] {user[:400]}"
        return LLMResult(text=text, meta={"model": self.model, "provider": self.name})
