from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from devagent.cli.prompts import MenuChoice, can_use_arrow_menu, choose_directory, choose_menu_action
from devagent.config.settings import ConfigManager
from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.core.agent import RepoAgent
from devagent.core.project import detect_project
from devagent.tools.edit_tool import EditAgent
from devagent.tools.git_tool import GitError, GitTool
from devagent.tools.insights import Inspector
from devagent.tools.node_tool import find_node_packages
from devagent.tools.runtime_tool import RunTool
from devagent.tools.setup_tool import SetupTool
from devagent.watcher.file_watcher import WatchService

app = typer.Typer(help="Local-first agentic AI developer assistant.")
workspace_app = typer.Typer(help="Bind and inspect the active workspace.")
setup_app = typer.Typer(help="Clone projects or publish local projects to GitHub.")
new_app = typer.Typer(help="Guided onboarding flows for new or existing projects.")
git_app = typer.Typer(help="Git workflow automation.", invoke_without_command=True)
run_app = typer.Typer(help="Launch workspace services and save run phrases.", invoke_without_command=True)
branch_app = typer.Typer(help="Branch helpers.")
pr_app = typer.Typer(help="Pull request helpers.")
merge_app = typer.Typer(help="Merge conflict helpers.")
commit_app = typer.Typer(help="Commit message helpers.")

app.add_typer(workspace_app, name="workspace")
app.add_typer(setup_app, name="setup")
app.add_typer(new_app, name="new")
app.add_typer(git_app, name="git")
app.add_typer(run_app, name="run")
app.add_typer(commit_app, name="commit")
git_app.add_typer(branch_app, name="branch")
git_app.add_typer(pr_app, name="pr")
git_app.add_typer(merge_app, name="merge")

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


def _git_tool() -> GitTool:
    return GitTool(_workspace_path())


def _run_tool() -> RunTool:
    return RunTool(_workspace_path())


def _print_git_menu() -> None:
    table = Table(title="DevAgent Git")
    table.add_column("What You Want")
    table.add_column("Command To Run")
    table.add_row("See what changed and which branch you're on", "devagent git status")
    table.add_row("Stage everything for the next commit", "devagent git add")
    table.add_row("Stage a specific file or folder", "devagent git add <path>")
    table.add_row("Create a branch for new work", "devagent git branch create <name>")
    table.add_row("Switch to another branch safely", "devagent git branch switch <name>")
    table.add_row("Commit with an auto-generated message", "devagent git commit --all")
    table.add_row("Suggest a commit message without committing", "devagent commit suggest")
    table.add_row("Pull the latest changes from the remote", "devagent git pull")
    table.add_row("Push your current branch", "devagent git push")
    table.add_row("Preview a pull request title and body", "devagent git pr preview")
    table.add_row("Open a pull request with GitHub CLI", "devagent git pr create")
    table.add_row("See which files are stuck in a conflict", "devagent git merge conflicts")
    table.add_row("Abort a merge that went sideways", "devagent git merge abort")
    table.add_row("Continue after resolving conflicts", "devagent git merge continue")
    console.print(table)


def _print_run_menu() -> None:
    tool = _run_tool()
    detected = tool.detect_launch_specs()
    saved = tool.saved_profiles()

    detected_table = Table(title="Detected Run Targets")
    detected_table.add_column("Name")
    detected_table.add_column("Folder")
    detected_table.add_column("Command")
    if detected:
        for spec in detected:
            detected_table.add_row(spec.name, spec.scope(tool.workspace), spec.display_command)
    else:
        detected_table.add_row("No launchable services detected", "-", "-")
    console.print(detected_table)

    saved_table = Table(title="Saved Run Phrases")
    saved_table.add_column("Phrase")
    saved_table.add_column("Launches")
    saved_table.add_column("Targets")
    if saved:
        for phrase, specs in saved.items():
            saved_table.add_row(phrase, str(len(specs)), "\n".join(spec.name for spec in specs))
    else:
        saved_table.add_row("No saved phrases yet", "-", "-")
    console.print(saved_table)


