import subprocess
from pathlib import Path
from types import MethodType

import devagent.tools.git_tool as git_tool_module
from devagent.cli.main import git_action_choices
from devagent.tools.git_tool import CommitSuggestion, GitTool, infer_action, infer_area, normalize_status_path


class SilentAI:
    available = False

    def complete(self, *args, **kwargs):
        return None


class RefiningAI:
    available = True

    def complete(self, *args, **kwargs):
        return (
            "SUBJECT: feat: upgrade guided Git workflows\n"
            "BODY:\n"
            "- Tighten guided pull and push prompts.\n"
            "- Improve PR targeting across repos."
        )


def make_tool(tmp_path: Path, *, ai=None) -> GitTool:
    return GitTool(tmp_path, ai=ai or SilentAI())


def test_normalize_status_path() -> None:
    assert normalize_status_path(" M devagent/app.py") == "devagent/app.py"
    assert normalize_status_path("?? README.md") == "README.md"


def test_commit_message_helpers() -> None:
    assert infer_action(["?? devagent/app.py"], "") == "add"
    assert infer_area(["devagent/app.py", "devagent/cli.py"]) == "devagent changes"


def test_conflict_marker_count(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("<<<<<<< HEAD\nleft\n=======\nright\n>>>>>>> branch\n", encoding="utf-8")
    assert make_tool(tmp_path).conflict_marker_count("README.md") == 1


def test_changed_files_since_returns_empty_when_base_missing(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    assert make_tool(tmp_path).changed_files_since("does-not-exist") == []


def test_git_action_choices_are_descriptive() -> None:
    labels = [choice.label for choice in git_action_choices()]

    assert "See what changed and which branch you're on" in labels
    assert "Pull the latest changes into this branch" in labels
    assert "Open a PR for this branch" in labels
    assert "Exit Git assistant" in labels


def test_diff_returns_empty_string_when_stdout_is_missing(tmp_path: Path) -> None:
    tool = make_tool(tmp_path)

    def fake_run(self, args, check=True):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=None, stderr="")

    tool._run = MethodType(fake_run, tool)

    assert tool.diff() == ""


def test_suggest_commit_is_specific_for_git_and_help_changes(tmp_path: Path) -> None:
    tool = make_tool(tmp_path)

    def fake_diff(self, staged=False):
        return (
            "+def pull_with_prompts(self):\n"
            "+def push_with_prompts(self):\n"
            "+def pr_preview_with_prompts(self):\n"
            "+GIT_HELP = \"guided Git workflows\"\n"
        )

    def fake_changed(self):
        return [
            " M devagent/tools/git_tool.py",
            " M devagent/core/shell.py",
            " M devagent/cli/main.py",
            " M tests/test_git_tool.py",
        ]

    tool.diff = MethodType(fake_diff, tool)
    tool.changed_files = MethodType(fake_changed, tool)

    suggestion = tool.suggest_commit()

    assert suggestion.subject.startswith("chore:")
    assert "git pull, push, and PR flows" in suggestion.subject
    assert suggestion.project_area == "git pull, push, and PR flows"
    assert suggestion.body_bullets
    assert "`devagent/tools/git_tool.py`" in suggestion.body
    assert "Makes everyday Git actions easier to understand for normal project work." in suggestion.body


def test_suggest_commit_handles_docs_only_changes(tmp_path: Path) -> None:
    tool = make_tool(tmp_path)

    tool.diff = MethodType(lambda self, staged=False: "+# Usage\n+Updated CLI help guide\n", tool)
    tool.changed_files = MethodType(lambda self: [" M README.md"], tool)

    suggestion = tool.suggest_commit()

    assert suggestion.subject.startswith("docs:")
    assert "readme guidance" in suggestion.subject.casefold()
    assert suggestion.project_area == "README guidance"
    assert "README.md" in suggestion.body


def test_suggest_commit_handles_tests_only_changes(tmp_path: Path) -> None:
    tool = make_tool(tmp_path)

    tool.diff = MethodType(lambda self, staged=False: "+def test_pull_flow():\n+    assert True\n", tool)
    tool.changed_files = MethodType(lambda self: [" M tests/test_git_tool.py"], tool)

    suggestion = tool.suggest_commit()

    assert suggestion.subject.startswith("test:")
    assert "git tool coverage" in suggestion.subject
    assert "Adds stronger regression protection" in suggestion.body


def test_suggest_commit_message_handles_missing_diff(tmp_path: Path) -> None:
    tool = make_tool(tmp_path)

    def fake_diff(self, staged=False):
        return None

    def fake_changed(self):
        return [" M devagent/app.py"]

    tool.diff = MethodType(fake_diff, tool)
    tool.changed_files = MethodType(fake_changed, tool)

    assert "devagent and app" in tool.suggest_commit_message()


def test_suggest_commit_uses_ai_refinement_when_available(tmp_path: Path) -> None:
    tool = make_tool(tmp_path, ai=RefiningAI())

    tool.diff = MethodType(lambda self, staged=False: "+def push_with_prompts(self):\n", tool)
    tool.changed_files = MethodType(lambda self: [" M devagent/core/shell.py"], tool)

    suggestion = tool.suggest_commit()

    assert suggestion.subject == "feat: upgrade guided Git workflows"
    assert "Improve PR targeting across repos." in suggestion.body


def test_commit_uses_subject_and_body_segments(tmp_path: Path) -> None:
    tool = make_tool(tmp_path)
    calls: list[list[str]] = []

    def fake_run(self, args, check=True):
        calls.append(args)
        if args[:3] == ["git", "rev-parse", "--short"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    tool._run = MethodType(fake_run, tool)

    commit_id = tool.commit(
        CommitSuggestion(
            subject="feat: upgrade guided Git workflows",
            body="- Tighten pull prompts.\n- Improve PR targeting.",
        )
    )

    assert commit_id == "abc123"
    assert ["git", "commit", "-m", "feat: upgrade guided Git workflows", "-m", "- Tighten pull prompts.\n- Improve PR targeting."] in calls


def test_run_decodes_non_utf8_output_without_crashing(tmp_path: Path, monkeypatch) -> None:
    tool = make_tool(tmp_path)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=kwargs.get("args", args[0]), returncode=0, stdout=b"line \x90\n", stderr=b"")

    monkeypatch.setattr(git_tool_module.subprocess, "run", fake_run)

    result = tool._run(["git", "status"], check=False)

    assert isinstance(result.stdout, str)
    assert "line" in result.stdout
