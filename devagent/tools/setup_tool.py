from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from devagent.core.project import detect_project
from devagent.tools.git_tool import GitTool


@dataclass(frozen=True)
class SetupResult:
    path: Path
    message: str


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
        dependency_command = dependency_install_command(destination)
        if dependency_command:
            messages.append(f"Suggested dependency command: {' '.join(dependency_command)}.")
            if install_deps:
                run(dependency_command, cwd=destination)
                messages.append("Installed dependencies.")
        if open_code:
            run(["code", str(destination)], cwd=destination, check=False)
            messages.append("Requested VS Code open.")
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


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {' '.join(args)}")
    return result
