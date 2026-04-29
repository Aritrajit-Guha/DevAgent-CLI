from __future__ import annotations

from contextlib import contextmanager
import os
import time
from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol
from urllib import error, request
import json

from devagent.config.settings import ConfigManager, ProviderModelConfig

GENERATION_CAPABILITY = "generate"
EMBED_CAPABILITY = "embed"
PROVIDER_ORDER = ("gemini", "xai")
PROVIDER_LABELS = {"gemini": "Gemini", "xai": "xAI"}
TRANSIENT_BACKOFF_SECONDS = (0.25, 0.75)
GEMINI_DEFAULT_FAST_MODEL = "gemini-2.5-flash"
GEMINI_DEFAULT_DEEP_MODEL = "gemini-2.5-pro"
GEMINI_DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
XAI_DEFAULT_FAST_MODEL = "grok-3-mini"

_CLIENT_CACHE: dict[tuple[str, str, str | None], object] = {}
_MODEL_CACHE: dict[tuple[str, str], tuple["DiscoveredModel", ...]] = {}


@dataclass(frozen=True)
class ProviderCredentials:
    provider: str
    api_key: str
    api_source: str


@dataclass(frozen=True)
class DiscoveredModel:
    provider: str
    id: str
    label: str
    capabilities: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class AIProviderStatus:
    provider: str
    api_source: str | None
    selected: bool
    generation_models: int = 0
    embedding_models: int = 0

    @property
    def label(self) -> str:
        return PROVIDER_LABELS.get(self.provider, self.provider)


