from __future__ import annotations

import json
import os
from hashlib import sha256
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderModelConfig:
    model: str | None = None
    deep_model: str | None = None
    embedding_model: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ProviderModelConfig":
        payload = data or {}
        return cls(
            model=payload.get("model"),
            deep_model=payload.get("deep_model"),
            embedding_model=payload.get("embedding_model"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "deep_model": self.deep_model,
            "embedding_model": self.embedding_model,
        }


@dataclass(frozen=True)
class AISettings:
    selected_provider: str | None = None
    providers: dict[str, ProviderModelConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AISettings":
        payload = data or {}
        provider_payload = payload.get("providers") or {}
        return cls(
            selected_provider=payload.get("selected_provider"),
            providers={
                name: ProviderModelConfig.from_dict(config)
                for name, config in provider_payload.items()
                if isinstance(config, dict)
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_provider": self.selected_provider,
            "providers": {name: config.to_dict() for name, config in self.providers.items()},
        }


@dataclass(frozen=True)
class DevAgentConfig:
    workspace_path: Path | None = None
    ai_settings: AISettings = field(default_factory=AISettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DevAgentConfig":
        raw_path = data.get("workspace_path")
        return cls(
            workspace_path=Path(raw_path).expanduser().resolve() if raw_path else None,
            ai_settings=AISettings.from_dict(data.get("ai_settings")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_path": str(self.workspace_path) if self.workspace_path else None,
            "ai_settings": self.ai_settings.to_dict(),
        }


class ConfigManager:
    """Stores lightweight local DevAgent state outside tracked project files."""

    @staticmethod
    def config_dir() -> Path:
        override = os.environ.get("DEVAGENT_CONFIG_DIR")
        if override:
            return Path(override).expanduser().resolve()
        return Path.home() / ".devagent"

    @classmethod
    def config_file(cls) -> Path:
        return cls.config_dir() / "config.json"

    @classmethod
    def workspace_cache_dir(cls, workspace: Path) -> Path:
        resolved = str(workspace.expanduser().resolve())
        digest = sha256(resolved.encode("utf-8")).hexdigest()[:16]
        return cls.config_dir() / "workspaces" / digest

    @classmethod
    def load(cls) -> DevAgentConfig:
        path = cls.config_file()
        if not path.exists():
            return DevAgentConfig()
        return DevAgentConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def save(cls, config: DevAgentConfig) -> None:
        cls.config_dir().mkdir(parents=True, exist_ok=True)
        cls.config_file().write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def bind_workspace(cls, path: Path) -> DevAgentConfig:
        current = cls.load()
        config = DevAgentConfig(
            workspace_path=path.expanduser().resolve(),
            ai_settings=current.ai_settings,
        )
        cls.save(config)
        return config

    @classmethod
    def save_ai_settings(cls, ai_settings: AISettings) -> DevAgentConfig:
        current = cls.load()
        updated = DevAgentConfig(workspace_path=current.workspace_path, ai_settings=ai_settings)
        cls.save(updated)
        return updated
