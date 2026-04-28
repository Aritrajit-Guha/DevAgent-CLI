from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from devagent.config.settings import ConfigManager
from devagent.context.indexer import CodeIndexer
from devagent.core.agent import RepoAgent
from devagent.core.project import ProjectInfo, detect_project
from devagent.tools.edit_tool import EditAgent, EditProposal
from devagent.tools.git_tool import GitError, GitTool
from devagent.tools.insights import Finding, Inspector
from devagent.tools.node_tool import NodePackage, find_node_packages
from devagent.tools.runtime_tool import LaunchSpec, RunProfile, RunTool
from devagent.tools.setup_tool import SetupResult, SetupTool
from devagent.watcher.file_watcher import WatchService


@dataclass(frozen=True)
class WorkspaceSnapshot:
    project: ProjectInfo
    is_repo: bool
    branch: str | None = None
    dirty: bool = False
    changed_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunInventory:
    detected: list[LaunchSpec]
    profiles: dict[str, RunProfile]


@dataclass(frozen=True)
class RunLaunchResult:
    specs: list[LaunchSpec]
    phrase: str | None = None
    browser_opened: bool = False
    browser_url: str | None = None


@dataclass(frozen=True)
class CommitOutcome:
    commit_id: str
    message: str


@dataclass(frozen=True)
class PullRequestPreview:
    title: str
    body: str


@dataclass(frozen=True)
class MergeConflictDetail:
    path: str
    markers: int


def validate_workspace_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {resolved}")
    return resolved


def bind_workspace_action(path: Path) -> WorkspaceSnapshot:
    resolved = validate_workspace_path(path)
    ConfigManager.bind_workspace(resolved)
    return snapshot_workspace(resolved)


def snapshot_workspace(path: Path) -> WorkspaceSnapshot:
    resolved = path.expanduser().resolve()
    project = detect_project(resolved)
    git = GitTool(resolved)
    changed = git.changed_files() if git.is_repo else []
    return WorkspaceSnapshot(
        project=project,
        is_repo=git.is_repo,
        branch=git.current_branch() if git.is_repo else None,
        dirty=bool(changed),
        changed_files=changed,
    )


