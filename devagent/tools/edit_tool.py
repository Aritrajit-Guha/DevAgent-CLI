from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.tools.ai import AIClient


@dataclass(frozen=True)
class EditProposal:
    instruction: str
    diff: str | None
    message: str


class EditAgent:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.ai = AIClient.from_env()

    def propose(self, instruction: str) -> EditProposal:
        index = CodeIndexer(self.workspace).load_or_build()
        chunks = Retriever(index).search(instruction, limit=8)
        context = "\n\n".join(
            f"File: {chunk.path}\nLines: {chunk.start_line}-{chunk.end_line}\n{chunk.text}" for chunk in chunks
        )
        if not self.ai.available:
            files = "\n".join(f"- {chunk.path}:{chunk.start_line}-{chunk.end_line}" for chunk in chunks)
            return EditProposal(
                instruction=instruction,
                diff=None,
                message=(
                    "Gemini is not configured, so I will not invent a patch. "
                    "Set GEMINI_API_KEY and rerun this command.\n\nRelevant files:\n"
                    f"{files or 'No relevant files found.'}"
                ),
            )

        prompt = (
            "You are a careful coding agent. Produce only a valid unified diff that can be applied with git apply. "
            "Do not include Markdown fences or explanations. Keep changes minimal and scoped to the instruction. "
            "If the context is insufficient, output exactly: NO_PATCH\n\n"
            f"Instruction: {instruction}\n\nContext:\n{context}"
        )
        diff = self.ai.complete(prompt)
        if not diff or diff.strip() == "NO_PATCH" or "AI request failed:" in diff:
            return EditProposal(instruction=instruction, diff=None, message=diff or "No patch generated.")
        clean_diff = sanitize_unified_diff(diff)
        if not clean_diff:
            return EditProposal(instruction=instruction, diff=None, message="No valid unified diff was generated.")
        return EditProposal(instruction=instruction, diff=clean_diff, message="Patch generated.")

    def apply(self, proposal: EditProposal) -> None:
        if not proposal.diff:
            raise ValueError("No diff is available to apply.")
        result = subprocess.run(
            ["git", "apply", "--whitespace=fix", "-"],
            cwd=self.workspace,
            input=proposal.diff.encode("utf-8"),
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or stdout or "Failed to apply diff.")


def sanitize_unified_diff(raw: str) -> str | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start_markers = ("diff --git ", "--- a/", "--- /", "Index: ")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(start_markers):
            cleaned = "\n".join(lines[index:]).strip()
            return f"{cleaned}\n" if cleaned else None
    return None
