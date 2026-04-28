from pathlib import Path

from devagent.tools import setup_tool as setup_tool_module
from devagent.tools.setup_tool import (
    SetupTool,
    dependency_install_command,
    dependency_install_commands,
    is_python_venv_dir,
    normalize_github_clone_url,
    open_in_vscode,
    preferred_python_venv_dir,
    python_venv_display,
    python_venv_executable,
    resolve_command,
)


def test_normalize_github_url() -> None:
    assert normalize_github_clone_url("https://github.com/example/project") == "https://github.com/example/project.git"


def test_dependency_command_prefers_node(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert dependency_install_command(tmp_path) == ["npm", "install"]


def test_dependency_command_for_python_uses_project_venv(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    command = dependency_install_command(tmp_path)

    assert command is not None
    assert command[0] == str(python_venv_executable(tmp_path / ".venv"))
    assert command[1:] == ["-m", "pip", "install", "-r", "requirements.txt"]


def test_preferred_python_venv_dir_reuses_existing_venv(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (tmp_path / "venv" / "Scripts").mkdir(parents=True)
    (tmp_path / "venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (tmp_path / "venv" / "pyvenv.cfg").write_text("home = C:\\Python311\n", encoding="utf-8")

    venv_dir = preferred_python_venv_dir(tmp_path)
    command = dependency_install_commands(tmp_path, include_nested=False)[0]

    assert venv_dir == tmp_path / "venv"
    assert is_python_venv_dir(venv_dir)
    assert command.virtualenv_dir == venv_dir
    assert command.setup_commands == ()
    assert command.command[0] == str(python_venv_executable(venv_dir))


def test_dependency_commands_find_nested_node_apps(tmp_path: Path) -> None:
    (tmp_path / "client").mkdir()
    (tmp_path / "server").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "client" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "server" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "server" / "yarn.lock").write_text("", encoding="utf-8")
    (tmp_path / "node_modules" / "package.json").write_text("{}", encoding="utf-8")

    commands = dependency_install_commands(tmp_path)

    displays = [line for command in commands for line in command.display_lines(tmp_path)]
    assert "client> npm install" in displays
    assert "server> yarn install" in displays
    assert all("node_modules" not in display for display in displays)


def test_dependency_commands_show_python_venv_steps(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    commands = dependency_install_commands(tmp_path)
    backend_command = next(command for command in commands if command.cwd == tmp_path / "backend")
    displays = backend_command.display_lines(tmp_path)

    assert "backend> python -m venv .venv" in displays
    assert f"backend> {python_venv_display(Path('.venv'))} -m pip install -r requirements.txt" in displays


def test_open_in_vscode_is_non_fatal_when_code_is_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("devagent.tools.setup_tool.which", lambda _: None)

    message = open_in_vscode(tmp_path)

    assert "Skipped VS Code open" in message


def test_resolve_command_uses_full_path(monkeypatch) -> None:
    monkeypatch.setattr("devagent.tools.setup_tool.which", lambda name: r"C:\Program Files\nodejs\npm.cmd" if name == "npm" else None)

    resolved = resolve_command(["npm", "install"])

    assert resolved == [r"C:\Program Files\nodejs\npm.cmd", "install"]


def test_clone_installs_python_dependencies_inside_local_venv(monkeypatch, tmp_path: Path) -> None:
    captured: list[tuple[list[str], Path]] = []

    def fake_run(args, cwd, check=True):
        captured.append((list(args), cwd))
        if args[:3] == ["git", "clone", "https://github.com/example/project.git"]:
            destination = Path(args[3])
            (destination / "backend").mkdir(parents=True)
            (destination / "frontend").mkdir(parents=True)
            (destination / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
            (destination / "frontend" / "package.json").write_text("{}", encoding="utf-8")
        elif len(args) >= 4 and args[1:4] == ["-m", "venv", ".venv"]:
            (cwd / ".venv" / "Scripts").mkdir(parents=True, exist_ok=True)
        return setup_tool_module.subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(setup_tool_module, "run", fake_run)

    result = SetupTool.clone_from_github("https://github.com/example/project", target=tmp_path, install_deps=True, open_code=False)

    backend = result.path / "backend"
    frontend = result.path / "frontend"
    assert ([str(python_venv_executable(backend / ".venv")), "-m", "pip", "install", "-r", "requirements.txt"], backend) in captured
    assert (["npm", "install"], frontend) in captured
    assert not any(command[:5] == ["python", "-m", "pip", "install", "-r"] for command, _ in captured)
    assert "Created virtual environment in backend/.venv." in result.message