class DevAgentActions:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.repo_agent = RepoAgent(self.workspace)
        self.run_tool = RunTool(self.workspace)
        self.git_tool = GitTool(self.workspace)

    def refresh_workspace(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.repo_agent = RepoAgent(self.workspace)
        self.run_tool = RunTool(self.workspace)
        self.git_tool = GitTool(self.workspace)

    def bind_workspace(self, path: Path) -> WorkspaceSnapshot:
        snapshot = bind_workspace_action(path)
        self.refresh_workspace(snapshot.project.path)
        return snapshot

    def workspace_status(self) -> WorkspaceSnapshot:
        return snapshot_workspace(self.workspace)

    def index_workspace(self) -> int:
        index = CodeIndexer(self.workspace).build()
        return len(index.records)

    def chat(self, question: str, *, deep: bool = False, new_session: bool = False) -> str:
        return self.repo_agent.answer(question, deep=deep, new_session=new_session)

    def clear_chat_session(self) -> None:
        self.repo_agent.clear_session()

    def packages(self) -> list[NodePackage]:
        return find_node_packages(self.workspace)

    def inspect(self) -> list[Finding]:
        return Inspector(self.workspace).run()

    def run_inventory(self) -> RunInventory:
        return RunInventory(detected=self.run_tool.detect_launch_specs(), profiles=self.run_tool.saved_profiles())

    def run_start(self, phrase: str | None = None, *, open_browser: bool = True) -> RunLaunchResult:
        specs = self.run_tool.launch_saved(phrase, open_browser=open_browser) if phrase else self.run_tool.launch_detected(open_browser=open_browser)
        browser_url = next((spec.browser_url for spec in specs if spec.browser_url), None) if open_browser else None
        return RunLaunchResult(specs=specs, phrase=phrase, browser_opened=open_browser and browser_url is not None, browser_url=browser_url)

    def run_launch_profile(self, profile: RunProfile, *, open_browser: bool | None = None) -> RunLaunchResult:
        specs = self.run_tool.launch_profile(profile, open_browser=open_browser)
        should_open = profile.open_browser if open_browser is None else open_browser
        browser_url = next((spec.browser_url for spec in specs if spec.browser_url), None) if should_open else None
        return RunLaunchResult(specs=specs, phrase=profile.phrase, browser_opened=should_open and browser_url is not None, browser_url=browser_url)

    def find_run_profile(self, phrase: str) -> RunProfile | None:
        return self.run_tool.find_profile(phrase)

    def save_run_profile(
        self,
        phrase: str,
        *,
        command: str | None = None,
        cwd: Path | None = None,
        open_browser: bool = False,
        description: str | None = None,
    ) -> RunProfile:
        if command:
            return self.run_tool.save_manual_profile(phrase, command, cwd=cwd, open_browser=open_browser, description=description)
        return self.run_tool.save_detected_profile(phrase, open_browser=open_browser, description=description)

    def delete_run_profile(self, phrase: str) -> bool:
        return self.run_tool.delete_profile(phrase)

    def clone_repo(self, repo_url: str, *, target: Path | None = None, install_deps: bool = False, open_code: bool = False) -> SetupResult:
        result = SetupTool.clone_from_github(repo_url, target, install_deps=install_deps, open_code=open_code)
        ConfigManager.bind_workspace(result.path)
        self.refresh_workspace(result.path)
        return result

    def publish_repo(self, path: Path, *, repo_name: str | None = None, private: bool = False, push: bool = True) -> SetupResult:
        result = SetupTool.publish_to_github(path, repo_name=repo_name, private=private, push=push)
        ConfigManager.bind_workspace(result.path)
        self.refresh_workspace(result.path)
        return result

    def edit_propose(self, instruction: str) -> EditProposal:
        return EditAgent(self.workspace).propose(instruction)

    def edit_apply(self, proposal: EditProposal) -> None:
        EditAgent(self.workspace).apply(proposal)

    def git_status(self) -> str:
        return self.git_tool.status_text()

    def git_add(self, path: str = ".") -> None:
        self.git_tool.add(path)

    def git_create_branch(self, name: str) -> None:
        self.git_tool.create_branch(name)

    def git_switch_branch(self, name: str, *, force: bool = False) -> None:
        if self.git_tool.has_changes() and not force:
            raise ValueError("Uncommitted changes exist. Commit/stash them or pass --force.")
        self.git_tool.switch_branch(name)

    def git_commit(self, *, message: str | None = None, all_files: bool = True) -> CommitOutcome:
        final_message = message or self.git_tool.suggest_commit_message()
        commit_id = self.git_tool.commit(final_message, all_files=all_files)
        return CommitOutcome(commit_id=commit_id, message=final_message)

    def git_pull(self, *, remote: str = "origin", branch: str | None = None, rebase: bool = False) -> str:
        self.git_tool.pull(remote=remote, branch=branch, rebase=rebase)
        return branch or self.git_tool.current_branch() or "current branch"

    def git_push(self, *, remote: str = "origin", branch: str | None = None) -> str:
        target_branch = branch or self.git_tool.current_branch()
        self.git_tool.push(remote=remote, branch=target_branch)
        return target_branch or "current branch"

    def pr_preview(self, *, base: str = "main") -> PullRequestPreview:
        return PullRequestPreview(title=self.git_tool.pr_title(), body=self.git_tool.pr_body(base=base))

    def pr_create(
        self,
        *,
        base: str = "main",
        title: str | None = None,
        body: str | None = None,
        draft: bool = False,
    ) -> str:
        return self.git_tool.create_pr(base=base, title=title, body=body, draft=draft)

    def merge_conflicts(self) -> list[MergeConflictDetail]:
        return [MergeConflictDetail(path=file, markers=self.git_tool.conflict_marker_count(file)) for file in self.git_tool.conflict_files()]

    def merge_abort(self) -> None:
        self.git_tool.merge_abort()

    def merge_continue(self) -> None:
        self.git_tool.merge_continue()

    def suggest_commit(self, *, conventional: bool = True) -> str:
        return self.git_tool.suggest_commit_message(conventional=conventional)

    def watch_workspace(self, *, interval: float = 1.0) -> None:
        WatchService(self.workspace, interval=interval).run()