@dataclass(frozen=True)
class AIStatusSnapshot:
    selected_provider: str | None
    fast_model: str | None
    deep_model: str | None
    embedding_model: str | None
    providers: tuple[AIProviderStatus, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedAIProfile:
    provider: str | None
    api_key: str | None
    api_source: str | None
    fast_model: str | None
    deep_model: str | None
    embedding_model: str | None
    available_providers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ProviderAdapter(Protocol):
    provider: str
    credentials: ProviderCredentials

    def list_models(self, *, refresh: bool = False) -> list[DiscoveredModel]:
        ...

    def complete(self, prompt: str, *, model: str, system_instruction: str | None = None) -> str | None:
        ...

    def embed(self, texts: Iterable[str], *, model: str) -> list[list[float]] | None:
        ...


@dataclass(frozen=True)
class AIClient:
    provider: str | None
    api_key: str | None
    api_source: str | None = None
    fast_model: str | None = GEMINI_DEFAULT_FAST_MODEL
    deep_model: str | None = GEMINI_DEFAULT_DEEP_MODEL
    embedding_model: str | None = GEMINI_DEFAULT_EMBEDDING_MODEL
    available_providers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "AIClient":
        load_dotenv_if_available()
        config = ConfigManager.load()
        credentials = resolve_available_credentials()
        profile = resolve_profile(credentials, config.ai_settings)
        return cls(
            provider=profile.provider,
            api_key=profile.api_key,
            api_source=profile.api_source,
            fast_model=profile.fast_model,
            deep_model=profile.deep_model,
            embedding_model=profile.embedding_model,
            available_providers=profile.available_providers,
            warnings=profile.warnings,
        )

    @property
    def available(self) -> bool:
        return bool(self.provider and self.api_key)

    @property
    def provider_label(self) -> str:
        if not self.provider:
            return "AI"
        return PROVIDER_LABELS.get(self.provider, self.provider)

    def selected_model(self, *, deep: bool = False) -> str | None:
        if deep and self.deep_model:
            return self.deep_model
        return self.fast_model

    def complete(self, prompt: str, *, deep: bool = False, system_instruction: str | None = None) -> str | None:
        if not self.available or not self.provider:
            return None
        model = self._resolved_generation_model(deep=deep)
        if not model:
            return f"AI request failed: no generation model is configured for {self.provider_label}."
        attempts = len(TRANSIENT_BACKOFF_SECONDS) + 1
        for attempt in range(attempts):
            try:
                return self._adapter_for(self.provider).complete(prompt, model=model, system_instruction=system_instruction)
            except Exception as exc:
                if not is_transient_ai_error(exc) or attempt >= attempts - 1:
                    return f"AI request failed: {exc}"
                time.sleep(TRANSIENT_BACKOFF_SECONDS[attempt])
        return None

    def embed(self, texts: Iterable[str]) -> list[list[float]] | None:
        if not self.available or not self.provider or not self.embedding_model:
            return None
        text_list = list(texts)
        if not text_list:
            return []
        if not self.supports_embeddings(self.provider):
            return None
        model = self._resolved_embedding_model()
        if not model:
            return None
        try:
            return self._adapter_for(self.provider).embed(text_list, model=model)
        except Exception:
            return None

    def supports_embeddings(self, provider: str | None = None) -> bool:
        target = provider or self.provider
        return target == "gemini"

    def provider_status(self, *, refresh: bool = False) -> AIStatusSnapshot:
        warnings = list(self.warnings)
        provider_rows: list[AIProviderStatus] = []

        for provider in self.available_providers:
            models = self.list_models(provider=provider, refresh=refresh)
            provider_rows.append(
                AIProviderStatus(
                    provider=provider,
                    api_source=self._credentials_for(provider).api_source if self._credentials_for(provider) else None,
                    selected=provider == self.provider,
                    generation_models=sum(1 for model in models if model.supports(GENERATION_CAPABILITY)),
                    embedding_models=sum(1 for model in models if model.supports(EMBED_CAPABILITY)),
                )
            )

        fast_model = self.fast_model
        deep_model = self.deep_model
        embedding_model = self.embedding_model

        if self.provider:
            generation_ids = {model.id for model in self.list_models(provider=self.provider, refresh=refresh, capability=GENERATION_CAPABILITY)}
            if fast_model and generation_ids and fast_model not in generation_ids:
                warnings.append(f"Saved chat model `{fast_model}` is not currently available for {self.provider_label}; DevAgent will fall back automatically.")
                fast_model = self._fallback_model_for(self.provider, GENERATION_CAPABILITY, deep=False)
            if deep_model and generation_ids and deep_model not in generation_ids:
                warnings.append(f"Saved deep model `{deep_model}` is not currently available for {self.provider_label}; DevAgent will fall back automatically.")
                deep_model = self._fallback_model_for(self.provider, GENERATION_CAPABILITY, deep=True)

            if self.supports_embeddings(self.provider):
                embedding_ids = {model.id for model in self.list_models(provider=self.provider, refresh=refresh, capability=EMBED_CAPABILITY)}
                if embedding_model and embedding_ids and embedding_model not in embedding_ids:
                    warnings.append(f"Saved embedding model `{embedding_model}` is not currently available for {self.provider_label}; DevAgent will fall back automatically.")
                    embedding_model = self._fallback_model_for(self.provider, EMBED_CAPABILITY, deep=False)
            else:
                embedding_model = None

        return AIStatusSnapshot(
            selected_provider=self.provider,
            fast_model=fast_model,
            deep_model=deep_model,
            embedding_model=embedding_model,
            providers=tuple(provider_rows),
            warnings=tuple(unique_preserving_order(warnings)),
        )

    def list_models(
        self,
        *,
        provider: str | None = None,
        refresh: bool = False,
        capability: str | None = None,
    ) -> list[DiscoveredModel]:
        target = provider or self.provider
        if not target:
            return []
        adapter = self._adapter_for(target)
        models = adapter.list_models(refresh=refresh)
        if capability:
            return [model for model in models if model.supports(capability)]
        return models

    def _resolved_generation_model(self, *, deep: bool) -> str | None:
        if not self.provider:
            return None
        selected = self.selected_model(deep=deep)
        try:
            available = {model.id for model in self.list_models(provider=self.provider, capability=GENERATION_CAPABILITY)}
        except Exception:
            available = set()
        if selected and (not available or selected in available):
            return selected
        return self._fallback_model_for(self.provider, GENERATION_CAPABILITY, deep=deep)

    def _resolved_embedding_model(self) -> str | None:
        if not self.provider or not self.supports_embeddings(self.provider):
            return None
        selected = self.embedding_model
        try:
            available = {model.id for model in self.list_models(provider=self.provider, capability=EMBED_CAPABILITY)}
        except Exception:
            available = set()
        if selected and (not available or selected in available):
            return selected
        return self._fallback_model_for(self.provider, EMBED_CAPABILITY, deep=False)

    def _fallback_model_for(self, provider: str, capability: str, *, deep: bool) -> str | None:
        discovered = self.list_models(provider=provider, capability=capability)
        if discovered:
            chosen = choose_default_discovered_model(provider, discovered, capability=capability, deep=deep)
            if chosen:
                return chosen.id
        if provider == "gemini":
            if capability == EMBED_CAPABILITY:
                return GEMINI_DEFAULT_EMBEDDING_MODEL
            return GEMINI_DEFAULT_DEEP_MODEL if deep else GEMINI_DEFAULT_FAST_MODEL
        if provider == "xai" and capability == GENERATION_CAPABILITY:
            return XAI_DEFAULT_FAST_MODEL
        return None

    def _credentials_for(self, provider: str) -> ProviderCredentials | None:
        if provider == self.provider and self.api_key:
            return ProviderCredentials(provider=provider, api_key=self.api_key, api_source=self.api_source or "")
        return resolve_available_credentials().get(provider)

    def _adapter_for(self, provider: str) -> ProviderAdapter:
        credentials = self._credentials_for(provider)
        if credentials is None:
            raise RuntimeError(f"No API key is configured for provider `{provider}`.")
        if provider == "gemini":
            return GeminiAdapter(credentials)
        if provider == "xai":
            return XAIAdapter(credentials)
        raise RuntimeError(f"Unsupported AI provider `{provider}`.")


def resolve_profile(
    credentials: dict[str, ProviderCredentials],
    ai_settings,
) -> ResolvedAIProfile:
    available = tuple(provider for provider in PROVIDER_ORDER if provider in credentials)
    warnings: list[str] = []
    selected_provider = ai_settings.selected_provider if ai_settings.selected_provider in credentials else None
    if ai_settings.selected_provider and selected_provider is None:
        warnings.append(f"Saved provider `{ai_settings.selected_provider}` is not currently configured; DevAgent is using the next available provider.")
    if selected_provider is None:
        selected_provider = "gemini" if "gemini" in credentials else next(iter(available), None)
    if not selected_provider:
        return ResolvedAIProfile(
            provider=None,
            api_key=None,
            api_source=None,
            fast_model=None,
            deep_model=None,
            embedding_model=None,
            available_providers=available,
            warnings=tuple(warnings),
        )

    provider_config = ai_settings.providers.get(selected_provider, ProviderModelConfig())
    provider_credentials = credentials[selected_provider]
    fast_model = first_non_empty(
        provider_config.model,
        provider_env_model(selected_provider, "model"),
        default_model_for_provider(selected_provider, capability=GENERATION_CAPABILITY, deep=False),
    )
    deep_model = first_non_empty(
        provider_config.deep_model,
        provider_env_model(selected_provider, "deep_model"),
        default_model_for_provider(selected_provider, capability=GENERATION_CAPABILITY, deep=True),
    )
    embedding_model = first_non_empty(
        provider_config.embedding_model,
        provider_env_model(selected_provider, "embedding_model"),
        default_model_for_provider(selected_provider, capability=EMBED_CAPABILITY, deep=False),
    )
    if selected_provider != "gemini":
        embedding_model = None

    return ResolvedAIProfile(
        provider=selected_provider,
        api_key=provider_credentials.api_key,
        api_source=provider_credentials.api_source,
        fast_model=fast_model,
        deep_model=deep_model,
        embedding_model=embedding_model,
        available_providers=available,
        warnings=tuple(warnings),
    )


def resolve_available_credentials() -> dict[str, ProviderCredentials]:
    credentials: dict[str, ProviderCredentials] = {}
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        credentials["gemini"] = ProviderCredentials("gemini", gemini_key, "GEMINI_API_KEY")
    else:
        google_key = os.environ.get("GOOGLE_API_KEY")
        if google_key:
            credentials["gemini"] = ProviderCredentials("gemini", google_key, "GOOGLE_API_KEY")

    xai_key = os.environ.get("XAI_API_KEY")
    if xai_key:
        credentials["xai"] = ProviderCredentials("xai", xai_key, "XAI_API_KEY")
    return credentials


def resolve_api_credentials(provider: str | None = None) -> tuple[str | None, str | None]:
    credentials = resolve_available_credentials()
    if provider:
        chosen = credentials.get(provider)
        return (chosen.api_key, chosen.api_source) if chosen else (None, None)
    for candidate in PROVIDER_ORDER:
        if candidate in credentials:
            chosen = credentials[candidate]
            return chosen.api_key, chosen.api_source
    return None, None


def provider_env_model(provider: str, kind: str) -> str | None:
    if provider == "gemini":
        if kind == "model":
            return os.environ.get("GEMINI_MODEL_FAST") or os.environ.get("GEMINI_MODEL")
        if kind == "deep_model":
            return os.environ.get("GEMINI_MODEL_DEEP")
        if kind == "embedding_model":
            return os.environ.get("GEMINI_EMBEDDING_MODEL")
    if provider == "xai":
        if kind == "model":
            return os.environ.get("XAI_MODEL_FAST") or os.environ.get("XAI_MODEL")
        if kind == "deep_model":
            return os.environ.get("XAI_MODEL_DEEP")
        if kind == "embedding_model":
            return os.environ.get("XAI_EMBEDDING_MODEL")
    return None


def default_model_for_provider(provider: str, *, capability: str, deep: bool) -> str | None:
    if provider == "gemini":
        if capability == EMBED_CAPABILITY:
            return GEMINI_DEFAULT_EMBEDDING_MODEL
        return GEMINI_DEFAULT_DEEP_MODEL if deep else GEMINI_DEFAULT_FAST_MODEL
    if provider == "xai" and capability == GENERATION_CAPABILITY:
        return XAI_DEFAULT_FAST_MODEL
    return None


def choose_default_discovered_model(
    provider: str,
    models: list[DiscoveredModel],
    *,
    capability: str,
    deep: bool,
) -> DiscoveredModel | None:
    if not models:
        return None

    ranked = list(models)
    if provider == "gemini":
        preferences = []
        if capability == EMBED_CAPABILITY:
            preferences = ("embedding",)
        elif deep:
            preferences = ("2.5-pro", "pro")
        else:
            preferences = ("2.5-flash", "flash")
        for needle in preferences:
            for model in ranked:
                if needle in model.id.casefold():
                    return model
    return ranked[0]


def first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None


def is_transient_ai_error(exc: Exception) -> bool:
    message = str(exc).upper()
    transient_markers = ("503", "UNAVAILABLE", "HIGH DEMAND", "SPIKES IN DEMAND", "TEMPORARY", "TIMED OUT")
    return any(marker in message for marker in transient_markers)


@contextmanager
def selected_api_environment(api_key: str | None, api_source: str | None) -> Iterator[None]:
    original_gemini = os.environ.get("GEMINI_API_KEY")
    original_google = os.environ.get("GOOGLE_API_KEY")
    original_xai = os.environ.get("XAI_API_KEY")
    try:
        if api_source == "GEMINI_API_KEY" and api_key:
            os.environ["GEMINI_API_KEY"] = api_key
            os.environ.pop("GOOGLE_API_KEY", None)
        elif api_source == "GOOGLE_API_KEY" and api_key:
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ.pop("GEMINI_API_KEY", None)
        elif api_source == "XAI_API_KEY" and api_key:
            os.environ["XAI_API_KEY"] = api_key
        yield
    finally:
        restore_environment_value("GEMINI_API_KEY", original_gemini)
        restore_environment_value("GOOGLE_API_KEY", original_google)
        restore_environment_value("XAI_API_KEY", original_xai)


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


class GeminiAdapter:
    provider = "gemini"

    def __init__(self, credentials: ProviderCredentials):
        self.credentials = credentials

    def list_models(self, *, refresh: bool = False) -> list[DiscoveredModel]:
        cache_key = (self.provider, self.credentials.api_key)
        if refresh:
            _MODEL_CACHE.pop(cache_key, None)
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

        client = self._get_client()
        with selected_api_environment(self.credentials.api_key, self.credentials.api_source):
            raw_models = list(client.models.list())
        models = [normalize_gemini_model(item) for item in raw_models]
        filtered = [model for model in models if model.capabilities]
        _MODEL_CACHE[cache_key] = tuple(filtered)
        return filtered

    def complete(self, prompt: str, *, model: str, system_instruction: str | None = None) -> str | None:
        client = self._get_client()
        response = None
        if system_instruction:
            try:
                with selected_api_environment(self.credentials.api_key, self.credentials.api_source):
                    from google.genai import types

                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(system_instruction=system_instruction),
                    )
            except Exception as exc:
                if is_transient_ai_error(exc):
                    raise
                response = None
        if response is not None:
            return getattr(response, "text", None)

        combined = prompt if not system_instruction else f"{system_instruction}\n\n{prompt}"
        with selected_api_environment(self.credentials.api_key, self.credentials.api_source):
            response = client.models.generate_content(model=model, contents=combined)
        return getattr(response, "text", None)

    def embed(self, texts: Iterable[str], *, model: str) -> list[list[float]] | None:
        text_list = list(texts)
        if not text_list:
            return []
        client = self._get_client()
        with selected_api_environment(self.credentials.api_key, self.credentials.api_source):
            response = client.models.embed_content(model=model, contents=text_list)
        return [embedding.values for embedding in response.embeddings]

    def _get_client(self):
        cache_key = (self.provider, self.credentials.api_key, self.credentials.api_source)
        cached = _CLIENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        with selected_api_environment(self.credentials.api_key, self.credentials.api_source):
            from google import genai

            client = genai.Client(api_key=self.credentials.api_key)
        _CLIENT_CACHE[cache_key] = client
        return client


