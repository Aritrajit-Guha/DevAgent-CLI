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
        return EditProposal(instruction=instruction, diff=diff.strip(), message="Patch generated.")

    def apply(self, proposal: EditProposal) -> None:
        if not proposal.diff:
            raise ValueError("No diff is available to apply.")
        result = subprocess.run(
            ["git", "apply", "--whitespace=fix", "-"],
            cwd=self.workspace,
            text=True,
            input=proposal.diff,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Failed to apply diff.")
