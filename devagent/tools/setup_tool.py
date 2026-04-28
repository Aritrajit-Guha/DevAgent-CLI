from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from urllib.parse import urlparse

from devagent.context.scanner import IGNORED_DIRS
from devagent.core.project import detect_project
from devagent.tools.git_tool import GitTool


@dataclass(frozen=True)
class SetupResult:
    path: Path
    message: str


@dataclass(frozen=True)
class DependencyCommand:
    cwd: Path
    command: list[str]

    def display(self, root: Path) -> str:
        relative = self.cwd.relative_to(root).as_posix() if self.cwd != root else "."
        return f"{relative}> {' '.join(self.command)}"


class SetupTool:
    @staticmethod
    def clone_from_github(
        repo_url: str,
        target: Path | None = None,
        *,
        install_deps: bool = False,
        open_code: bool = False,
    ) -> SetupResult:
        clone_url = normalize_github_clone_url(repo_url)
        parent = target.expanduser().resolve() if target else Path.cwd()
        parent.mkdir(parents=True, exist_ok=True)
        repo_name = clone_url.rstrip("/").removesuffix(".git").split("/")[-1]
        destination = parent / repo_name
        run(["git", "clone", clone_url, str(destination)], cwd=parent)

        messages = [f"Cloned {clone_url} to {destination}."]
        project = detect_project(destination)
        if project.project_types:
            messages.append(f"Detected project type: {', '.join(project.project_types)}.")
        dependency_commands = dependency_install_commands(destination)
        if dependency_commands:
            suggestions = "\n".join(command.display(destination) for command in dependency_commands)
            messages.append(f"Suggested dependency commands:\n{suggestions}")
            if install_deps:
                for command in dependency_commands:
                    try:
                        run(command.command, cwd=command.cwd)
                        messages.append(f"Installed dependencies in {command.display(destination).split('>')[0].strip()}.")
                    except RuntimeError as exc:
                        messages.append(f"Dependency install failed in {command.display(destination).split('>')[0].strip()}: {exc}")
        if open_code:
            messages.append(open_in_vscode(destination))
        return SetupResult(path=destination, message="\n".join(messages))

    @staticmethod
    def publish_to_github(path: Path, repo_name: str | None = None, *, private: bool = False, push: bool = True) -> SetupResult:
        workspace = path.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            raise ValueError(f"Project folder does not exist: {workspace}")

        git = GitTool(workspace)
        messages: list[str] = []
        if not git.is_repo:
            git.init()
            messages.append("Initialized Git repository.")

        if git.has_changes():
            git.add_all()
            try:
                git.commit("chore: initial project snapshot")
                messages.append("Created initial commit.")
            except Exception as exc:
                messages.append(f"Skipped initial commit: {exc}")

        final_name = repo_name or workspace.name
        visibility = "--private" if private else "--public"
        command = ["gh", "repo", "create", final_name, visibility, "--source", str(workspace), "--remote", "origin"]
        if push:
            command.append("--push")
        run(command, cwd=workspace)
        messages.append(f"Created GitHub repository {final_name}.")
        if push:
            messages.append("Pushed local branch to GitHub.")
        return SetupResult(path=workspace, message="\n".join(messages))


def normalize_github_clone_url(value: str) -> str:
    if value.startswith("git@") or value.endswith(".git"):
        return value
    parsed = urlparse(value)
    if parsed.netloc.lower() != "github.com":
        return value
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return value
    return f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}.git"


def dependency_install_command(path: Path) -> list[str] | None:
    commands = dependency_install_commands(path, include_nested=False)
    return commands[0].command if commands else None


def dependency_install_commands(path: Path, include_nested: bool = True, max_depth: int = 3) -> list[DependencyCommand]:
    root = path.expanduser().resolve()
    commands: list[DependencyCommand] = []
    candidates = [root]
    if include_nested:
        candidates.extend(sorted(parent for parent in root.rglob("*") if parent.is_dir()))

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate != root:
            relative = candidate.relative_to(root)
            if any(part in IGNORED_DIRS for part in relative.parts):
                continue
            if len(relative.parts) >= max_depth:
                continue
        command = dependency_command_for_directory(candidate)
        if command:
            commands.append(DependencyCommand(cwd=candidate, command=command))
    return commands


def dependency_command_for_directory(path: Path) -> list[str] | None:
    if (path / "package.json").exists():
        if (path / "pnpm-lock.yaml").exists():
            return ["pnpm", "install"]
        if (path / "yarn.lock").exists():
            return ["yarn", "install"]
        return ["npm", "install"]
    if (path / "requirements.txt").exists():
        return ["python", "-m", "pip", "install", "-r", "requirements.txt"]
    if (path / "pyproject.toml").exists():
        return ["python", "-m", "pip", "install", "-e", "."]
    return None


def open_in_vscode(path: Path) -> str:
    result = run(["code", str(path)], cwd=path, check=False)
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip()
        if result.returncode == 127:
            return "Skipped VS Code open because the `code` command is not available in PATH."
        return f"Requested VS Code open, but it reported an issue: {detail or 'unknown error'}."
    return "Requested VS Code open."


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    resolved_args = resolve_command(args)
    try:
        result = subprocess.run(resolved_args, cwd=cwd, text=True, capture_output=True)
    except FileNotFoundError as exc:
        if check:
            raise RuntimeError(f"Required command not found: {args[0]}") from exc
        return subprocess.CompletedProcess(args=args, returncode=127, stdout="", stderr=f"Command not found: {args[0]}")
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {' '.join(args)}")
    return result


def resolve_command(args: list[str]) -> list[str]:
    if not args:
        return args
    resolved = which(args[0])
    if not resolved:
        return args
    return [resolved, *args[1:]]
