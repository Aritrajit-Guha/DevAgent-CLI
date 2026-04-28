from pathlib import Path

from rich.console import Console

from devagent.cli.prompts import MenuChoice, choose_menu_action, visible_directories


def test_visible_directories_sorts_and_hides_dotfolders(tmp_path: Path) -> None:
    (tmp_path / "zeta").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "file.txt").write_text("not a directory", encoding="utf-8")

    names = [path.name for path in visible_directories(tmp_path)]

    assert names == ["alpha", "zeta"]


def test_choose_menu_action_falls_back_to_numbered_prompt(monkeypatch) -> None:
    monkeypatch.setattr("devagent.cli.prompts.can_use_arrow_menu", lambda: False)
    monkeypatch.setattr("devagent.cli.prompts.Prompt.ask", lambda *args, **kwargs: "2")

    action = choose_menu_action(
        Console(),
        "Pick one",
        [MenuChoice("First action", "first"), MenuChoice("Second action", "second")],
    )

    assert action == "second"
