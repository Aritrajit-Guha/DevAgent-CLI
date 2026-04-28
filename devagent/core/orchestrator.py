from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devagent.core.agent import RepoAgent
from devagent.tools.git_tool import GitTool


@dataclass(frozen=True)
class OrchestratorResult:
    kind: str
    message: str


class AgentOrchestrator:
    """Small decision layer for routing natural language to safe local actions."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()

    def handle(self, request: str) -> OrchestratorResult:
        lowered = request.strip().lower()
        if lowered in {"git status", "status"}:
            return OrchestratorResult(kind="git", message=GitTool(self.workspace).status_text())
        if lowered.startswith("commit message") or lowered.startswith("suggest commit"):
            return OrchestratorResult(kind="commit", message=GitTool(self.workspace).suggest_commit_message())
        return OrchestratorResult(kind="chat", message=RepoAgent(self.workspace).answer(request))
