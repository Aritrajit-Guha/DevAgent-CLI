from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from devagent.context.scanner import IGNORED_DIRS, read_text_safely
from devagent.tools.git_tool import GitTool


SECRET_RULES = [
    ("Private key block", "high", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS access key exposed", "high", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("GitHub token exposed", "high", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Slack token exposed", "high", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("JWT-like token exposed", "high", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9._-]{8,}\.[A-Za-z0-9._-]{8,}\b")),
    ("Mongo connection string exposed", "high", re.compile(r"mongodb(?:\+srv)?:\/\/[^\s'\"`]+")),
    ("Database URL exposed", "high", re.compile(r"(?i)\b(?:database_url|db_url)\b\s*[:=]\s*['\"][^'\"]+['\"]")),
    (
        "Possible hardcoded secret or token",
        "high",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|client[_-]?secret|jwt[_-]?secret|aws[_-]?secret[_-]?access[_-]?key)"
            r"\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
    ),
    ("Possible hardcoded password", "high", re.compile(r"(?i)\b(?:password|passwd|pwd)\b\s*[:=]\s*['\"][^'\"]{6,}['\"]")),
    (
        "Hardcoded backend or API URL",
        "medium",
        re.compile(r"(?i)\b(?:api|backend|base[_-]?url|server[_-]?url)\b\s*[:=]\s*['\"]https?://[^'\"]+['\"]"),
    ),
]

SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".npmrc",
    ".yarnrc",
}
ENV_TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template"}

SENSITIVE_FILE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".p8"}
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".mp4",
    ".mp3",
    ".woff",
    ".woff2",
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


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
        tracked_files = git.tracked_files() if git.is_repo else set()
        if git.is_repo and git.has_changes():
            findings.append(Finding("info", ".", "Working tree has uncommitted changes."))

        for path in iter_security_files(self.workspace):
            relative = path.relative_to(self.workspace).as_posix()
            findings.extend(sensitive_file_findings(relative, tracked=relative in tracked_files, ignored=git.is_ignored(relative) if git.is_repo else False))
            if path.stat().st_size > 500_000:
                findings.append(Finding("low", relative, "Large file may slow indexing."))
                continue
            text = read_text_safely(path)
            if not text:
                continue
            findings.extend(secret_findings(relative, text))
            if path.suffix == ".py":
                findings.extend(python_function_findings(relative, text))
        return sort_findings(findings)


def secret_findings(relative: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "devagent: ignore-secret" in line:
            continue
        for message, severity, pattern in SECRET_RULES:
            if pattern.search(line):
                findings.append(Finding(severity, f"{relative}:{line_number}", message))
                break
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


def sensitive_file_findings(relative: str, tracked: bool, ignored: bool) -> list[Finding]:
    if not is_sensitive_file(relative):
        return []
    if tracked:
        return [Finding("high", relative, "Sensitive file is tracked by Git and may be pushed to the remote repository.")]
    if not ignored:
        return [Finding("high", relative, "Sensitive file exists but is not ignored by Git.")]
    return []


def is_sensitive_file(relative: str) -> bool:
    path = Path(relative)
    name = path.name.lower()
    if name in ENV_TEMPLATE_NAMES:
        return False
    return name in SENSITIVE_FILE_NAMES or name.startswith(".env.") or path.suffix.lower() in SENSITIVE_FILE_SUFFIXES


def iter_security_files(root: Path):
    resolved = root.expanduser().resolve()
    for path in sorted(resolved.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(resolved)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES and not is_sensitive_file(relative.as_posix()):
            continue
        yield path


def sort_findings(findings: list[Finding]) -> list[Finding]:
    unique: dict[tuple[str, str, str], Finding] = {}
    for finding in findings:
        unique[(finding.severity, finding.path, finding.message)] = finding
    return sorted(unique.values(), key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.path, item.message))
