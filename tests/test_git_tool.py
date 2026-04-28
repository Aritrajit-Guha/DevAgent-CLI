import subprocess
from pathlib import Path

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
