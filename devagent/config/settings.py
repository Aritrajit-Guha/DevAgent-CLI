from __future__ import annotations

import json
import os
from hashlib import sha256
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DevAgentConfig:
    workspace_path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DevAgentConfig":
        raw_path = data.get("workspace_path")
        return cls(workspace_path=Path(raw_path).expanduser().resolve() if raw_path else None)

    def to_dict(self) -> dict[str, Any]:
        return {"workspace_path": str(self.workspace_path) if self.workspace_path else None}


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
        config = DevAgentConfig(workspace_path=path.expanduser().resolve())
        cls.save(config)
        return config
