from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.prompt import Confirm, Prompt

from devagent.cli.prompts import MenuChoice, can_use_arrow_menu, choose_directory, choose_menu_action
from devagent.cli.renderers import (
    insights_renderable,
    merge_conflicts_renderable,
    packages_renderable,
    run_inventory_renderable,
    run_launch_message,
    workspace_status_table,
)
from devagent.cli.ui import app_panel, app_table, console, hero_panel, status_badge, styled_path, toned_message
from devagent.config.settings import ConfigManager
from devagent.core.actions import DevAgentActions, bind_workspace_action, snapshot_workspace
from devagent.core.shell import AgentShell, interactive_terminal
from devagent.tools.git_tool import GitError

app = typer.Typer(help="Local-first agentic AI developer assistant.", invoke_without_command=True, no_args_is_help=False)
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


@app.callback()
def app_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if interactive_terminal():
        config = ConfigManager.load()
        if not config.workspace_path:
            console.print(app_panel("No workspace is bound yet.\nRun `devagent workspace bind <path>` or `devagent new project` first.", "Agent Shell", tone="warning", expand=False))
            console.print(ctx.get_help())
            raise typer.Exit()
        shell = AgentShell(config.workspace_path)
        shell.run()
        raise typer.Exit()
    console.print(ctx.get_help())
    raise typer.Exit()


def _workspace_path(explicit: Optional[Path] = None) -> Path:
    if explicit:
        return explicit.expanduser().resolve()
    config = ConfigManager.load()
    if not config.workspace_path:
        raise typer.BadParameter("No workspace is bound. Run `devagent workspace bind <path>` first.")
    return config.workspace_path


def _print_project_status(path: Path) -> None:
    console.print(workspace_status_table(snapshot_workspace(path)))


def _actions(explicit: Optional[Path] = None) -> DevAgentActions:
    return DevAgentActions(_workspace_path(explicit))


def _print_run_menu() -> None:
    actions = _actions()
    inventory = actions.run_inventory()
    console.print(hero_panel("Runtime Agent", "Spin up services, attach environments, and open the app in one move."))
    console.print(run_inventory_renderable(actions.workspace, inventory))


