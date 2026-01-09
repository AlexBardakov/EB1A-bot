# app/llm/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class LLMResult:
    text: str
    meta: Dict[str, Any]


class LLMClient:
    """
    Provider-agnostic interface.
    Implement generate() for OpenAI and Gemini.
    """
    name: str

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
        raise NotImplementedError
