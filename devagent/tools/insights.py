from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from devagent.context.scanner import iter_source_files, read_text_safely
from devagent.tools.git_tool import GitTool


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{6,}['\"]"),
]


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    message: str


class Inspector:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()

    def run(self) -> list[Finding]:
        findings: list[Finding] = []
        if not (self.workspace / ".env.example").exists():
            findings.append(Finding("medium", ".env.example", "Missing .env.example for documenting required secrets."))

        git = GitTool(self.workspace)
        if git.is_repo and git.has_changes():
            findings.append(Finding("info", ".", "Working tree has uncommitted changes."))

        for path in iter_source_files(self.workspace):
            relative = path.relative_to(self.workspace).as_posix()
            if path.stat().st_size > 500_000:
                findings.append(Finding("low", relative, "Large file may slow indexing."))
                continue
            text = read_text_safely(path)
            if not text:
                continue
            findings.extend(secret_findings(relative, text))
            if path.suffix == ".py":
                findings.extend(python_function_findings(relative, text))
        return findings


def secret_findings(relative: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "devagent: ignore-secret" in line:
            continue
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            findings.append(Finding("high", f"{relative}:{line_number}", "Possible hardcoded secret or password string."))
    return findings


def python_function_findings(relative: str, text: str, max_lines: int = 100) -> list[Finding]:
    findings: list[Finding] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and hasattr(node, "end_lineno"):
            length = int(node.end_lineno or node.lineno) - node.lineno + 1
            if length > max_lines:
                findings.append(Finding("low", f"{relative}:{node.lineno}", f"Large function `{node.name}` has {length} lines."))
    return findings
