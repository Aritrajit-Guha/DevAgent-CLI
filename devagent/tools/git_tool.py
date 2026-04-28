from __future__ import annotations

import locale
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from devagent.tools.ai import AIClient

COMMON_PATH_TOKENS = {
    "api",
    "app",
    "build",
    "cli",
    "code",
    "core",
    "devagent",
    "file",
    "files",
    "main",
    "module",
    "project",
    "service",
    "services",
    "src",
    "test",
    "tests",
    "tool",
    "tools",
    "utils",
}
FOCUS_PATTERNS = {
    "Git workflows": {"git", "branch", "merge", "commit", "push", "pull", "pr", "remote"},
    "CLI help": {"help", "cli", "command", "prompt", "shell"},
    "repo chat": {"chat", "agent", "prompt", "retriever", "session"},
    "runtime launch flows": {"runtime", "run", "launch", "browser", "venv"},
    "inspection checks": {"inspect", "insight", "security", "secret", "scan"},
    "workspace setup": {"workspace", "setup", "publish", "clone"},
    "test coverage": {"test", "tests", "pytest"},
}
TOPIC_SCOPE_LABELS = {
    "Git workflows": "guided Git workflows",
    "CLI help": "CLI help catalogs",
    "repo chat": "repo chat answers",
    "runtime launch flows": "runtime launch flows",
    "inspection checks": "inspection checks",
    "workspace setup": "workspace setup flows",
    "test coverage": "regression coverage",
}
SYMBOL_RE = re.compile(
    r"^[+-]\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"^[+-]\s*class\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"^[+-]\s*(?:export\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"^[+-]\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    re.MULTILINE,
)
DIFF_FILE_RE = re.compile(r"^\+\+\+\s+b/(.+)$", re.MULTILINE)
GITHUB_HTTP_RE = re.compile(r"https://github\.com/([^/]+/[^/.]+)(?:\.git)?/?$", re.IGNORECASE)
GITHUB_SSH_RE = re.compile(r"git@github\.com:([^/]+/[^/.]+)(?:\.git)?$", re.IGNORECASE)


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitRemote:
    name: str
    fetch_url: str
    push_url: str
    repo_slug: str | None = None

    @property
    def owner(self) -> str | None:
        if not self.repo_slug or "/" not in self.repo_slug:
            return None
        return self.repo_slug.split("/", 1)[0]


@dataclass(frozen=True)
class CommitSuggestion:
    subject: str
    body: str
    changed_files: tuple[str, ...] = ()
    change_summary: tuple[str, ...] = ()
    impact_summary: tuple[str, ...] = ()
    conventional: bool = True

    @property
    def full_message(self) -> str:
        if not self.body.strip():
            return self.subject
        return f"{self.subject}\n\n{self.body.strip()}"


@dataclass(frozen=True)
class PullOptions:
    remote: str
    branch: str
    rebase: bool = False


@dataclass(frozen=True)
class PullResult:
    local_branch: str
    remote: str
    remote_branch: str
    rebase: bool = False


@dataclass(frozen=True)
class PushOptions:
    remote: str
    local_branch: str
    remote_branch: str
    set_upstream: bool = True
    force_with_lease: bool = False


@dataclass(frozen=True)
class PushResult:
    remote: str
    local_branch: str
    remote_branch: str
    set_upstream: bool = True
    force_with_lease: bool = False


@dataclass(frozen=True)
class PullRequestOptions:
    base_repo: str | None
    base_branch: str
    head_repo: str | None
    head_branch: str
    draft: bool = False
    title: str | None = None
    body: str | None = None


@dataclass(frozen=True)
class ChangeAnalysis:
    files: tuple[str, ...]
    diff: str
    staged_diff: str
    statuses: tuple[str, ...]
    symbols: tuple[str, ...]
    focus_topics: tuple[str, ...]
    key_files: tuple[str, ...]
    prefix: str
    action: str
    scope_label: str
    change_summary: tuple[str, ...]
    impact_summary: tuple[str, ...]


