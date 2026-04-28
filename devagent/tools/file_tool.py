from __future__ import annotations

import difflib
from pathlib import Path


class FileTool:
    """Read-oriented file helper with explicit diff generation for controlled edits."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()

    def resolve(self, relative_path: str) -> Path:
        path = (self.workspace / relative_path).resolve()
        path.relative_to(self.workspace)
        return path

    def read_text(self, relative_path: str) -> str:
        return self.resolve(relative_path).read_text(encoding="utf-8")

    def diff_text(self, relative_path: str, new_text: str) -> str:
        path = self.resolve(relative_path)
        old_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        if new_text and not new_text.endswith("\n"):
            new_lines[-1] = f"{new_lines[-1]}\n"
        return "".join(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
