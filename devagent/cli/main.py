from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from devagent.cli.prompts import choose_directory
from devagent.config.settings import ConfigManager
from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.core.agent import RepoAgent
from devagent.core.project import detect_project
from devagent.tools.edit_tool import EditAgent
from devagent.tools.git_tool import GitTool
from devagent.tools.insights import Inspector
from devagent.tools.node_tool import find_node_packages
from devagent.tools.setup_tool import SetupTool
from devagent.watcher.file_watcher import WatchService

app = typer.Typer(help="Local-first agentic AI developer assistant.")
workspace_app = typer.Typer(help="Bind and inspect the active workspace.")
setup_app = typer.Typer(help="Clone projects or publish local projects to GitHub.")
new_app = typer.Typer(help="Guided onboarding flows for new or existing projects.")
git_app = typer.Typer(help="Git workflow automation.")
branch_app = typer.Typer(help="Branch helpers.")
commit_app = typer.Typer(help="Commit message helpers.")

app.add_typer(workspace_app, name="workspace")
app.add_typer(setup_app, name="setup")
app.add_typer(new_app, name="new")
app.add_typer(git_app, name="git")
app.add_typer(commit_app, name="commit")
git_app.add_typer(branch_app, name="branch")

console = Console()


def _workspace_path(explicit: Optional[Path] = None) -> Path:
    if explicit:
        return explicit.expanduser().resolve()
    config = ConfigManager.load()
    if not config.workspace_path:
        raise typer.BadParameter("No workspace is bound. Run `devagent workspace bind <path>` first.")
    return config.workspace_path


def _print_project_status(path: Path) -> None:
    project = detect_project(path)
    git = GitTool(path)
    table = Table(title="Workspace Status")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Path", str(project.path))
    table.add_row("Project type", ", ".join(project.project_types) or "unknown")
    table.add_row("Package files", ", ".join(project.package_files) or "none")
    table.add_row("Git repository", "yes" if git.is_repo else "no")
    if git.is_repo:
        table.add_row("Branch", git.current_branch() or "unknown")
        table.add_row("Dirty", "yes" if git.has_changes() else "no")
        changed = git.changed_files()
        table.add_row("Changed files", "\n".join(changed) if changed else "none")
    console.print(table)


@workspace_app.command("bind")
def bind_workspace(path: Path = typer.Argument(..., help="Project folder to attach DevAgent to.")) -> None:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise typer.BadParameter(f"Workspace does not exist or is not a directory: {resolved}")
    ConfigManager.bind_workspace(resolved)
    console.print(Panel.fit(f"Bound workspace:\n[bold]{resolved}[/bold]", title="DevAgent"))
    _print_project_status(resolved)


@workspace_app.command("status")
def workspace_status() -> None:
    _print_project_status(_workspace_path())


@setup_app.command("clone")
def clone_repo(
    repo_url: str = typer.Argument(..., help="GitHub repository URL or clone URL."),
    target: Optional[Path] = typer.Option(None, "--target", "-t", help="Target parent directory."),
    install_deps: bool = typer.Option(False, "--install-deps", help="Install detected dependencies after clone."),
    open_code: bool = typer.Option(False, "--open-code", help="Open the cloned project in VS Code."),
) -> None:
    try:
        result = SetupTool.clone_from_github(repo_url, target, install_deps=install_deps, open_code=open_code)
    except RuntimeError as exc:
        console.print(Panel(str(exc), title="Setup Failed", style="red"))
        raise typer.Exit(code=1) from exc
    ConfigManager.bind_workspace(result.path)
    console.print(Panel.fit(result.message, title="Clone Complete"))
    _print_project_status(result.path)


@app.command("clone")
def clone_repo_alias(
    repo_url: str = typer.Argument(..., help="GitHub repository URL or clone URL."),
    target: Optional[Path] = typer.Option(None, "--target", "-t", help="Target parent directory."),
    install_deps: bool = typer.Option(False, "--install-deps", help="Install detected dependencies after clone."),
    open_code: bool = typer.Option(False, "--open-code", help="Open the cloned project in VS Code."),
) -> None:
    """Shortcut for `devagent setup clone`."""
    clone_repo(repo_url=repo_url, target=target, install_deps=install_deps, open_code=open_code)


@setup_app.command("publish")
def publish_repo(
    path: Path = typer.Argument(..., help="Local project folder."),
    repo_name: Optional[str] = typer.Option(None, "--name", "-n", help="GitHub repository name."),
    private: bool = typer.Option(False, "--private", help="Create a private GitHub repository."),
    push: bool = typer.Option(True, "--push/--no-push", help="Push after creating the remote repository."),
) -> None:
    try:
        result = SetupTool.publish_to_github(path, repo_name=repo_name, private=private, push=push)
    except (RuntimeError, ValueError) as exc:
        console.print(Panel(str(exc), title="Publish Failed", style="red"))
        raise typer.Exit(code=1) from exc
    ConfigManager.bind_workspace(result.path)
    console.print(Panel.fit(result.message, title="Publish Complete"))


@app.command("publish")
def publish_repo_alias(
    path: Path = typer.Argument(..., help="Local project folder."),
    repo_name: Optional[str] = typer.Option(None, "--name", "-n", help="GitHub repository name."),
    private: bool = typer.Option(False, "--private", help="Create a private GitHub repository."),
    push: bool = typer.Option(True, "--push/--no-push", help="Push after creating the remote repository."),
) -> None:
    """Shortcut for `devagent setup publish`."""
    publish_repo(path=path, repo_name=repo_name, private=private, push=push)


