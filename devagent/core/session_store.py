from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from devagent.config.settings import ConfigManager


@dataclass(frozen=True)
class SessionTurn:
    role: str
    content: str


@dataclass(frozen=True)
class ChatSession:
    summary: str = ""
    turns: list[SessionTurn] = field(default_factory=list)


class SessionStore:
    def __init__(self, workspace: Path, max_turns: int = 8):
        self.workspace = workspace.expanduser().resolve()
        self.max_turns = max_turns
        self.file_path = ConfigManager.workspace_cache_dir(self.workspace) / "chat_session.json"

    def load(self) -> ChatSession:
        if not self.file_path.exists():
            return ChatSession()
        data = json.loads(self.file_path.read_text(encoding="utf-8"))
        turns = [SessionTurn(**item) for item in data.get("turns", [])]
        return ChatSession(summary=str(data.get("summary") or ""), turns=turns)

    def save(self, session: ChatSession) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": session.summary, "turns": [asdict(turn) for turn in session.turns]}
        self.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def clear(self) -> None:
        if self.file_path.exists():
            self.file_path.unlink()

    def append_exchange(self, question: str, answer: str) -> ChatSession:
        session = self.load()
        turns = [*session.turns, SessionTurn("user", question), SessionTurn("assistant", answer)]
        turns = turns[-self.max_turns :]
        updated = ChatSession(summary=self._summarize(turns), turns=turns)
        self.save(updated)
        return updated

    def recent_history(self, limit: int = 4) -> list[SessionTurn]:
        session = self.load()
        return session.turns[-limit:]

    def _summarize(self, turns: list[SessionTurn]) -> str:
        recent_user_topics = [trim_sentence(turn.content) for turn in turns if turn.role == "user"][-3:]
        if not recent_user_topics:
            return ""
        return "Recent user topics: " + " | ".join(recent_user_topics)


def trim_sentence(text: str, limit: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