class GitTool:
    def __init__(self, path: Path, ai: AIClient | None = None):
        self.path = path.expanduser().resolve()
        self.ai = ai or AIClient.from_env()

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

    def local_branches(self) -> list[str]:
        result = self._run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], check=False)
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def remotes(self) -> list[GitRemote]:
        result = self._run(["git", "remote", "-v"], check=False)
        if result.returncode != 0:
            return []
        remotes: dict[str, dict[str, str]] = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            name, url, kind = parts[0], parts[1], parts[2].strip("()")
            remotes.setdefault(name, {})
            remotes[name][kind] = url
        ordered: list[GitRemote] = []
        for name in sorted(remotes.keys()):
            urls = remotes[name]
            fetch = urls.get("fetch") or urls.get("push") or ""
            push = urls.get("push") or fetch
            ordered.append(GitRemote(name=name, fetch_url=fetch, push_url=push, repo_slug=parse_github_repo_slug(fetch)))
        return ordered

    def remote_names(self) -> list[str]:
        return [remote.name for remote in self.remotes()]

    def remote_branches(self, remote: str) -> list[str]:
        result = self._run(
            ["git", "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}"],
            check=False,
        )
        if result.returncode != 0:
            return []
        branches: list[str] = []
        prefix = f"{remote}/"
        for line in result.stdout.splitlines():
            value = line.strip()
            if not value or value.endswith("/HEAD") or value.endswith("->"):
                continue
            if value.startswith(prefix):
                value = value[len(prefix) :]
            if value and value not in branches:
                branches.append(value)
        return branches

    def upstream_for(self, branch: str | None = None) -> str | None:
        target = branch or self.current_branch()
        if not target:
            return None
        result = self._run(["git", "rev-parse", "--abbrev-ref", f"{target}@{{upstream}}"], check=False)
        upstream = result.stdout.strip()
        return upstream or None

    def merge_in_progress(self) -> bool:
        result = self._run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"], check=False)
        return result.returncode == 0 and bool(result.stdout.strip())

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

    def pull(self, options: PullOptions | None = None, *, remote: str = "origin", branch: str | None = None, rebase: bool = False) -> PullResult:
        plan = options or PullOptions(remote=remote, branch=branch or self.current_branch() or "", rebase=rebase)
        if not plan.branch:
            raise GitError("Could not determine which branch to pull.")
        args = ["git", "pull", plan.remote, plan.branch]
        if plan.rebase:
            args.insert(2, "--rebase")
        self._run(args)
        return PullResult(
            local_branch=self.current_branch() or plan.branch,
            remote=plan.remote,
            remote_branch=plan.branch,
            rebase=plan.rebase,
        )

    def commit(self, message: str | CommitSuggestion, all_files: bool = False) -> str:
        if all_files:
            self.add_all()
        args = ["git", "commit"]
        if isinstance(message, CommitSuggestion):
            args.extend(["-m", message.subject])
            if message.body.strip():
                args.extend(["-m", message.body.strip()])
        else:
            args.extend(["-m", message])
        self._run(args)
        result = self._run(["git", "rev-parse", "--short", "HEAD"])
        return result.stdout.strip()

    def push(
        self,
        options: PushOptions | None = None,
        *,
        remote: str = "origin",
        branch: str | None = None,
        local_branch: str | None = None,
        remote_branch: str | None = None,
        set_upstream: bool = True,
        force_with_lease: bool = False,
    ) -> PushResult:
        local = local_branch or branch or self.current_branch()
        if not local:
            raise GitError("Could not determine which local branch to push.")
        destination = remote_branch or branch or local
        plan = options or PushOptions(
            remote=remote,
            local_branch=local,
            remote_branch=destination,
            set_upstream=set_upstream,
            force_with_lease=force_with_lease,
        )
        args = ["git", "push"]
        if plan.set_upstream:
            args.append("-u")
        if plan.force_with_lease:
            args.append("--force-with-lease")
        args.extend([plan.remote, f"{plan.local_branch}:{plan.remote_branch}"])
        self._run(args)
        return PushResult(
            remote=plan.remote,
            local_branch=plan.local_branch,
            remote_branch=plan.remote_branch,
            set_upstream=plan.set_upstream,
            force_with_lease=plan.force_with_lease,
        )

    def diff(self, staged: bool = False) -> str:
        args = ["git", "diff", "--cached"] if staged else ["git", "diff"]
        result = self._run(args, check=False)
        return result.stdout or ""

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

    def pr_title(self, *, base_branch: str = "main") -> str:
        return self.suggest_commit(conventional=False).subject

    def pr_body(
        self,
        *,
        base_branch: str = "main",
        base_repo: str | None = None,
        head_repo: str | None = None,
        head_branch: str | None = None,
    ) -> str:
        preview = self.build_pr_preview(
            PullRequestOptions(
                base_repo=base_repo,
                base_branch=base_branch,
                head_repo=head_repo,
                head_branch=head_branch or self.current_branch() or "current-branch",
            )
        )
        return preview.body

    def build_pr_preview(self, options: PullRequestOptions) -> CommitSuggestion:
        suggestion = self.suggest_commit(conventional=False)
        files = self.changed_files_since(options.base_branch) or [normalize_status_path(line) for line in self.changed_files()]
        summary_lines = [
            f"Base repo: `{options.base_repo or 'current gh repo'}`",
            f"Base branch: `{options.base_branch}`",
            f"Head repo: `{options.head_repo or options.base_repo or 'current branch repo'}`",
            f"Head branch: `{options.head_branch}`",
        ]
        if files:
            summary_lines.append("")
            summary_lines.append("Changed files:")
            summary_lines.extend(f"- `{file}`" for file in files[:20])

        stat = self.diff_stat_since(options.base_branch)
        body_sections = ["## Summary", "", *summary_lines]
        if suggestion.change_summary:
            body_sections.extend(["", "## What changed", ""])
            body_sections.extend(f"- {line}" for line in suggestion.change_summary)
        if suggestion.impact_summary:
            body_sections.extend(["", "## Impact", ""])
            body_sections.extend(f"- {line}" for line in suggestion.impact_summary)
        if stat:
            body_sections.extend(["", "## Diff Stat", "", "```text", stat, "```"])

        return CommitSuggestion(
            subject=options.title or suggestion.subject,
            body=options.body or "\n".join(body_sections).strip(),
            changed_files=tuple(files),
            change_summary=suggestion.change_summary,
            impact_summary=suggestion.impact_summary,
            conventional=False,
        )

    def create_pr(
        self,
        *,
        base_branch: str = "main",
        base_repo: str | None = None,
        head_branch: str | None = None,
        head_repo: str | None = None,
        title: str | None = None,
        body: str | None = None,
        draft: bool = False,
    ) -> str:
        options = PullRequestOptions(
            base_repo=base_repo,
            base_branch=base_branch,
            head_repo=head_repo,
            head_branch=head_branch or self.current_branch() or "current-branch",
            draft=draft,
            title=title,
            body=body,
        )
        preview = self.build_pr_preview(options)
        args = ["gh", "pr", "create", "--base", options.base_branch, "--title", preview.subject, "--body", preview.body]
        if options.base_repo:
            args.extend(["--repo", options.base_repo])
        head_value = build_pr_head_value(options.head_repo, options.head_branch, options.base_repo)
        if head_value:
            args.extend(["--head", head_value])
        if options.draft:
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

    def suggest_commit(self, conventional: bool = True) -> CommitSuggestion:
        diff = self.diff(staged=False)
        staged_diff = self.diff(staged=True)
        working_diff = diff or staged_diff or ""
        changed = self.changed_files()
        if not working_diff and not changed:
            subject = "chore: no changes to commit" if conventional else "No changes to commit"
            return CommitSuggestion(subject=subject, body="", conventional=conventional)

        analysis = analyze_changes(changed, working_diff, staged_diff or "")
        fallback = build_deterministic_commit_suggestion(analysis, conventional=conventional)
        refined = self._refine_commit_suggestion_with_ai(analysis, fallback, conventional=conventional)
        return refined or fallback

    def suggest_commit_message(self, conventional: bool = True) -> str:
        return self.suggest_commit(conventional=conventional).full_message

    def _refine_commit_suggestion_with_ai(
        self,
        analysis: ChangeAnalysis,
        fallback: CommitSuggestion,
        *,
        conventional: bool,
    ) -> CommitSuggestion | None:
        if not self.ai.available:
            return None
        prompt = build_commit_prompt(analysis, fallback, conventional=conventional)
        response = self.ai.complete(
            prompt,
            system_instruction=(
                "You write precise Git commit messages for a developer CLI. "
                "Return exactly this shape:\n"
                "SUBJECT: <one line>\n"
                "BODY:\n"
                "- bullet one\n"
                "- bullet two\n"
                "Keep the subject under 72 characters if possible. "
                "Use concrete modules, files, and user-facing effects. "
                "Do not mention tests unless they changed. "
                "If conventional commits are requested, keep the prefix in the subject."
            ),
        )
        if not response or response.startswith("AI request failed:"):
            return None
        return parse_ai_commit_suggestion(response, fallback)

    def _run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                args,
                cwd=self.path,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            if check:
                raise GitError(f"Required command not found: {args[0]}") from exc
            return subprocess.CompletedProcess(args=args, returncode=127, stdout="", stderr=f"Command not found: {args[0]}")
        decoded = subprocess.CompletedProcess(
            args=result.args,
            returncode=result.returncode,
            stdout=decode_process_output(result.stdout),
            stderr=decode_process_output(result.stderr),
        )
        if check and decoded.returncode != 0:
            raise GitError(decoded.stderr.strip() or decoded.stdout.strip() or f"Command failed: {' '.join(args)}")
        return decoded


