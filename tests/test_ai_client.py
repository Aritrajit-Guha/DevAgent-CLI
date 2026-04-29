import os
import sys
import types
from pathlib import Path

import devagent.tools.ai as ai_module
from devagent.config.settings import AISettings, ConfigManager, ProviderModelConfig
from devagent.tools.ai import AIClient, resolve_api_credentials, selected_api_environment


def _clear_ai_caches() -> None:
    ai_module._CLIENT_CACHE.clear()
    ai_module._MODEL_CACHE.clear()


def test_resolve_api_credentials_prefers_gemini_over_google_and_xai(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")

    api_key, source = resolve_api_credentials()

    assert api_key == "gemini-key"
    assert source == "GEMINI_API_KEY"
    assert resolve_api_credentials("xai") == ("xai-key", "XAI_API_KEY")


def test_selected_api_environment_hides_the_other_google_key(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    with selected_api_environment("gemini-key", "GEMINI_API_KEY"):
        assert os.environ.get("GEMINI_API_KEY") == "gemini-key"
        assert "GOOGLE_API_KEY" not in os.environ

    assert os.environ.get("GOOGLE_API_KEY") == "google-key"
    assert os.environ.get("GEMINI_API_KEY") == "gemini-key"


def test_ai_client_reuses_cached_gemini_client_and_keeps_env_silent(monkeypatch) -> None:
    _clear_ai_caches()
    client_envs: list[tuple[str | None, str | None]] = []
    call_envs: list[tuple[str | None, str | None]] = []

    class FakeResponse:
        text = "ok"

    class FakeModels:
        def generate_content(self, **kwargs):
            call_envs.append((os.environ.get("GEMINI_API_KEY"), os.environ.get("GOOGLE_API_KEY")))
            return FakeResponse()

        def embed_content(self, **kwargs):
            call_envs.append((os.environ.get("GEMINI_API_KEY"), os.environ.get("GOOGLE_API_KEY")))
            return types.SimpleNamespace(embeddings=[types.SimpleNamespace(values=[0.1, 0.2])])

    class FakeClient:
        def __init__(self, api_key=None):
            client_envs.append((os.environ.get("GEMINI_API_KEY"), os.environ.get("GOOGLE_API_KEY")))
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

    client = AIClient(provider="gemini", api_key="gemini-key", api_source="GEMINI_API_KEY", available_providers=("gemini",))

    assert client.complete("hello") == "ok"
    assert client.complete("hello again") == "ok"
    assert client.embed(["one"]) == [[0.1, 0.2]]
    assert client_envs == [("gemini-key", None)]
    assert call_envs == [("gemini-key", None), ("gemini-key", None), ("gemini-key", None)]


def test_ai_client_retries_transient_503_errors(monkeypatch) -> None:
    _clear_ai_caches()
    attempts: list[int] = []
    sleeps: list[float] = []

    class FakeResponse:
        text = "ok after retry"

    class FakeModels:
        def generate_content(self, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setattr(ai_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    client = AIClient(provider="gemini", api_key="gemini-key", api_source="GEMINI_API_KEY", available_providers=("gemini",))

    assert client.complete("hello") == "ok after retry"
    assert len(attempts) == 3
    assert sleeps == [0.25, 0.75]


def test_ai_client_returns_error_after_repeated_transient_failures(monkeypatch) -> None:
    _clear_ai_caches()
    attempts: list[int] = []
    sleeps: list[float] = []

    class FakeModels:
        def generate_content(self, **kwargs):
            attempts.append(1)
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setattr(ai_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    client = AIClient(provider="gemini", api_key="gemini-key", api_source="GEMINI_API_KEY", available_providers=("gemini",))

    message = client.complete("hello")
    assert message is not None
    assert message.startswith("AI request failed:")
    assert len(attempts) == 3
    assert sleeps == [0.25, 0.75]


def test_ai_client_does_not_retry_non_transient_errors(monkeypatch) -> None:
    _clear_ai_caches()
    attempts: list[int] = []
    sleeps: list[float] = []

    class FakeModels:
        def generate_content(self, **kwargs):
            attempts.append(1)
            raise RuntimeError("400 INVALID_ARGUMENT")

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)

    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setattr(ai_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    client = AIClient(provider="gemini", api_key="gemini-key", api_source="GEMINI_API_KEY", available_providers=("gemini",))

    message = client.complete("hello")
    assert message is not None
    assert message.startswith("AI request failed:")
    assert len(attempts) == 1
    assert sleeps == []


def test_ai_client_uses_saved_xai_provider_selection(tmp_path: Path, monkeypatch) -> None:
    _clear_ai_caches()
    monkeypatch.setenv("DEVAGENT_CONFIG_DIR", str(tmp_path / "config-home"))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("XAI_API_KEY", "xai-key")
    ConfigManager.save_ai_settings(
        AISettings(
            selected_provider="xai",
            providers={"xai": ProviderModelConfig(model="grok-3-mini", deep_model="grok-3-mini")},
        )
    )

    client = AIClient.from_env()

    assert client.provider == "xai"
    assert client.fast_model == "grok-3-mini"
    assert client.deep_model == "grok-3-mini"
    assert client.embedding_model is None


def test_bind_workspace_preserves_saved_ai_settings(tmp_path: Path, monkeypatch) -> None:
    _clear_ai_caches()
    monkeypatch.setenv("DEVAGENT_CONFIG_DIR", str(tmp_path / "config-home"))
    ConfigManager.save_ai_settings(
        AISettings(
            selected_provider="gemini",
            providers={"gemini": ProviderModelConfig(model="gemini-2.5-flash")},
        )
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    ConfigManager.bind_workspace(workspace)
    config = ConfigManager.load()

    assert config.workspace_path == workspace.resolve()
    assert config.ai_settings.selected_provider == "gemini"
    assert config.ai_settings.providers["gemini"].model == "gemini-2.5-flash"


def test_ai_client_filters_gemini_generation_and_embedding_models(monkeypatch) -> None:
    _clear_ai_caches()

    class FakeModels:
        def list(self):
            return [
                types.SimpleNamespace(
                    name="models/gemini-2.5-flash",
                    display_name="Gemini 2.5 Flash",
                    supported_generation_methods=["generateContent", "countTokens"],
                ),
                types.SimpleNamespace(
                    name="models/gemini-embedding-001",
                    display_name="Gemini Embedding",
                    supported_generation_methods=["embedContent"],
                ),
            ]

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", fake_google)

    client = AIClient(provider="gemini", api_key="gemini-key", api_source="GEMINI_API_KEY", available_providers=("gemini",))
    models = client.list_models(provider="gemini", refresh=True)

    assert [(model.id, model.capabilities) for model in models] == [
        ("gemini-2.5-flash", ("generate",)),
        ("gemini-embedding-001", ("embed",)),
    ]


def test_ai_client_filters_gemini_models_from_supported_actions_shape(monkeypatch) -> None:
    _clear_ai_caches()

    class FakeModels:
        def list(self):
            return [
                {
                    "name": "models/gemini-2.5-flash",
                    "display_name": "Gemini 2.5 Flash",
                    "supported_actions": ["generateContent", "countTokens"],
                },
                {
                    "name": "models/gemini-2.5-pro",
                    "display_name": "Gemini 2.5 Pro",
                    "supported_actions": ["generateContent"],
                },
                {
                    "name": "models/gemini-embedding-001",
                    "display_name": "Gemini Embedding 001",
                    "supported_actions": ["embedContent"],
                },
            ]

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", fake_google)

    client = AIClient(provider="gemini", api_key="gemini-key", api_source="GEMINI_API_KEY", available_providers=("gemini",))
    models = client.list_models(provider="gemini", refresh=True)

    assert [(model.id, model.capabilities) for model in models] == [
        ("gemini-2.5-flash", ("generate",)),
        ("gemini-2.5-pro", ("generate",)),
        ("gemini-embedding-001", ("embed",)),
    ]


def test_ai_client_lists_xai_models_from_language_models_endpoint(monkeypatch) -> None:
    _clear_ai_caches()
    monkeypatch.setattr(
        ai_module,
        "fetch_json",
        lambda url, headers: {
            "data": [
                {"id": "grok-3-mini", "name": "Grok 3 Mini"},
                {"id": "grok-3-fast", "display_name": "Grok 3 Fast"},
            ]
        },
    )

    client = AIClient(provider="xai", api_key="xai-key", api_source="XAI_API_KEY", available_providers=("xai",))
    models = client.list_models(provider="xai", refresh=True)

    assert [model.id for model in models] == ["grok-3-mini", "grok-3-fast"]
    assert all(model.capabilities == ("generate",) for model in models)


def test_ai_client_uses_xai_chat_completion_path(monkeypatch) -> None:
    _clear_ai_caches()
    captured: list[dict[str, object]] = []

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured.append(kwargs)
            return types.SimpleNamespace(
                choices=[
                    types.SimpleNamespace(message=types.SimpleNamespace(content="xai says hi"))
                ]
            )

    class FakeOpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.chat = types.SimpleNamespace(completions=FakeChatCompletions())

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    client = AIClient(provider="xai", api_key="xai-key", api_source="XAI_API_KEY", fast_model="grok-3-mini", available_providers=("xai",))

    assert client.complete("hello", system_instruction="Be helpful") == "xai says hi"
    assert captured == [
        {
            "model": "grok-3-mini",
            "messages": [
                {"role": "system", "content": "Be helpful"},
                {"role": "user", "content": "hello"},
            ],
        }
    ]


def test_ai_client_status_warns_and_falls_back_when_saved_model_is_missing(tmp_path: Path, monkeypatch) -> None:
    _clear_ai_caches()
    monkeypatch.setenv("DEVAGENT_CONFIG_DIR", str(tmp_path / "config-home"))
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    ConfigManager.save_ai_settings(
        AISettings(
            selected_provider="gemini",
            providers={"gemini": ProviderModelConfig(model="ghost-model", deep_model="ghost-deep", embedding_model="ghost-embed")},
        )
    )

    class FakeModels:
        def list(self):
            return [
                types.SimpleNamespace(
                    name="models/gemini-2.5-flash",
                    display_name="Gemini 2.5 Flash",
                    supported_generation_methods=["generateContent"],
                ),
                types.SimpleNamespace(
                    name="models/gemini-2.5-pro",
                    display_name="Gemini 2.5 Pro",
                    supported_generation_methods=["generateContent"],
                ),
                types.SimpleNamespace(
                    name="models/gemini-embedding-001",
                    display_name="Gemini Embedding",
                    supported_generation_methods=["embedContent"],
                ),
            ]

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    fake_google = types.ModuleType("google")
    fake_google.genai = types.SimpleNamespace(Client=FakeClient)
    monkeypatch.setitem(sys.modules, "google", fake_google)

    status = AIClient.from_env().provider_status(refresh=True)

    assert status.selected_provider == "gemini"
    assert status.fast_model == "gemini-2.5-flash"
    assert status.deep_model == "gemini-2.5-pro"
    assert status.embedding_model == "gemini-embedding-001"
    assert any("ghost-model" in warning for warning in status.warnings)
    assert any("ghost-deep" in warning for warning in status.warnings)
    assert any("ghost-embed" in warning for warning in status.warnings)


def test_xai_embed_returns_none_without_embedding_support() -> None:
    client = AIClient(provider="xai", api_key="xai-key", api_source="XAI_API_KEY", embedding_model=None, available_providers=("xai",))

    assert client.embed(["hello"]) is None
