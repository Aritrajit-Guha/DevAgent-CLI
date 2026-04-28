from pathlib import Path

from devagent.tools.file_tool import FileTool


def test_file_tool_generates_unified_diff(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('old')\n", encoding="utf-8")

    diff = FileTool(tmp_path).diff_text("app.py", "print('new')\n")

    assert "--- a/app.py" in diff
    assert "+++ b/app.py" in diff
    assert "-print('old')" in diff
    assert "+print('new')" in diff
