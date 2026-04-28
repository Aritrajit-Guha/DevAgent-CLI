from __future__ import annotations

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
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")
DOCUMENTATION_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}
PLACEHOLDER_HINTS = (
    "<",
    ">",
    "example",
    "sample",
    "placeholder",
    "replace",
    "your_",
    "your-",
    "username",
    "password",
    "dbname",
    "cluster-url",
    "cluster_name",
    "localhost",
    "127.0.0.1",
)
STRONG_PLACEHOLDER_HINTS = ("<", ">", "your_", "your-", "username", "password", "dbname", "cluster-url", "cluster_name")

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
        security_files = list(iter_security_files(self.workspace))
        if not any(is_env_template_file(path.relative_to(self.workspace).as_posix()) for path in security_files):
            findings.append(Finding("medium", ".env.example", "Missing .env.example for documenting required secrets."))

        git = GitTool(self.workspace)
        tracked_files = git.tracked_files() if git.is_repo else set()
        if git.is_repo and git.has_changes():
            findings.append(Finding("info", ".", "Working tree has uncommitted changes."))

        for path in security_files:
            relative = path.relative_to(self.workspace).as_posix()
            tracked = relative in tracked_files if git.is_repo else False
            ignored = git.is_ignored(relative) if git.is_repo else False
            findings.extend(sensitive_file_findings(relative, tracked=tracked, ignored=ignored))
            if path.stat().st_size > 500_000:
                findings.append(Finding("low", relative, "Large file may slow indexing."))
                continue
            text = read_text_safely(path)
            if not text:
                continue
            findings.extend(secret_findings(relative, text, tracked=tracked, ignored=ignored))
        return sort_findings(findings)


def secret_findings(relative: str, text: str, *, tracked: bool = False, ignored: bool = False) -> list[Finding]:
    if should_skip_secret_scanning(relative, tracked=tracked, ignored=ignored):
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "devagent: ignore-secret" in line:
            continue
        for message, severity, pattern in SECRET_RULES:
            match = pattern.search(line)
            if not match:
                continue
            if is_false_positive_secret_match(relative, line, match.group(0), message):
                continue
            if match:
                findings.append(Finding(severity, f"{relative}:{line_number}", message))
                break
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
    if is_env_template_name(name):
        return False
    return name in SENSITIVE_FILE_NAMES or name.startswith(".env.") or path.suffix.lower() in SENSITIVE_FILE_SUFFIXES


def is_env_template_name(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(".env") and lowered.endswith(ENV_TEMPLATE_SUFFIXES)


def is_env_template_file(relative: str) -> bool:
    return is_env_template_name(Path(relative).name)


def should_skip_secret_scanning(relative: str, *, tracked: bool, ignored: bool) -> bool:
    name = Path(relative).name.lower()
    if is_env_template_name(name):
        return True
    if name.startswith(".env") and ignored and not tracked:
        return True
    return False


def is_false_positive_secret_match(relative: str, line: str, matched: str, message: str) -> bool:
    if message == "Mongo connection string exposed":
        return looks_like_example_secret(relative, line, matched)
    return False


def looks_like_example_secret(relative: str, line: str, matched: str) -> bool:
    suffix = Path(relative).suffix.lower()
    lower_line = line.lower()
    lower_match = matched.lower()
    if suffix in DOCUMENTATION_SUFFIXES and any(hint in lower_line for hint in PLACEHOLDER_HINTS):
        return True
    return any(hint in lower_match for hint in STRONG_PLACEHOLDER_HINTS)


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
