from __future__ import annotations

from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.core.project import detect_project
from devagent.tools.ai import AIClient


class RepoAgent:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.ai = AIClient.from_env()

    def answer(self, question: str) -> str:
        index = CodeIndexer(self.workspace).load_or_build()
        chunks = Retriever(index).search(question, limit=6)
        project = detect_project(self.workspace)
        context = "\n\n".join(
            f"File: {chunk.path}\nLines: {chunk.start_line}-{chunk.end_line}\n{chunk.text}" for chunk in chunks
        )
        if self.ai.available:
            prompt = (
                "You are DevAgent, a local-first developer assistant. Answer using only the supplied project context. "
                "The user is on Windows. Do not suggest Unix-only commands such as cat, grep, or ls. "
                "Prefer DevAgent commands first, such as `devagent workspace status`, `devagent index`, "
                "`devagent packages`, and `devagent inspect`. If a shell command is truly needed, suggest "
                "`type` for cmd.exe or `Get-Content` for PowerShell. "
                "If the context is insufficient, say what is missing and suggest one Windows-compatible next command.\n\n"
                f"Project types: {', '.join(project.project_types) or 'unknown'}\n"
                f"File tree:\n{chr(10).join(project.file_tree[:80])}\n\n"
                f"Context:\n{context}\n\nQuestion: {question}"
            )
            response = self.ai.complete(prompt)
            if response:
                return response

        if not chunks:
            return "I could not find matching code context. Run `devagent index` and try a more specific question."

        lines = [
            "I found the most relevant project context locally:",
            "",
            *[f"- {chunk.path}:{chunk.start_line}-{chunk.end_line}" for chunk in chunks],
            "",
            "Set GEMINI_API_KEY to enable a synthesized answer over these files.",
        ]
        return "\n".join(lines)
