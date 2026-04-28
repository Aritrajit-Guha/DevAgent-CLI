from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AIClient:
    api_key: str | None
    fast_model: str = "gemini-2.5-flash"
    deep_model: str | None = None
    embedding_model: str = "gemini-embedding-001"

    @classmethod
    def from_env(cls) -> "AIClient":
        load_dotenv_if_available()
        configured_fast = os.environ.get("GEMINI_MODEL_FAST") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
        return cls(
            api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or None,
            fast_model=configured_fast,
            deep_model=os.environ.get("GEMINI_MODEL_DEEP") or None,
            embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"),
        )

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def selected_model(self, *, deep: bool = False) -> str:
        if deep and self.deep_model:
            return self.deep_model
        return self.fast_model

    def complete(self, prompt: str, *, deep: bool = False, system_instruction: str | None = None) -> str | None:
        if not self.available:
            return None
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            response = None
            if system_instruction:
                try:
                    from google.genai import types

                    response = client.models.generate_content(
                        model=self.selected_model(deep=deep),
                        contents=prompt,
                        config=types.GenerateContentConfig(system_instruction=system_instruction),
                    )
                except Exception:
                    response = None
            if response is None:
                combined = prompt if not system_instruction else f"{system_instruction}\n\n{prompt}"
                response = client.models.generate_content(model=self.selected_model(deep=deep), contents=combined)
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