def git_action_choices() -> list[MenuChoice]:
    return [
        MenuChoice("See what changed and which branch you're on", "status"),
        MenuChoice("Stage everything for the next commit", "add_all"),
        MenuChoice("Stage a specific file or folder", "add_path"),
        MenuChoice("Create a branch for new work", "branch_create"),
        MenuChoice("Switch to another branch safely", "branch_switch"),
        MenuChoice("Commit with an auto-generated message", "commit_auto"),
        MenuChoice("Suggest a commit message without committing", "commit_suggest"),
        MenuChoice("Pull the latest changes from the remote", "pull"),
        MenuChoice("Push your current branch", "push"),
        MenuChoice("Preview a pull request title and body", "pr_preview"),
        MenuChoice("Open a pull request with GitHub CLI", "pr_create"),
        MenuChoice("See which files are stuck in a conflict", "merge_conflicts"),
        MenuChoice("Abort a merge that went sideways", "merge_abort"),
        MenuChoice("Continue after resolving conflicts", "merge_continue"),
        MenuChoice("Exit Git assistant", "exit"),
    ]


def _run_git_menu() -> None:
    while True:
        action = choose_menu_action(console, "Choose a Git action", git_action_choices())
        if not action or action == "exit":
            return
        try:
            if action == "status":
                git_status()
            elif action == "add_all":
                git_add(".")
            elif action == "add_path":
                git_add(Prompt.ask("Path to stage", default="."))
            elif action == "branch_create":
                create_branch(Prompt.ask("New branch name"))
            elif action == "branch_switch":
                switch_branch(Prompt.ask("Branch to switch to"), force=Confirm.ask("Allow switching with uncommitted changes?", default=False))
            elif action == "commit_auto":
                custom = Confirm.ask("Write your own commit message?", default=False)
                message = Prompt.ask("Commit message") if custom else None
                git_commit(message=message, all_files=True)
            elif action == "commit_suggest":
                suggest_commit(conventional=True)
            elif action == "pull":
                git_pull(remote=Prompt.ask("Remote", default="origin"), branch=None, rebase=Confirm.ask("Pull with rebase?", default=False))
            elif action == "push":
                git_push(remote=Prompt.ask("Remote", default="origin"), branch=None)
            elif action == "pr_preview":
                pr_preview(base=Prompt.ask("Base branch", default="main"))
            elif action == "pr_create":
                pr_create(
                    base=Prompt.ask("Base branch", default="main"),
                    title=None,
                    body=None,
                    draft=Confirm.ask("Create this PR as a draft?", default=False),
                )
            elif action == "merge_conflicts":
                merge_conflicts()
            elif action == "merge_abort":
                merge_abort()
            elif action == "merge_continue":
                merge_continue()
        except typer.Exit:
            continue
        except Exception as exc:
            console.print(Panel(str(exc), title="Git Action Failed", style="red"))


@git_app.callback()
def git_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        if can_use_arrow_menu():
            _run_git_menu()
        else:
            _print_git_menu()


@run_app.callback()
def run_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _print_run_menu()


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


@run_app.command("start")
def run_start(
    phrase: Optional[str] = typer.Argument(None, help="Saved run phrase to launch. Defaults to detected services."),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser", help="Open the detected local app URL after launching services."),
) -> None:
    tool = _run_tool()
    try:
        specs = tool.launch_saved(phrase, open_browser=open_browser) if phrase else tool.launch_detected(open_browser=open_browser)
    except RuntimeError as exc:
        console.print(Panel(str(exc), title="Run Failed", style="red"))
        raise typer.Exit(code=1) from exc

    sections = []
    for spec in specs:
        sections.append(
            f"Launched [bold]{spec.name}[/bold] in [bold]{spec.scope(tool.workspace)}[/bold]\n"
            f"Command: [cyan]{spec.display_command}[/cyan]"
        )
    if phrase:
        sections.insert(0, f"Used saved run phrase: [bold]{phrase}[/bold]")
    if open_browser:
        browser_url = next((spec.browser_url for spec in specs if spec.browser_url), None)
        if browser_url:
            sections.append(f"Opened browser at [link={browser_url}]{browser_url}[/link]")
    console.print(Panel("\n\n".join(sections), title="Services Started"))


