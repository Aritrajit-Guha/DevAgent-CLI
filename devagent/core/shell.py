from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.core.agent import RepoAgent
from devagent.core.project import detect_project
from devagent.tools.git_tool import GitTool
from devagent.tools.insights import Inspector
from devagent.tools.node_tool import find_node_packages
from devagent.tools.runtime_tool import LaunchSpec, RunTool


@dataclass(frozen=True)
class ShellResult:
    title: str
    message: str
    tone: str = "info"
    exit_shell: bool = False


def interactive_terminal() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)()) and bool(getattr(sys.stdout, "isatty", lambda: False)())


class AgentShell:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.repo_agent = RepoAgent(self.workspace)
        self.run_tool = RunTool(self.workspace)
        self.deep_mode = False

    def welcome_message(self) -> str:
        project = detect_project(self.workspace)
        saved = self.run_tool.saved_profiles()
        lines = [
            f"Workspace: {self.workspace}",
            f"Project types: {', '.join(project.project_types) or 'unknown'}",
            f"Saved run phrases: {len(saved)}",
            "",
            "Try plain requests like:",
            "- explain the auth flow",
            "- inspect this repo",
            "- show workspace status",
            "- start the app",
            "",
            "Slash commands: /help, /deep, /clear, /workspace, /exit",
        ]
        return "\n".join(lines)

    def handle_input(self, raw_text: str) -> ShellResult | None:
        text = raw_text.strip()
        if not text:
            return None
        if text.startswith("/"):
            return self._handle_slash_command(text)

        matched_profile = self.run_tool.find_profile(text)
        if matched_profile:
            specs = self.run_tool.launch_profile(matched_profile)
            return ShellResult(
                "Saved Run Phrase",
                launch_summary(self.workspace, specs, phrase=matched_profile.phrase, browser_opened=matched_profile.open_browser),
                "success",
            )

        if is_runtime_intent(text):
            open_browser = wants_browser(text)
            specs = self.run_tool.launch_detected(open_browser=open_browser)
            return ShellResult("Runtime Agent", launch_summary(self.workspace, specs, browser_opened=open_browser), "success")

        repo_action = infer_repo_action(text)
        if repo_action == "status":
            return ShellResult("Workspace Status", workspace_status_snapshot(self.workspace), "info")
        if repo_action == "index":
            index = CodeIndexer(self.workspace).build()
            return ShellResult("Index Complete", f"Indexed {len(index.records)} chunks for {self.workspace}.", "success")
        if repo_action == "packages":
            return ShellResult("Package Scan", packages_snapshot(self.workspace), "info")
        if repo_action == "inspect":
            return ShellResult("DevAgent Insights", inspect_snapshot(self.workspace), "info")

        answer = self.repo_agent.answer(text, deep=self.deep_mode)
        return ShellResult("DevAgent", answer, "info")

    def _handle_slash_command(self, text: str) -> ShellResult:
        command = text.strip().casefold()
        if command == "/help":
            return ShellResult(
                "Agent Shell",
                "\n".join(
                    [
                        "Speak naturally and DevAgent will route the request.",
                        "",
                        "Slash commands:",
                        "/help      Show shell controls",
                        "/deep      Toggle deeper answer mode",
                        "/clear     Clear workspace chat memory",
                        "/workspace Show the active workspace",
                        "/exit      Leave the shell",
                    ]
                ),
                "info",
            )
        if command == "/deep":
            self.deep_mode = not self.deep_mode
            state = "enabled" if self.deep_mode else "disabled"
            return ShellResult("Deep Mode", f"Deep repo-answer mode is now {state}.", "success")
        if command == "/clear":
            self.repo_agent.clear_session()
            return ShellResult("Chat Memory Cleared", "Cleared the stored workspace conversation context.", "success")
        if command == "/workspace":
            return ShellResult("Active Workspace", workspace_status_snapshot(self.workspace), "info")
        if command == "/exit":
            return ShellResult("Agent Shell", "See you soon.", "success", exit_shell=True)
        return ShellResult("Agent Shell", f"Unknown shell command: {text}", "warning")


def infer_repo_action(text: str) -> str | None:
    lowered = text.casefold()
    if any(token in lowered for token in ("inspect", "security scan", "scan repo", "check secrets")):
        return "inspect"
    if any(token in lowered for token in ("workspace status", "repo status", "show status", "what changed", "which branch")):
        return "status"
    if lowered in {"status", "show me the status"}:
        return "status"
    if any(token in lowered for token in ("reindex", "build index", "refresh index")) or lowered == "index":
        return "index"
    if any(token in lowered for token in ("packages", "dependencies", "node packages")):
        return "packages"
    return None


def is_runtime_intent(text: str) -> bool:
    lowered = text.casefold().strip()
    runtime_starts = ("start", "run", "launch", "boot", "spin up", "bring up", "open")
    if not lowered.startswith(runtime_starts):
        return False
    return any(token in lowered for token in ("app", "site", "website", "frontend", "backend", "services", "project"))


def wants_browser(text: str) -> bool:
    lowered = text.casefold()
    if any(token in lowered for token in ("no browser", "without browser", "don't open")):
        return False
    return any(token in lowered for token in ("browser", "website", "site", "frontend", "app"))


def workspace_status_snapshot(workspace: Path) -> str:
    project = detect_project(workspace)
    git = GitTool(workspace)
    lines = [
        f"Path: {project.path}",
        f"Project types: {', '.join(project.project_types) or 'unknown'}",
        f"Package files: {', '.join(project.package_files) or 'none'}",
        f"Git repository: {'yes' if git.is_repo else 'no'}",
    ]
    if git.is_repo:
        lines.append(f"Branch: {git.current_branch() or 'unknown'}")
        lines.append(f"Dirty: {'yes' if git.has_changes() else 'no'}")
        changed = git.changed_files()
        lines.append("Changed files: " + (", ".join(changed) if changed else "none"))
    return "\n".join(lines)


def packages_snapshot(workspace: Path) -> str:
    packages = find_node_packages(workspace)
    if not packages:
        return "No package.json dependencies were found in the active workspace."
    lines = []
    current_manifest = None
    for package in packages:
        if package.manifest != current_manifest:
            current_manifest = package.manifest
            if lines:
                lines.append("")
            lines.append(current_manifest)
        lines.append(f"- [{package.section}] {package.name}: {package.version}")
    return "\n".join(lines)


def inspect_snapshot(workspace: Path) -> str:
    findings = Inspector(workspace).run()
    if not findings:
        return "No issues found."
    lines = []
    for finding in findings:
        lines.append(f"[{finding.severity}] {finding.path} - {finding.message}")
    return "\n".join(lines)


def launch_summary(workspace: Path, specs: list[LaunchSpec], *, phrase: str | None = None, browser_opened: bool = False) -> str:
    lines = []
    if phrase:
        lines.append(f"Used saved phrase: {phrase}")
        lines.append("")
    for spec in specs:
        lines.append(f"{spec.name} -> {spec.scope(workspace)}")
        lines.append(f"Command: {spec.display_command}")
        lines.append("")
    if browser_opened:
        preferred_url = next((spec.browser_url for spec in specs if spec.browser_url), None)
        if preferred_url:
            lines.append(f"Opened browser at {preferred_url}")
    return "\n".join(line for line in lines if line is not None).strip()