def normalize_status_path(line: str) -> str:
    return line[3:].strip() if len(line) > 3 else line.strip()


def infer_action(changed: list[str], diff: str | None) -> str:
    diff_text = diff or ""
    statuses = [line[:2] for line in changed]
    if any("A" in status or "??" in status for status in statuses):
        if any(token in diff_text.lower() for token in ("help", "support", "guide")):
            return "document"
        return "add"
    if any("D" in status for status in statuses):
        return "remove"
    lowered = diff_text.lower()
    if re.search(r"test_|describe\(|pytest|unittest", diff_text, re.IGNORECASE):
        return "cover"
    if any(token in lowered for token in ("fix", "bug", "error", "exception", "traceback")):
        return "fix"
    if any(token in lowered for token in ("refactor", "rename", "extract", "cleanup")):
        return "refine"
    if any(token in lowered for token in ("help", "description", "usage", "example")):
        return "improve"
    return "update"


def infer_area(files: list[str]) -> str:
    if not files:
        return "project changes"
    top_levels = [Path(file).parts[0] for file in files if Path(file).parts]
    if not top_levels:
        return "project changes"
    common = top_levels[0] if all(part == top_levels[0] for part in top_levels) else "project"
    return f"{common} changes"


def infer_conventional_prefix(files: list[str], extensions: set[str], diff: str | None) -> str:
    diff_text = (diff or "").lower()
    lowered = " ".join(files).lower()
    if files and all(is_test_path(file) for file in files):
        return "test"
    if files and all(is_docs_path(file) for file in files):
        return "docs"
    if "fix" in diff_text or "bug" in diff_text or "error" in diff_text:
        return "fix"
    if any(status_word in diff_text for status_word in ("add", "create", "new ")):
        return "feat"
    if any(token in lowered for token in ("config", "workflow", ".yml", ".yaml", ".toml")):
        return "chore"
    return "refactor" if any(token in diff_text for token in ("refactor", "cleanup", "rename")) else "chore"


