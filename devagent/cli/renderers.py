from __future__ import annotations

from pathlib import Path
from typing import Iterable

from rich.console import Group, RenderableType

from devagent.cli.ui import app_table, status_badge, styled_path, toned_message
from devagent.core.actions import (
    MergeConflictDetail,
    PullOutcome,
    PullRequestPreview,
    PushOutcome,
    RunInventory,
    RunLaunchResult,
    WorkspaceSnapshot,
)
from devagent.tools.git_tool import CommitSuggestion, GitRemote
from devagent.tools.insights import Finding
from devagent.tools.node_tool import NodePackage


def workspace_status_table(snapshot: WorkspaceSnapshot):
    table = app_table("Workspace Status")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Path", styled_path(str(snapshot.project.path)))
    table.add_row("Project type", ", ".join(snapshot.project.project_types) or "unknown")
    table.add_row("Package files", ", ".join(snapshot.project.package_files) or "none")
    table.add_row("Git repository", status_badge("yes", "success") if snapshot.is_repo else status_badge("no", "warning"))
    if snapshot.is_repo:
        table.add_row("Branch", toned_message(snapshot.branch or "unknown", "info"))
        table.add_row("Dirty", status_badge("yes", "warning") if snapshot.dirty else status_badge("no", "success"))
        table.add_row("Changed files", "\n".join(snapshot.changed_files) if snapshot.changed_files else "none")
    return table


def packages_renderable(workspace: Path, packages: list[NodePackage]) -> RenderableType:
    if not packages:
        return f"No package.json dependencies found.\nActive workspace: {workspace}"
    table = app_table("Node Packages")
    table.add_column("Manifest")
    table.add_column("Section")
    table.add_column("Package")
    table.add_column("Version")
    for package in packages:
        table.add_row(package.manifest, package.section, package.name, package.version)
    return table


def insights_renderable(findings: list[Finding]) -> RenderableType:
    if not findings:
        return "No issues found."
    table = app_table("DevAgent Insights")
    table.add_column("Severity")
    table.add_column("File")
    table.add_column("Message")
    for finding in findings:
        tone = "error" if finding.severity == "high" else "warning" if finding.severity == "medium" else "info" if finding.severity == "info" else "success"
        table.add_row(status_badge(finding.severity, tone), finding.path, finding.message)
    return table


def merge_conflicts_renderable(conflicts: list[MergeConflictDetail]) -> RenderableType:
    if not conflicts:
        return "No merge conflicts detected."
    table = app_table("Merge Conflicts")
    table.add_column("File")
    table.add_column("Conflict Markers")
    for conflict in conflicts:
        table.add_row(conflict.path, str(conflict.markers))
    return table


def run_inventory_renderable(workspace: Path, inventory: RunInventory) -> RenderableType:
    detected_table = app_table("Detected Run Targets")
    detected_table.add_column("Name")
    detected_table.add_column("Folder")
    detected_table.add_column("Command")
    if inventory.detected:
        for spec in inventory.detected:
            detected_table.add_row(spec.name, spec.scope(workspace), spec.display_command)
    else:
        detected_table.add_row("No launchable services detected", "-", "-")

    saved_table = app_table("Saved Run Phrases")
    saved_table.add_column("Phrase")
    saved_table.add_column("Browser")
    saved_table.add_column("Targets")
    if inventory.profiles:
        for phrase, profile in inventory.profiles.items():
            saved_table.add_row(phrase, "yes" if profile.open_browser else "no", "\n".join(spec.name for spec in profile.specs))
    else:
        saved_table.add_row("No saved phrases yet", "-", "-")
    return Group(detected_table, saved_table)


def run_launch_message(workspace: Path, result: RunLaunchResult) -> str:
    sections = []
    for spec in result.specs:
        sections.append(f"Launched {spec.name} in {spec.scope(workspace)}\nCommand: {spec.display_command}")
    if result.phrase:
        sections.insert(0, f"Used saved run phrase: {result.phrase}")
    if result.browser_opened and result.browser_url:
        sections.append(f"Opened browser at {result.browser_url}")
    return "\n\n".join(sections)


def package_lines(packages: Iterable[NodePackage]) -> str:
    packages = list(packages)
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


def insight_lines(findings: Iterable[Finding]) -> str:
    findings = list(findings)
    if not findings:
        return "No issues found."
    return "\n".join(f"[{finding.severity}] {finding.path} - {finding.message}" for finding in findings)


def commit_suggestion_renderable(suggestion: CommitSuggestion) -> RenderableType:
    table = app_table("Commit Suggestion")
    table.add_column("Section")
    table.add_column("Details")
    table.add_row("Subject", suggestion.subject)
    table.add_row("Summary", "\n".join(f"- {line}" for line in suggestion.change_summary) or "none")
    table.add_row("Impact", "\n".join(f"- {line}" for line in suggestion.impact_summary) or "none")
    table.add_row("Key files", "\n".join(suggestion.changed_files[:5]) or "none")
    if suggestion.body.strip():
        table.add_row("Commit body", suggestion.body)
    return table


def git_pull_summary_renderable(result: PullOutcome) -> RenderableType:
    table = app_table("Pull Summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Local branch", result.local_branch)
    table.add_row("Remote", result.remote)
    table.add_row("Remote branch", result.remote_branch)
    table.add_row("Strategy", "rebase" if result.rebase else "merge")
    return table


def git_push_summary_renderable(result: PushOutcome) -> RenderableType:
    table = app_table("Push Summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Local branch", result.local_branch)
    table.add_row("Destination remote", result.remote)
    table.add_row("Destination branch", result.remote_branch)
    table.add_row("Set upstream", "yes" if result.set_upstream else "no")
    table.add_row("Force with lease", "yes" if result.force_with_lease else "no")
    return table


def pr_preview_renderable(preview: PullRequestPreview) -> RenderableType:
    table = app_table("Pull Request Preview")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Title", preview.title)
    table.add_row("Body", preview.body)
    return table


def git_remotes_renderable(remotes: list[GitRemote]) -> RenderableType:
    table = app_table("Git Remotes")
    table.add_column("Remote")
    table.add_column("GitHub Repo")
    table.add_column("Fetch URL")
    if not remotes:
        table.add_row("none", "-", "-")
        return table
    for remote in remotes:
        table.add_row(remote.name, remote.repo_slug or "-", remote.fetch_url)
    return table
