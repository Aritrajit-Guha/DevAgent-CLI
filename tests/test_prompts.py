from pathlib import Path

from devagent.cli.prompts import visible_directories


def test_visible_directories_sorts_and_hides_dotfolders(tmp_path: Path) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "file.txt").write_text("not a directory", encoding="utf-8")

    names = [path.name for path in visible_directories(tmp_path)]

    assert names == ["alpha", "zeta"]
