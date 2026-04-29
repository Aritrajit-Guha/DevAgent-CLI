from __future__ import annotations

from contextlib import contextmanager
import os
import time
from dataclasses import dataclass
from typing import Iterable, Iterator

_CLIENT_CACHE: dict[tuple[str, str | None], object] = {}
TRANSIENT_BACKOFF_SECONDS = (0.25, 0.75)


@dataclass(frozen=True)
class AIClient:
    api_key: str | None
    api_source: str | None = None
    fast_model: str = "gemini-2.5-flash"
    deep_model: str | None = None
    embedding_model: str = "gemini-embedding-001"

    @classmethod
    def from_env(cls) -> "AIClient":
        load_dotenv_if_available()
        configured_fast = os.environ.get("GEMINI_MODEL_FAST") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
        api_key, api_source = resolve_api_credentials()
        return cls(
            api_key=api_key,
            api_source=api_source,
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
        attempts = len(TRANSIENT_BACKOFF_SECONDS) + 1
        for attempt in range(attempts):
            try:
                client = self._get_client()
                response = self._generate_content(client, prompt, deep=deep, system_instruction=system_instruction)
                return getattr(response, "text", None)
            except Exception as exc:
                if not is_transient_ai_error(exc) or attempt >= attempts - 1:
                    return f"AI request failed: {exc}"
                time.sleep(TRANSIENT_BACKOFF_SECONDS[attempt])
        return None

    def embed(self, texts: Iterable[str]) -> list[list[float]] | None:
        if not self.available:
            return None
        text_list = list(texts)
        if not text_list:
            return []
        try:
            client = self._get_client()
            with selected_api_environment(self.api_key, self.api_source):
                response = client.models.embed_content(model=self.embedding_model, contents=text_list)
            return [embedding.values for embedding in response.embeddings]
        except Exception:
            return None

    def _get_client(self):
        if not self.api_key:
            raise RuntimeError("No Gemini API key is configured.")
        cache_key = (self.api_key, self.api_source)
        cached = _CLIENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        with selected_api_environment(self.api_key, self.api_source):
            from google import genai

            client = genai.Client(api_key=self.api_key)
        _CLIENT_CACHE[cache_key] = client
        return client

    def _generate_content(self, client, prompt: str, *, deep: bool, system_instruction: str | None):
        response = None
        if system_instruction:
            try:
                with selected_api_environment(self.api_key, self.api_source):
                    from google.genai import types

                    response = client.models.generate_content(
                        model=self.selected_model(deep=deep),
                        contents=prompt,
                        config=types.GenerateContentConfig(system_instruction=system_instruction),
                    )
            except Exception as exc:
                if is_transient_ai_error(exc):
                    raise
                response = None
        if response is not None:
            return response

        combined = prompt if not system_instruction else f"{system_instruction}\n\n{prompt}"
        with selected_api_environment(self.api_key, self.api_source):
            return client.models.generate_content(model=self.selected_model(deep=deep), contents=combined)


def resolve_api_credentials() -> tuple[str | None, str | None]:
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        return gemini_key, "GEMINI_API_KEY"
    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key:
        return google_key, "GOOGLE_API_KEY"
    return None, None


def is_transient_ai_error(exc: Exception) -> bool:
    message = str(exc).upper()
    transient_markers = ("503", "UNAVAILABLE", "HIGH DEMAND", "SPIKES IN DEMAND", "TEMPORARY")
    return any(marker in message for marker in transient_markers)


@contextmanager
def selected_api_environment(api_key: str | None, api_source: str | None) -> Iterator[None]:
    original_gemini = os.environ.get("GEMINI_API_KEY")
    original_google = os.environ.get("GOOGLE_API_KEY")
    try:
        if api_source == "GEMINI_API_KEY" and api_key:
            os.environ["GEMINI_API_KEY"] = api_key
            os.environ.pop("GOOGLE_API_KEY", None)
        elif api_source == "GOOGLE_API_KEY" and api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ.pop("GEMINI_API_KEY", None)
        yield
    finally:
        restore_environment_value("GEMINI_API_KEY", original_gemini)
        restore_environment_value("GOOGLE_API_KEY", original_google)


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        return


def restore_environment_value(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
