import os
import sys
import types

import devagent.tools.ai as ai_module
from devagent.tools.ai import AIClient, resolve_api_credentials, selected_api_environment


def test_resolve_api_credentials_prefers_gemini(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    api_key, source = resolve_api_credentials()

    assert api_key == "gemini-key"
    assert source == "GEMINI_API_KEY"


def test_selected_api_environment_hides_the_other_key(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    with selected_api_environment("gemini-key", "GEMINI_API_KEY"):
        assert os.environ.get("GEMINI_API_KEY") == "gemini-key"
        assert "GOOGLE_API_KEY" not in os.environ

    assert os.environ.get("GOOGLE_API_KEY") == "google-key"
    assert os.environ.get("GEMINI_API_KEY") == "gemini-key"


def test_ai_client_reuses_cached_client_and_keeps_env_silent(monkeypatch) -> None:
    ai_module._CLIENT_CACHE.clear()
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

    client = AIClient(api_key="gemini-key", api_source="GEMINI_API_KEY")

    assert client.complete("hello") == "ok"
    assert client.complete("hello again") == "ok"
    assert client.embed(["one"]) == [[0.1, 0.2]]
    assert client_envs == [("gemini-key", None)]
    assert call_envs == [("gemini-key", None), ("gemini-key", None), ("gemini-key", None)]


def test_ai_client_retries_transient_503_errors(monkeypatch) -> None:
    ai_module._CLIENT_CACHE.clear()
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

    client = AIClient(api_key="gemini-key", api_source="GEMINI_API_KEY")

    assert client.complete("hello") == "ok after retry"
    assert len(attempts) == 3
    assert sleeps == [0.25, 0.75]


def test_ai_client_returns_error_after_repeated_transient_failures(monkeypatch) -> None:
    ai_module._CLIENT_CACHE.clear()
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

    client = AIClient(api_key="gemini-key", api_source="GEMINI_API_KEY")

    message = client.complete("hello")
    assert message is not None
    assert message.startswith("AI request failed:")
    assert len(attempts) == 3
    assert sleeps == [0.25, 0.75]


def test_ai_client_does_not_retry_non_transient_errors(monkeypatch) -> None:
    ai_module._CLIENT_CACHE.clear()
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

    client = AIClient(api_key="gemini-key", api_source="GEMINI_API_KEY")

    message = client.complete("hello")
    assert message is not None
    assert message.startswith("AI request failed:")
    assert len(attempts) == 1
    assert sleeps == []