def _print_git_menu() -> None:
    console.print(hero_panel("Git Assistant", "Command your repo with guided actions and neon telemetry."))
    table = app_table("DevAgent Git")
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
            console.print(app_panel(str(exc), "Git Action Failed", tone="error", expand=False))


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
    try:
        snapshot = bind_workspace_action(path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(app_panel(f"Bound workspace:\n{snapshot.project.path}", "Workspace Linked", tone="success", expand=False))
    console.print(workspace_status_table(snapshot))


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
    actions = DevAgentActions(_workspace_path() if ConfigManager.load().workspace_path else Path.cwd())
    try:
        result = actions.clone_repo(repo_url, target=target, install_deps=install_deps, open_code=open_code)
    except (RuntimeError, ValueError) as exc:
        console.print(app_panel(str(exc), "Setup Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(app_panel(result.message, "Clone Complete", tone="success", expand=False))
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
    actions = DevAgentActions(_workspace_path() if ConfigManager.load().workspace_path else Path.cwd())
    try:
        result = actions.publish_repo(path, repo_name=repo_name, private=private, push=push)
    except (RuntimeError, ValueError) as exc:
        console.print(app_panel(str(exc), "Publish Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(app_panel(result.message, "Publish Complete", tone="success", expand=False))


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
    console.print(hero_panel("New Project", "Clone an existing repo or publish local work without losing the flow."))
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
    actions = _actions(path)
    count = actions.index_workspace()
    console.print(app_panel(f"Indexed {count} chunks from\n{actions.workspace}", "Index Complete", tone="success", expand=False))


@app.command("chat")
def chat(
    question: str = typer.Argument(..., help="Question about the active workspace."),
    deep: bool = typer.Option(False, "--deep", help="Use broader retrieval and the deep Gemini model when configured."),
    new_session: bool = typer.Option(False, "--new-session", help="Clear saved workspace chat context before answering."),
) -> None:
    answer = _actions().chat(question, deep=deep, new_session=new_session)
    console.print(app_panel(answer, "DevAgent Response", tone="info"))


@app.command("packages")
def packages() -> None:
    """List direct Node packages from package.json files in the active workspace."""
    actions = _actions()
    node_packages = actions.packages()
    renderable = packages_renderable(actions.workspace, node_packages)
    if node_packages:
        console.print(renderable)
    else:
        console.print(app_panel(renderable, "Package Scan", tone="warning", expand=False))


@run_app.command("start")
def run_start(
    phrase: Optional[str] = typer.Argument(None, help="Saved run phrase to launch. Defaults to detected services."),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser", help="Open the detected local app URL after launching services."),
) -> None:
    actions = _actions()
    try:
        result = actions.run_start(phrase, open_browser=open_browser)
    except RuntimeError as exc:
        console.print(app_panel(str(exc), "Run Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(app_panel(run_launch_message(actions.workspace, result), "Services Started", tone="success", expand=False))


@run_app.command("save")
def run_save(
    phrase: str = typer.Argument(..., help="Natural-language phrase to remember."),
    command: Optional[str] = typer.Option(None, "--command", "-c", help="Manual command to launch instead of the detected stack."),
    cwd: Optional[Path] = typer.Option(None, "--cwd", help="Working directory for --command. Defaults to the workspace root."),
    open_browser: bool = typer.Option(False, "--open-browser/--no-open-browser", help="Remember whether this phrase should open the browser after launch."),
    description: Optional[str] = typer.Option(None, "--description", help="Optional note about what this phrase launches."),
) -> None:
    actions = _actions()
    try:
        profile = actions.save_run_profile(phrase, command=command, cwd=cwd, open_browser=open_browser, description=description)
    except RuntimeError as exc:
        console.print(app_panel(str(exc), "Save Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    if command:
        spec = profile.specs[0]
        body = (
            f"Saved phrase {phrase}\n\n"
            f"Folder: {spec.scope(actions.workspace)}\n"
            f"Command: {spec.display_command}\n"
            f"Open browser: {'yes' if profile.open_browser else 'no'}"
        )
    else:
        body = (
            f"Saved phrase {phrase} for the detected stack.\n\n"
            + "\n".join(f"- {spec.scope(actions.workspace)}: {spec.display_command}" for spec in profile.specs)
            + f"\n\nOpen browser: {'yes' if profile.open_browser else 'no'}"
        )
    console.print(app_panel(body, "Run Phrase Saved", tone="success", expand=False))


@run_app.command("list")
def run_list() -> None:
    _print_run_menu()


@run_app.command("forget")
def run_forget(
    phrase: str = typer.Argument(..., help="Saved run phrase to delete."),
) -> None:
    deleted = _actions().delete_run_profile(phrase)
    if not deleted:
        console.print(app_panel(f"No saved run phrase found: {phrase}", "Nothing Deleted", tone="warning", expand=False))
        raise typer.Exit(code=1)
    console.print(toned_message(f"Removed saved run phrase {phrase}.", "success"))


@app.command("edit")
def edit(
    instruction: str = typer.Argument(..., help="Natural language code edit instruction."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply the proposed diff without prompting."),
) -> None:
    actions = _actions()
    proposal = actions.edit_propose(instruction)
    console.print(app_panel(proposal.diff or proposal.message, "Proposed Change", tone="info"))
    if not proposal.diff:
        raise typer.Exit(code=1)
    if yes or typer.confirm("Apply this diff?"):
        try:
            actions.edit_apply(proposal)
        except RuntimeError as exc:
            console.print(app_panel(str(exc), "Edit Failed", tone="error", expand=False))
            console.print(toned_message("No files were changed.", "warning"))
            raise typer.Exit(code=1) from exc
        console.print(toned_message("Applied change.", "success"))
    else:
        console.print(toned_message("No files changed.", "warning"))


@git_app.command("status")
def git_status() -> None:
    try:
        status = _actions().git_status()
    except GitError as exc:
        console.print(app_panel(str(exc), "Git Status Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(app_panel(status, "Git Status", tone="info", expand=False))


@git_app.command("add")
def git_add(path: str = typer.Argument(".", help="Path to stage. Defaults to the whole workspace.")) -> None:
    try:
        _actions().git_add(path)
    except (GitError, ValueError) as exc:
        console.print(app_panel(str(exc), "Git Add Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    if path == ".":
        console.print(toned_message("Staged the whole workspace.", "success"))
    else:
        console.print(toned_message(f"Staged {path}.", "success"))


@branch_app.command("create")
def create_branch(name: str = typer.Argument(..., help="New branch name.")) -> None:
    try:
        _actions().git_create_branch(name)
    except GitError as exc:
        console.print(app_panel(str(exc), "Branch Create Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(toned_message(f"Created and switched to branch {name}.", "success"))


@branch_app.command("switch")
def switch_branch(
    name: str = typer.Argument(..., help="Branch to switch to."),
    force: bool = typer.Option(False, "--force", help="Allow switching with uncommitted changes."),
) -> None:
    try:
        _actions().git_switch_branch(name, force=force)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except GitError as exc:
        console.print(app_panel(str(exc), "Branch Switch Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(toned_message(f"Switched to branch {name}.", "success"))


@git_app.command("commit")
def git_commit(
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message."),
    all_files: bool = typer.Option(True, "--all/--staged-only", "-a/-s", help="Stage all changed files before committing."),
) -> None:
    try:
        outcome = _actions().git_commit(message=message, all_files=all_files)
    except GitError as exc:
        console.print(app_panel(str(exc), "Commit Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(app_panel(f"Created commit {outcome.commit_id}\n\n{outcome.message}", "Commit Complete", tone="success", expand=False))


@git_app.command("pull")
def git_pull(
    remote: str = "origin",
    branch: Optional[str] = None,
    rebase: bool = typer.Option(False, "--rebase", help="Pull with rebase instead of merge."),
) -> None:
    try:
        current_branch = _actions().git_pull(remote=remote, branch=branch, rebase=rebase)
    except GitError as exc:
        console.print(app_panel(str(exc), "Pull Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(toned_message(f"Pulled {current_branch} from {remote}.", "success"))


@git_app.command("push")
def git_push(remote: str = "origin", branch: Optional[str] = None) -> None:
    try:
        target_branch = _actions().git_push(remote=remote, branch=branch)
    except GitError as exc:
        console.print(app_panel(str(exc), "Push Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(toned_message(f"Pushed {target_branch} to {remote}.", "success"))


@pr_app.command("preview")
def pr_preview(base: str = typer.Option("main", "--base", help="Base branch for the pull request.")) -> None:
    preview = _actions().pr_preview(base=base)
    console.print(app_panel(f"TITLE\n{preview.title}\n\nBODY\n{preview.body}", "Pull Request Preview", tone="info"))


@pr_app.command("create")
def pr_create(
    base: str = typer.Option("main", "--base", help="Base branch for the pull request."),
    title: Optional[str] = typer.Option(None, "--title", help="Override the generated PR title."),
    body: Optional[str] = typer.Option(None, "--body", help="Override the generated PR body."),
    draft: bool = typer.Option(False, "--draft", help="Create the pull request as a draft."),
) -> None:
    try:
        url = _actions().pr_create(base=base, title=title, body=body, draft=draft)
    except GitError as exc:
        console.print(app_panel(str(exc), "PR Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(app_panel(url or "Pull request created.", "Pull Request", tone="success", expand=False))


@merge_app.command("conflicts")
def merge_conflicts() -> None:
    conflicts = _actions().merge_conflicts()
    renderable = merge_conflicts_renderable(conflicts)
    if conflicts:
        console.print(renderable)
    else:
        console.print(toned_message(str(renderable), "success"))


@merge_app.command("abort")
def merge_abort() -> None:
    try:
        _actions().merge_abort()
    except GitError as exc:
        console.print(app_panel(str(exc), "Merge Abort Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(toned_message("Aborted the merge.", "success"))


@merge_app.command("continue")
def merge_continue() -> None:
    try:
        _actions().merge_continue()
    except GitError as exc:
        console.print(app_panel(str(exc), "Merge Continue Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc
    console.print(toned_message("Continued the merge.", "success"))


@commit_app.command("suggest")
def suggest_commit(conventional: bool = typer.Option(True, "--conventional/--plain")) -> None:
    try:
        console.print(app_panel(_actions().suggest_commit(conventional=conventional), "Commit Suggestion", tone="info", expand=False))
    except GitError as exc:
        console.print(app_panel(str(exc), "Commit Suggestion Failed", tone="error", expand=False))
        raise typer.Exit(code=1) from exc


@app.command("watch")
def watch_workspace(
    interval: float = typer.Option(1.0, "--interval", help="Polling interval when watchdog is unavailable."),
) -> None:
    actions = _actions()
    console.print(app_panel(f"Watching {actions.workspace}\nPress Ctrl+C to stop.", "Watch Mode", tone="info", expand=False))
    actions.watch_workspace(interval=interval)


@app.command("inspect")
def inspect_workspace() -> None:
    findings = _actions().inspect()
    renderable = insights_renderable(findings)
    if findings:
        console.print(renderable)
    else:
        console.print(app_panel(renderable, "DevAgent Insights", tone="success", expand=False))


if __name__ == "__main__":
    app()