def analyze_changes(changed: list[str], diff: str, staged_diff: str = "") -> ChangeAnalysis:
    files = tuple(normalize_status_path(line) for line in changed)
    statuses = tuple(line[:2].strip() or line[:2] for line in changed)
    extensions = {Path(file).suffix.lower() for file in files}
    action = infer_action(changed, diff)
    prefix = infer_conventional_prefix(list(files), extensions, diff)
    symbols = extract_symbols(diff or staged_diff)
    focus_topics = derive_focus_topics(files, diff, symbols)
    key_files = select_key_files(files)
    scope_label = derive_scope_label(files, focus_topics)
    change_summary = build_change_summary(files, focus_topics, symbols)
    impact_summary = build_impact_summary(focus_topics, files)
    return ChangeAnalysis(
        files=files,
        diff=diff,
        staged_diff=staged_diff,
        statuses=statuses,
        symbols=symbols,
        focus_topics=focus_topics,
        key_files=key_files,
        prefix=prefix,
        action=action,
        scope_label=scope_label,
        change_summary=change_summary,
        impact_summary=impact_summary,
    )


def build_deterministic_commit_suggestion(analysis: ChangeAnalysis, *, conventional: bool) -> CommitSuggestion:
    subject = build_subject_line(analysis, conventional=conventional)
    body = build_commit_body(analysis)
    return CommitSuggestion(
        subject=subject,
        body=body,
        changed_files=analysis.key_files,
        change_summary=analysis.change_summary,
        impact_summary=analysis.impact_summary,
        conventional=conventional,
    )


