from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AIClient:
    api_key: str | None
    model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"

    @classmethod
    def from_env(cls) -> "AIClient":
        load_dotenv_if_available()
        return cls(
            api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None,
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str) -> str | None:
        if not self.available:
            return None
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(model=self.model, contents=prompt)
            return getattr(response, "text", None)
        except Exception as exc:
            return f"AI request failed: {exc}"

    def embed(self, texts: Iterable[str]) -> list[list[float]] | None:
        if not self.available:
            return None
        text_list = list(texts)
        if not text_list:
            return []
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            response = client.models.embed_content(model=self.embedding_model, contents=text_list)
            return [embedding.values for embedding in response.embeddings]
        except Exception:
            return None


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        return
