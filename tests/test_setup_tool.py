from pathlib import Path

from devagent.tools.setup_tool import (
    dependency_install_command,
    dependency_install_commands,
    normalize_github_clone_url,
    open_in_vscode,
)


def test_normalize_github_url() -> None:
    assert normalize_github_clone_url("https://github.com/example/project") == "https://github.com/example/project.git"


def test_dependency_command_prefers_node(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert dependency_install_command(tmp_path) == ["npm", "install"]


def test_dependency_commands_find_nested_node_apps(tmp_path: Path) -> None:
    (tmp_path / "client").mkdir()
    (tmp_path / "server").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "client" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "server" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "server" / "yarn.lock").write_text("", encoding="utf-8")
    (tmp_path / "node_modules" / "package.json").write_text("{}", encoding="utf-8")

    commands = dependency_install_commands(tmp_path)

    displays = [command.display(tmp_path) for command in commands]
    assert "client> npm install" in displays
    assert "server> yarn install" in displays
    assert all("node_modules" not in display for display in displays)


def test_open_in_vscode_is_non_fatal_when_code_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("devagent.tools.setup_tool.which", lambda _: None)

    message = open_in_vscode(tmp_path)

    assert "Skipped VS Code open" in message
