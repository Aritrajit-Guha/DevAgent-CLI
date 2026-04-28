from __future__ import annotations

import re
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


class GitTool:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()

    @property
    def is_repo(self) -> bool:
        result = self._run(["git", "rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def init(self) -> None:
        self._run(["git", "init"])

    def add(self, *paths: str) -> None:
        targets = list(paths) or ["."]
        self._run(["git", "add", *targets])

    def current_branch(self) -> str | None:
        result = self._run(["git", "branch", "--show-current"], check=False)
        branch = result.stdout.strip()
        return branch or None

    def has_changes(self) -> bool:
        return bool(self.changed_files())

    def changed_files(self) -> list[str]:
        result = self._run(["git", "status", "--short"], check=False)
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def tracked_files(self) -> set[str]:
        result = self._run(["git", "ls-files"], check=False)
        if result.returncode != 0:
            return set()
        return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}

    def is_ignored(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/")
        result = self._run(["git", "check-ignore", "-q", normalized], check=False)
        return result.returncode == 0

    def status_text(self) -> str:
        if not self.is_repo:
            return "This workspace is not a Git repository."
        result = self._run(["git", "status", "--short", "--branch"])
        return result.stdout.strip() or "Clean working tree."

    def create_branch(self, name: str) -> None:
        self._run(["git", "checkout", "-b", name])

    def switch_branch(self, name: str) -> None:
        self._run(["git", "checkout", name])

    def add_all(self) -> None:
        self._run(["git", "add", "."])

    def pull(self, remote: str = "origin", branch: str | None = None, rebase: bool = False) -> None:
        target = branch or self.current_branch()
        if not target:
            raise GitError("Could not determine current branch.")
        args = ["git", "pull", remote, target]
        if rebase:
            args.insert(2, "--rebase")
        self._run(args)

    def commit(self, message: str, all_files: bool = False) -> str:
        if all_files:
            self.add_all()
        self._run(["git", "commit", "-m", message])
        result = self._run(["git", "rev-parse", "--short", "HEAD"])
        return result.stdout.strip()

    def push(self, remote: str = "origin", branch: str | None = None) -> None:
        target = branch or self.current_branch()
        if not target:
            raise GitError("Could not determine current branch.")
        self._run(["git", "push", "-u", remote, target])

    def diff(self, staged: bool = False) -> str:
        args = ["git", "diff", "--cached"] if staged else ["git", "diff"]
        result = self._run(args, check=False)
        return result.stdout

    def conflict_files(self) -> list[str]:
        result = self._run(["git", "diff", "--name-only", "--diff-filter=U"], check=False)
        if result.returncode != 0:
            return []
        return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]

    def has_conflicts(self) -> bool:
        return bool(self.conflict_files())

    def merge_abort(self) -> None:
        self._run(["git", "merge", "--abort"])

    def merge_continue(self) -> None:
        self._run(["git", "merge", "--continue"])

    def conflict_marker_count(self, relative_path: str) -> int:
        path = self.path / relative_path
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return 0
        return sum(1 for line in text.splitlines() if line.startswith("<<<<<<<"))

    def pr_title(self) -> str:
        return self.suggest_commit_message(conventional=False)

    def pr_body(self, base: str = "main") -> str:
        branch = self.current_branch() or "current-branch"
        files = self.changed_files_since(base)
        if not files:
            files = [normalize_status_path(line) for line in self.changed_files()]
        lines = [f"## Summary", "", f"- Branch: `{branch}`", ""]
        if files:
            lines.append("## Changed Files")
            lines.append("")
            lines.extend(f"- `{file}`" for file in files[:20])
            lines.append("")
        stat = self.diff_stat_since(base)
        if stat:
            lines.append("## Diff Stat")
            lines.append("")
            lines.append("```text")
            lines.append(stat)
            lines.append("```")
        return "\n".join(lines).strip()

    def create_pr(self, base: str = "main", title: str | None = None, body: str | None = None, draft: bool = False) -> str:
        pr_title = title or self.pr_title()
        pr_body = body or self.pr_body(base=base)
        args = ["gh", "pr", "create", "--base", base, "--title", pr_title, "--body", pr_body]
        if draft:
            args.append("--draft")
        result = self._run(args)
        return result.stdout.strip()

    def changed_files_since(self, base: str = "main") -> list[str]:
        result = self._run(["git", "diff", "--name-only", f"{base}...HEAD"], check=False)
        if result.returncode != 0:
            return []
        return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]

    def diff_stat_since(self, base: str = "main") -> str:
        result = self._run(["git", "diff", "--stat", f"{base}...HEAD"], check=False)
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def suggest_commit_message(self, conventional: bool = True) -> str:
        diff = self.diff(staged=False) or self.diff(staged=True)
        changed = self.changed_files()
        if not diff and not changed:
            return "chore: no changes to commit" if conventional else "No changes to commit"

        files = [normalize_status_path(line) for line in changed]
        extensions = {Path(file).suffix for file in files}
        action = infer_action(changed, diff)
        area = infer_area(files)
        prefix = infer_conventional_prefix(files, extensions, diff)
        message = f"{action} {area}".strip()
        if conventional:
            return f"{prefix}: {message}"
        return message[:1].upper() + message[1:]

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(args, cwd=self.path, text=True, capture_output=True)
        except FileNotFoundError as exc:
            if check:
                raise GitError(f"Required command not found: {args[0]}") from exc
            return subprocess.CompletedProcess(args=args, returncode=127, stdout="", stderr=f"Command not found: {args[0]}")
        if check and result.returncode != 0:
            raise GitError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {' '.join(args)}")
        return result


def normalize_status_path(line: str) -> str:
    return line[3:].strip() if len(line) > 3 else line.strip()


def infer_action(changed: list[str], diff: str) -> str:
    statuses = [line[:2] for line in changed]
    if any("A" in status or "??" in status for status in statuses):
        return "add"
    if any("D" in status for status in statuses):
        return "remove"
    if re.search(r"test_|describe\(|pytest|unittest", diff, re.IGNORECASE):
        return "update tests for"
    return "update"


def infer_area(files: list[str]) -> str:
    if not files:
        return "project changes"
    top_levels = [Path(file).parts[0] for file in files if Path(file).parts]
    if not top_levels:
        return "project changes"
    common = top_levels[0] if all(part == top_levels[0] for part in top_levels) else "project"
    return f"{common} changes"


def infer_conventional_prefix(files: list[str], extensions: set[str], diff: str) -> str:
    lowered = " ".join(files).lower()
    if "test" in lowered or "tests" in lowered:
        return "test"
    if ".md" in extensions or "readme" in lowered:
        return "docs"
    if "fix" in diff.lower() or "bug" in diff.lower():
        return "fix"
    if any(status_word in diff.lower() for status_word in ("add", "create", "new ")):
        return "feat"
    return "chore"