class XAIAdapter:
    provider = "xai"
    base_url = "https://api.x.ai/v1"

    def __init__(self, credentials: ProviderCredentials):
        self.credentials = credentials

    def list_models(self, *, refresh: bool = False) -> list[DiscoveredModel]:
        cache_key = (self.provider, self.credentials.api_key)
        if refresh:
            _MODEL_CACHE.pop(cache_key, None)
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

        try:
            payload = fetch_json(
                f"{self.base_url}/language-models",
                headers={"Authorization": f"Bearer {self.credentials.api_key}"},
            )
        except Exception:
            payload = fetch_json(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.credentials.api_key}"},
            )

        models = [normalize_xai_model(item) for item in extract_model_items(payload)]
        filtered = [model for model in models if model.capabilities]
        _MODEL_CACHE[cache_key] = tuple(filtered)
        return filtered

    def complete(self, prompt: str, *, model: str, system_instruction: str | None = None) -> str | None:
        client = self._get_client()
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(model=model, messages=messages)
        return extract_chat_completion_text(response)

    def embed(self, texts: Iterable[str], *, model: str) -> list[list[float]] | None:
        return None

    def _get_client(self):
        cache_key = (self.provider, self.credentials.api_key, self.base_url)
        cached = _CLIENT_CACHE.get(cache_key)
        if cached is not None:
            return cached
        from openai import OpenAI

        client = OpenAI(api_key=self.credentials.api_key, base_url=self.base_url)
        _CLIENT_CACHE[cache_key] = client
        return client