@new_app.command("project")
def new_project(
    start: Optional[Path] = typer.Option(None, "--start", "-s", help="Folder where the directory picker starts."),
) -> None:
    """Guided setup for cloning a GitHub repo or publishing a local project."""
    console.print(Panel.fit("Let's connect a project to DevAgent.", title="New Project"))
    mode = Prompt.ask(
        "Do you already have a GitHub repo, or do you have a local project to publish?",
        choices=["github", "local"],
        default="github",
    )
    picker_start = (start or Path.cwd()).expanduser().resolve()
    if mode == "github":
        repo_url = Prompt.ask("Paste the GitHub repository page URL")
        target = choose_directory(console, picker_start, "Choose where to clone the repo")
        install_deps = Confirm.ask("Install dependencies if DevAgent detects them?", default=False)
        open_code = Confirm.ask("Open the project in VS Code after setup?", default=False)
        clone_repo(repo_url=repo_url, target=target, install_deps=install_deps, open_code=open_code)
        return

    local_path = choose_directory(console, picker_start, "Choose your local project folder")
    repo_name = Prompt.ask("GitHub repository name", default=local_path.name)
    private = Confirm.ask("Create the GitHub repo as private?", default=False)
    push = Confirm.ask("Push the local project after creating the remote?", default=True)
    publish_repo(path=local_path, repo_name=repo_name, private=private, push=push)


@app.command("index")
def index_workspace(path: Optional[Path] = typer.Option(None, "--path", "-p", help="Workspace path override.")) -> None:
    workspace = _workspace_path(path)
    index = CodeIndexer(workspace).build()
    console.print(f"Indexed [bold]{len(index.records)}[/bold] chunks from [bold]{workspace}[/bold].")


@app.command("chat")
def chat(question: str = typer.Argument(..., help="Question about the active workspace.")) -> None:
    workspace = _workspace_path()
    answer = RepoAgent(workspace).answer(question)
    console.print(Panel(answer, title="DevAgent"))


@app.command("packages")
def packages() -> None:
    """List direct Node packages from package.json files in the active workspace."""
    workspace = _workspace_path()
    node_packages = find_node_packages(workspace)
    if not node_packages:
        console.print("[yellow]No package.json dependencies found in the active workspace.[/yellow]")
        console.print(f"Active workspace: [bold]{workspace}[/bold]")
        return
    table = Table(title="Node Packages")
    table.add_column("Manifest")
    table.add_column("Section")
    table.add_column("Package")
    table.add_column("Version")
    for package in node_packages:
        table.add_row(package.manifest, package.section, package.name, package.version)
    console.print(table)


@app.command("edit")
def edit(
    instruction: str = typer.Argument(..., help="Natural language code edit instruction."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the proposed diff without prompting."),
) -> None:
    workspace = _workspace_path()
    edit_agent = EditAgent(workspace)
    proposal = edit_agent.propose(instruction)
    console.print(Panel(proposal.diff or proposal.message, title="Proposed Change"))
    if not proposal.diff:
        raise typer.Exit(code=1)
    if yes or typer.confirm("Apply this diff?"):
        edit_agent.apply(proposal)
        console.print("[green]Applied change.[/green]")
    else:
        console.print("[yellow]No files changed.[/yellow]")


@git_app.command("status")
def git_status() -> None:
    tool = GitTool(_workspace_path())
    console.print(tool.status_text())


@branch_app.command("create")
def create_branch(name: str = typer.Argument(..., help="New branch name.")) -> None:
    tool = GitTool(_workspace_path())
    tool.create_branch(name)
    console.print(f"Created and switched to branch [bold]{name}[/bold].")


@branch_app.command("switch")
def switch_branch(
    name: str = typer.Argument(..., help="Branch to switch to."),
    force: bool = typer.Option(False, "--force", help="Allow switching with uncommitted changes."),
) -> None:
    tool = GitTool(_workspace_path())
    if tool.has_changes() and not force:
        raise typer.BadParameter("Uncommitted changes exist. Commit/stash them or pass --force.")
    tool.switch_branch(name)
    console.print(f"Switched to branch [bold]{name}[/bold].")


@git_app.command("commit")
def git_commit(
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message."),
    all_files: bool = typer.Option(False, "--all", "-a", help="Stage all changed files before committing."),
) -> None:
    tool = GitTool(_workspace_path())
    final_message = message or tool.suggest_commit_message()
    commit_id = tool.commit(final_message, all_files=all_files)
    console.print(f"Created commit [bold]{commit_id}[/bold]: {final_message}")


@git_app.command("push")
def git_push(remote: str = "origin", branch: Optional[str] = None) -> None:
    tool = GitTool(_workspace_path())
    target_branch = branch or tool.current_branch()
    tool.push(remote=remote, branch=target_branch)
    console.print(f"Pushed [bold]{target_branch}[/bold] to [bold]{remote}[/bold].")


@commit_app.command("suggest")
def suggest_commit(conventional: bool = typer.Option(True, "--conventional/--plain")) -> None:
    tool = GitTool(_workspace_path())
    console.print(tool.suggest_commit_message(conventional=conventional))


@app.command("watch")
def watch_workspace(
    interval: float = typer.Option(1.0, "--interval", help="Polling interval when watchdog is unavailable."),
) -> None:
    workspace = _workspace_path()
    console.print(f"Watching [bold]{workspace}[/bold]. Press Ctrl+C to stop.")
    WatchService(workspace, interval=interval).run()


@app.command("inspect")
def inspect_workspace() -> None:
    workspace = _workspace_path()
    findings = Inspector(workspace).run()
    if not findings:
        console.print("[green]No issues found.[/green]")
        return
    table = Table(title="DevAgent Insights")
    table.add_column("Severity")
    table.add_column("File")
    table.add_column("Message")
    for finding in findings:
        table.add_row(finding.severity, finding.path, finding.message)
    console.print(table)


if __name__ == "__main__":
    app()