@run_app.command("save")
def run_save(
    phrase: str = typer.Argument(..., help="Natural-language phrase to remember."),
    command: Optional[str] = typer.Option(None, "--command", "-c", help="Manual command to launch instead of the detected stack."),
    cwd: Optional[Path] = typer.Option(None, "--cwd", help="Working directory for --command. Defaults to the workspace root."),
) -> None:
    tool = _run_tool()
    try:
        if command:
            spec = tool.save_manual_profile(phrase, command, cwd=cwd)
            body = (
                f"Saved phrase [bold]{phrase}[/bold]\n\n"
                f"Folder: [bold]{spec.scope(tool.workspace)}[/bold]\n"
                f"Command: [cyan]{spec.display_command}[/cyan]"
            )
        else:
            specs = tool.save_detected_profile(phrase)
            body = (
                f"Saved phrase [bold]{phrase}[/bold] for the detected stack.\n\n"
                + "\n".join(f"- {spec.scope(tool.workspace)}: {spec.display_command}" for spec in specs)
            )
    except RuntimeError as exc:
        console.print(Panel(str(exc), title="Save Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(Panel(body, title="Run Phrase Saved"))


@run_app.command("list")
def run_list() -> None:
    _print_run_menu()


@run_app.command("forget")
def run_forget(
    phrase: str = typer.Argument(..., help="Saved run phrase to delete."),
) -> None:
    tool = _run_tool()
    deleted = tool.delete_profile(phrase)
    if not deleted:
        console.print(Panel(f"No saved run phrase found: {phrase}", title="Nothing Deleted", style="yellow"))
        raise typer.Exit(code=1)
    console.print(f"Removed saved run phrase [bold]{phrase}[/bold].")


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
        try:
            edit_agent.apply(proposal)
        except RuntimeError as exc:
            console.print(Panel(str(exc), title="Edit Failed", style="red"))
            console.print("[yellow]No files were changed.[/yellow]")
            raise typer.Exit(code=1) from exc
        console.print("[green]Applied change.[/green]")
    else:
        console.print("[yellow]No files changed.[/yellow]")


@git_app.command("status")
def git_status() -> None:
    tool = _git_tool()
    console.print(tool.status_text())


@git_app.command("add")
def git_add(path: str = typer.Argument(".", help="Path to stage. Defaults to the whole workspace.")) -> None:
    tool = _git_tool()
    try:
        tool.add(path)
    except GitError as exc:
        console.print(Panel(str(exc), title="Git Add Failed", style="red"))
        raise typer.Exit(code=1) from exc
    if path == ".":
        console.print("[green]Staged the whole workspace.[/green]")
    else:
        console.print(f"Staged [bold]{path}[/bold].")


@branch_app.command("create")
def create_branch(name: str = typer.Argument(..., help="New branch name.")) -> None:
    tool = _git_tool()
    try:
        tool.create_branch(name)
    except GitError as exc:
        console.print(Panel(str(exc), title="Branch Create Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(f"Created and switched to branch [bold]{name}[/bold].")


@branch_app.command("switch")
def switch_branch(
    name: str = typer.Argument(..., help="Branch to switch to."),
    force: bool = typer.Option(False, "--force", help="Allow switching with uncommitted changes."),
) -> None:
    tool = _git_tool()
    if tool.has_changes() and not force:
        raise typer.BadParameter("Uncommitted changes exist. Commit/stash them or pass --force.")
    try:
        tool.switch_branch(name)
    except GitError as exc:
        console.print(Panel(str(exc), title="Branch Switch Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(f"Switched to branch [bold]{name}[/bold].")


@git_app.command("commit")
def git_commit(
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message."),
    all_files: bool = typer.Option(True, "--all/--staged-only", "-a/-s", help="Stage all changed files before committing."),
) -> None:
    tool = _git_tool()
    final_message = message or tool.suggest_commit_message()
    try:
        commit_id = tool.commit(final_message, all_files=all_files)
    except GitError as exc:
        console.print(Panel(str(exc), title="Commit Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(f"Created commit [bold]{commit_id}[/bold]: {final_message}")


@git_app.command("pull")
def git_pull(
    remote: str = "origin",
    branch: Optional[str] = None,
    rebase: bool = typer.Option(False, "--rebase", help="Pull with rebase instead of merge."),
) -> None:
    tool = _git_tool()
    try:
        tool.pull(remote=remote, branch=branch, rebase=rebase)
    except GitError as exc:
        console.print(Panel(str(exc), title="Pull Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(f"Pulled [bold]{branch or tool.current_branch() or 'current branch'}[/bold] from [bold]{remote}[/bold].")


@git_app.command("push")
def git_push(remote: str = "origin", branch: Optional[str] = None) -> None:
    tool = _git_tool()
    target_branch = branch or tool.current_branch()
    try:
        tool.push(remote=remote, branch=target_branch)
    except GitError as exc:
        console.print(Panel(str(exc), title="Push Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(f"Pushed [bold]{target_branch}[/bold] to [bold]{remote}[/bold].")


@pr_app.command("preview")
def pr_preview(base: str = typer.Option("main", "--base", help="Base branch for the pull request.")) -> None:
    tool = _git_tool()
    title = tool.pr_title()
    body = tool.pr_body(base=base)
    console.print(Panel(f"[bold]Title[/bold]\n{title}\n\n[bold]Body[/bold]\n{body}", title="Pull Request Preview"))


@pr_app.command("create")
def pr_create(
    base: str = typer.Option("main", "--base", help="Base branch for the pull request."),
    title: Optional[str] = typer.Option(None, "--title", help="Override the generated PR title."),
    body: Optional[str] = typer.Option(None, "--body", help="Override the generated PR body."),
    draft: bool = typer.Option(False, "--draft", help="Create the pull request as a draft."),
) -> None:
    tool = _git_tool()
    try:
        url = tool.create_pr(base=base, title=title, body=body, draft=draft)
    except GitError as exc:
        console.print(Panel(str(exc), title="PR Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print(Panel(url or "Pull request created.", title="Pull Request"))


@merge_app.command("conflicts")
def merge_conflicts() -> None:
    tool = _git_tool()
    files = tool.conflict_files()
    if not files:
        console.print("[green]No merge conflicts detected.[/green]")
        return
    table = Table(title="Merge Conflicts")
    table.add_column("File")
    table.add_column("Conflict Markers")
    for file in files:
        table.add_row(file, str(tool.conflict_marker_count(file)))
    console.print(table)


@merge_app.command("abort")
def merge_abort() -> None:
    tool = _git_tool()
    try:
        tool.merge_abort()
    except GitError as exc:
        console.print(Panel(str(exc), title="Merge Abort Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print("[green]Aborted the merge.[/green]")


@merge_app.command("continue")
def merge_continue() -> None:
    tool = _git_tool()
    try:
        tool.merge_continue()
    except GitError as exc:
        console.print(Panel(str(exc), title="Merge Continue Failed", style="red"))
        raise typer.Exit(code=1) from exc
    console.print("[green]Continued the merge.[/green]")


@commit_app.command("suggest")
def suggest_commit(conventional: bool = typer.Option(True, "--conventional/--plain")) -> None:
    tool = _git_tool()
    try:
        console.print(tool.suggest_commit_message(conventional=conventional))
    except GitError as exc:
        console.print(Panel(str(exc), title="Commit Suggestion Failed", style="red"))
        raise typer.Exit(code=1) from exc


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