def build_subject_line(analysis: ChangeAnalysis, *, conventional: bool) -> str:
    action = analysis.action
    scope = analysis.scope_label
    if action == "document":
        phrase = f"document {scope}"
    elif action == "cover":
        phrase = f"cover {scope}"
    elif action == "fix":
        phrase = f"fix {scope}"
    elif action == "refine":
        phrase = f"refine {scope}"
    elif action == "improve":
        phrase = f"improve {scope}"
    elif action == "add":
        phrase = f"add {scope}"
    elif action == "remove":
        phrase = f"remove {scope}"
    else:
        phrase = f"update {scope}"
    phrase = phrase.strip()
    if not conventional:
        return phrase[:1].upper() + phrase[1:]
    return f"{analysis.prefix}: {phrase}"


def build_commit_body(analysis: ChangeAnalysis) -> str:
    bullets: list[str] = []
    bullets.extend(analysis.change_summary)
    bullets.extend(analysis.impact_summary)
    if analysis.key_files:
        if len(analysis.key_files) == 1:
            bullets.append(f"Affects `{analysis.key_files[0]}` directly.")
        else:
            head = ", ".join(f"`{file}`" for file in analysis.key_files[:3])
            bullets.append(f"Affects {head} and related files.")
    return "\n".join(f"- {line}" for line in unique_limited(bullets, 6)).strip()


def derive_focus_topics(files: tuple[str, ...], diff: str, symbols: tuple[str, ...]) -> tuple[str, ...]:
    lowered_files = " ".join(files).lower()
    lowered_diff = diff.lower()
    token_counts: Counter[str] = Counter()
    for file in files:
        token_counts.update(path_tokens(file))
    token_counts.update(symbol.casefold() for symbol in symbols)
    token_counts.update(re.findall(r"[a-z][a-z0-9_-]{2,}", lowered_diff))

    matched_topics: list[str] = []
    for label, triggers in FOCUS_PATTERNS.items():
        if any(trigger in token_counts for trigger in triggers):
            matched_topics.append(label)

    if not matched_topics:
        if any(file.endswith((".md", ".mdx")) for file in files):
            matched_topics.append("documentation")
        elif any("/tests/" in file.lower() or file.lower().startswith("tests/") for file in files):
            matched_topics.append("test coverage")

    if not matched_topics:
        matched_topics.extend(humanize_token(token) for token, _ in token_counts.most_common(2) if token not in COMMON_PATH_TOKENS)
    return tuple(unique_limited(matched_topics, 2)) or ("project changes",)


