"""LLM client wrapper supporting Groq, optional Ollama fallback, and deterministic fallback."""

from __future__ import annotations

import json
import os
from typing import Optional, TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

T = TypeVar("T", bound=BaseModel)


def detect_inference_mode() -> str:
    """Report active LLM inference backend based on environment configuration."""
    if os.getenv("GROQ_API_KEY", "").strip():
        return "groq"
    if os.getenv("USE_OLLAMA_FALLBACK", "").strip().lower() in {"1", "true", "yes"}:
        return "ollama"
    return "deterministic_fallback"


def invoke_structured_llm(
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
) -> tuple[Optional[T], str]:
    """Invoke Groq (or optional Ollama) with structured Pydantic output, falling back safely."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_groq import ChatGroq

            model_name = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
            llm = ChatGroq(model=model_name, api_key=groq_key, temperature=0.0, timeout=12)
            structured = llm.with_structured_output(schema)
            result = structured.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            if isinstance(result, schema):
                return result, "groq"
        except Exception:
            pass

    if os.getenv("USE_OLLAMA_FALLBACK", "").strip().lower() in {"1", "true", "yes"}:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        model_name = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        try:
            payload = {
                "model": model_name,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{system_prompt}\nReturn ONLY valid JSON matching schema: "
                            f"{json.dumps(schema.model_json_schema())}"
                        ),
                    },
                    {"role": "user", "content": user_prompt},
                ],
            }
            resp = httpx.post(f"{base_url}/api/chat", json=payload, timeout=10.0)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            return schema.model_validate_json(content), "ollama"
        except Exception:
            pass

    return None, "deterministic_fallback"