def normalize_gemini_model(raw) -> DiscoveredModel:
    name = extract_attr(raw, "name") or extract_attr(raw, "model") or ""
    model_id = strip_model_prefix(name) or str(name)
    label = extract_attr(raw, "display_name") or extract_attr(raw, "displayName") or model_id
    methods = [
        value.casefold()
        for value in normalize_string_values(
            extract_attr(raw, "supported_actions")
            or extract_attr(raw, "supportedActions")
            or extract_attr(raw, "supported_generation_methods")
            or extract_attr(raw, "supportedGenerationMethods")
            or extract_attr(raw, "supported_methods")
            or extract_attr(raw, "supportedMethods")
            or []
        )
    ]
    capabilities: list[str] = []
    if any("generatecontent" in method or "streamgeneratecontent" in method for method in methods):
        capabilities.append(GENERATION_CAPABILITY)
    if any("embed" in method for method in methods) or "embedding" in model_id.casefold():
        capabilities.append(EMBED_CAPABILITY)
    aliases = tuple(unique_preserving_order([model_id, name] if name else [model_id]))
    modalities = tuple(normalize_string_values(extract_attr(raw, "supported_modalities") or extract_attr(raw, "inputModalities") or []))
    return DiscoveredModel(
        provider="gemini",
        id=model_id,
        label=str(label),
        capabilities=tuple(capabilities),
        modalities=modalities,
        aliases=aliases,
    )