def derive_scope_label(files: tuple[str, ...], focus_topics: tuple[str, ...]) -> str:
    if not files:
        return "project changes"
    path_context = derive_path_context(files)
    if files and all(is_docs_path(file) for file in files) and path_context:
        return path_context
    recognized = [TOPIC_SCOPE_LABELS[topic] for topic in focus_topics if topic in TOPIC_SCOPE_LABELS]
    if len(recognized) >= 2:
        return f"{recognized[0]} and {recognized[1]}"
    if recognized:
        return recognized[0]
    if path_context:
        return path_context
    if len(focus_topics) == 1:
        return focus_topics[0]
    return f"{focus_topics[0]} and {focus_topics[1]}"


def build_change_summary(files: tuple[str, ...], focus_topics: tuple[str, ...], symbols: tuple[str, ...]) -> tuple[str, ...]:
    summaries: list[str] = []
    primary_files = select_key_files(files)
    if primary_files:
        if len(primary_files) == 1:
            summaries.append(f"Updates `{primary_files[0]}`.")
        else:
            summaries.append(
                f"Updates {', '.join(f'`{file}`' for file in primary_files[:3])} and related files."
            )
    if symbols:
        summaries.append(f"Touches key symbols such as {', '.join(f'`{symbol}`' for symbol in symbols[:4])}.")
    if focus_topics:
        summaries.append(f"Centers the work on {', '.join(topic.casefold() for topic in focus_topics[:2])}.")
    return tuple(unique_limited(summaries, 3))


def build_impact_summary(focus_topics: tuple[str, ...], files: tuple[str, ...]) -> tuple[str, ...]:
    impacts: list[str] = []
    for topic in focus_topics:
        if topic == "Git workflows":
            impacts.append("Makes pull, push, branch, and PR work more explicit for DevAgent users.")
        elif topic == "CLI help":
            impacts.append("Gives users a clearer command catalog and richer nested help pages.")
        elif topic == "repo chat":
            impacts.append("Improves how clearly DevAgent explains repository behavior.")
        elif topic == "runtime launch flows":
            impacts.append("Makes local project startup flows easier to run from the CLI.")
        elif topic == "inspection checks":
            impacts.append("Strengthens repo hygiene and safety feedback.")
        elif topic == "workspace setup":
            impacts.append("Smooths onboarding and workspace setup flows.")
        elif topic == "test coverage":
            impacts.append("Adds stronger regression protection for the updated behavior.")
    if not impacts and files:
        impacts.append(f"Affects {len(files)} changed file(s) across the workspace.")
    return tuple(unique_limited(impacts, 2))


def derive_path_context(files: tuple[str, ...]) -> str | None:
    tokens: list[str] = []
    for file in files[:4]:
        for token in path_tokens(file):
            humanized = humanize_token(token)
            if humanized not in tokens:
                tokens.append(humanized)
    if not tokens:
        for file in files[:4]:
            normalized = file.replace("\\", "/")
            for part in Path(normalized).parts:
                stem = Path(part).stem
                for raw in re.findall(r"[A-Za-z][A-Za-z0-9_]*", stem):
                    humanized = humanize_token(raw.casefold())
                    if humanized not in tokens:
                        tokens.append(humanized)
    if not tokens:
        return None
    if len(tokens) == 1:
        return tokens[0]
    return f"{tokens[0]} and {tokens[1]}"


def select_key_files(files: tuple[str, ...]) -> tuple[str, ...]:
    ordered = sorted(files, key=file_priority)
    return tuple(ordered[:5])


def file_priority(path: str) -> tuple[int, int, str]:
    lowered = path.casefold()
    if lowered.endswith((".md", ".txt")):
        weight = 4
    elif "/tests/" in lowered or lowered.startswith("tests/"):
        weight = 3
    elif lowered.endswith((".yml", ".yaml", ".toml", ".json")):
        weight = 2
    else:
        weight = 1
    return (weight, len(Path(path).parts), lowered)


