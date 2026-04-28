import subprocess
from pathlib import Path
from types import MethodType

import devagent.tools.git_tool as git_tool_module
from devagent.cli.main import git_action_choices
from devagent.tools.git_tool import GitTool, infer_action, infer_area, normalize_status_path


def test_normalize_status_path() -> None:
    assert normalize_status_path(" M devagent/app.py") == "devagent/app.py"
    assert normalize_status_path("?? README.md") == "README.md"


def test_commit_message_helpers() -> None:
    assert infer_action(["?? devagent/app.py"], "") == "add"
    assert infer_area(["devagent/app.py", "devagent/cli.py"]) == "devagent changes"


def test_conflict_marker_count(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("<<<<<<< HEAD\nleft\n=======\nright\n>>>>>>> branch\n", encoding="utf-8")
    assert GitTool(tmp_path).conflict_marker_count("README.md") == 1


def test_changed_files_since_returns_empty_when_base_missing(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)

    assert GitTool(tmp_path).changed_files_since("does-not-exist") == []


def test_git_action_choices_are_descriptive() -> None:
    labels = [choice.label for choice in git_action_choices()]

    assert "See what changed and which branch you're on" in labels
    assert "Stage everything for the next commit" in labels
    assert "Exit Git assistant" in labels


def test_diff_returns_empty_string_when_stdout_is_missing(tmp_path: Path) -> None:
    tool = GitTool(tmp_path)

    def fake_run(self, args, check=True):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=None, stderr="")

    tool._run = MethodType(fake_run, tool)

    assert tool.diff() == ""


def test_suggest_commit_message_handles_missing_diff(tmp_path: Path) -> None:
    tool = GitTool(tmp_path)

    def fake_diff(self, staged=False):
        return None

    def fake_changed(self):
        return [" M devagent/app.py"]

    tool.diff = MethodType(fake_diff, tool)
    tool.changed_files = MethodType(fake_changed, tool)

    assert tool.suggest_commit_message() == "chore: update devagent changes"


def test_run_decodes_non_utf8_output_without_crashing(tmp_path: Path, monkeypatch) -> None:
    tool = GitTool(tmp_path)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=kwargs.get("args", args[0]), returncode=0, stdout=b"line \x90\n", stderr=b"")

    monkeypatch.setattr(git_tool_module.subprocess, "run", fake_run)

    result = tool._run(["git", "status"], check=False)

    assert isinstance(result.stdout, str)
    assert "line" in result.stdout