def normalize_xai_model(raw) -> DiscoveredModel:
    name = extract_attr(raw, "id") or extract_attr(raw, "name") or ""
    model_id = str(name)
    label = extract_attr(raw, "display_name") or extract_attr(raw, "displayName") or extract_attr(raw, "name") or model_id
    aliases = normalize_string_values(extract_attr(raw, "aliases") or [])
    modalities = normalize_string_values(
        extract_attr(raw, "modalities")
        or extract_attr(raw, "input_modalities")
        or extract_attr(raw, "inputModalities")
        or []
    )
    return DiscoveredModel(
        provider="xai",
        id=model_id,
        label=str(label),
        capabilities=(GENERATION_CAPABILITY,),
        modalities=tuple(modalities),
        aliases=tuple(unique_preserving_order([model_id, *aliases])),
    )


def extract_model_items(payload) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "models", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def fetch_json(url: str, *, headers: dict[str, str]) -> object:
    req = request.Request(url, headers={**headers, "Accept": "application/json"})
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_chat_completion_text(response) -> str | None:
    choices = getattr(response, "choices", None)
    if not choices and isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        return None
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        return None
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
        return "\n".join(part for part in parts if part).strip() or None
    return None


def extract_attr(value, name: str):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def normalize_string_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)]


def strip_model_prefix(name: str) -> str:
    return name[7:] if name.startswith("models/") else name


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.append(value)
    return seen