def extract_symbols(diff: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in SYMBOL_RE.finditer(diff or ""):
        for group in match.groups():
            if group:
                found.append(group)
    return tuple(unique_limited(found, 6))


def path_tokens(path: str) -> list[str]:
    tokens: list[str] = []
    relative = path.replace("\\", "/")
    for part in Path(relative).parts:
        stem = Path(part).stem
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9_]*", stem):
            lowered = raw.casefold()
            if lowered not in COMMON_PATH_TOKENS and len(lowered) > 2:
                tokens.append(lowered)
    return tokens


def humanize_token(token: str) -> str:
    return token.replace("_", " ").replace("-", " ")


def is_docs_path(path: str) -> bool:
    lowered = path.casefold()
    return lowered.endswith((".md", ".mdx", ".rst", ".txt")) or "readme" in lowered


def is_test_path(path: str) -> bool:
    lowered = path.casefold().replace("\\", "/")
    return lowered.startswith("tests/") or "/tests/" in lowered or Path(lowered).name.startswith("test_")


def build_commit_prompt(analysis: ChangeAnalysis, fallback: CommitSuggestion, *, conventional: bool) -> str:
    return (
        f"Conventional commit required: {'yes' if conventional else 'no'}\n"
        f"Fallback subject: {fallback.subject}\n"
        f"Fallback body:\n{fallback.body or '(none)'}\n\n"
        f"Changed files:\n- " + "\n- ".join(analysis.files or ("none",)) + "\n\n"
        f"Focus topics:\n- " + "\n- ".join(analysis.focus_topics or ("project changes",)) + "\n\n"
        f"Key symbols:\n- " + "\n- ".join(analysis.symbols or ("none",)) + "\n\n"
        f"Change summary:\n- " + "\n- ".join(analysis.change_summary or ("none",)) + "\n\n"
        f"Impact summary:\n- " + "\n- ".join(analysis.impact_summary or ("none",)) + "\n\n"
        "Diff excerpt:\n"
        f"{truncate_text(analysis.diff or analysis.staged_diff, 5000)}"
    )


def parse_ai_commit_suggestion(response: str, fallback: CommitSuggestion) -> CommitSuggestion | None:
    subject_match = re.search(r"^SUBJECT:\s*(.+)$", response, re.MULTILINE)
    body_match = re.search(r"^BODY:\s*(.*)$", response, re.MULTILINE | re.DOTALL)
    if not subject_match:
        return None
    subject = subject_match.group(1).strip()
    body = (body_match.group(1) if body_match else "").strip()
    if not subject:
        return None
    return CommitSuggestion(
        subject=subject,
        body=body,
        changed_files=fallback.changed_files,
        change_summary=fallback.change_summary,
        impact_summary=fallback.impact_summary,
        conventional=fallback.conventional,
    )


def build_pr_head_value(head_repo: str | None, head_branch: str, base_repo: str | None) -> str:
    if not head_repo:
        return head_branch
    if base_repo and head_repo == base_repo:
        return head_branch
    owner = head_repo.split("/", 1)[0] if "/" in head_repo else head_repo
    return f"{owner}:{head_branch}"


def parse_github_repo_slug(url: str) -> str | None:
    for pattern in (GITHUB_HTTP_RE, GITHUB_SSH_RE):
        match = pattern.search(url.strip())
        if match:
            return match.group(1)
    return None


def unique_limited(values: list[str], limit: int) -> list[str]:
    seen: list[str] = []
    for value in values:
        compact = " ".join(str(value).split())
        if not compact or compact in seen:
            continue
        seen.append(compact)
        if len(seen) >= limit:
            break
    return seen


def truncate_text(value: str, limit: int) -> str:
    compact = value.strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def decode_process_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value

    preferred = locale.getpreferredencoding(False) or "utf-8"
    for encoding in ("utf-8", preferred):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")
