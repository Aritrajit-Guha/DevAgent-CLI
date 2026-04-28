from pathlib import Path

import devagent.tools.runtime_tool as runtime_tool_module
from devagent.tools.runtime_tool import RunTool, build_windows_terminal_command


def test_detect_launch_specs_for_mixed_workspace(tmp_path: Path) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(
        '{"scripts": {"dev": "vite", "start": "vite preview"}}',
        encoding="utf-8",
    )
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "backend" / "main.py").write_text("print('hello')\n", encoding="utf-8")

    specs = RunTool(tmp_path).detect_launch_specs()

    assert len(specs) == 2
    node_spec = next(spec for spec in specs if spec.kind == "node")
    python_spec = next(spec for spec in specs if spec.kind == "python")

    assert node_spec.cwd == tmp_path / "frontend"
    assert node_spec.command == ["npm", "run", "dev"]
    assert node_spec.browser_url == "http://localhost:5173"
    assert python_spec.cwd == tmp_path / "backend"
    assert python_spec.command == ["python", "main.py"]
    assert python_spec.venv_dir == tmp_path / "backend" / ".venv"
    assert python_spec.bootstrap_commands


def test_build_windows_terminal_command_activates_venv(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (backend / "main.py").write_text("print('hello')\n", encoding="utf-8")
    venv_dir = backend / ".venv"
    spec = RunTool(tmp_path).save_manual_profile("start backend", "python main.py", cwd=backend)
    command = build_windows_terminal_command(spec)

    assert "activate.bat" in command
    assert "python main.py" in command
    assert str(venv_dir / "Scripts" / "python.exe") in command


def test_launch_opens_browser_for_detected_frontend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runtime_tool_module.os, "name", "nt")
    opened_urls: list[str] = []
    spawned: list[list[str]] = []

    class DummyProcess:
        pass

    def fake_popen(args, cwd=None, creationflags=0):
        spawned.append(list(args))
        return DummyProcess()

    monkeypatch.setattr(runtime_tool_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime_tool_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(runtime_tool_module.webbrowser, "open", lambda url: opened_urls.append(url))

    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"scripts": {"dev": "vite --port 3001"}}', encoding="utf-8")

    specs = RunTool(tmp_path).launch_detected(open_browser=True)

    assert specs[0].browser_url == "http://localhost:3001"
    assert opened_urls == ["http://localhost:3001"]
    assert spawned


def test_saved_profiles_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEVAGENT_CONFIG_DIR", str(tmp_path / "config-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "frontend").mkdir()
    (workspace / "frontend" / "package.json").write_text('{"scripts": {"dev": "vite"}}', encoding="utf-8")

    tool = RunTool(workspace)
    saved = tool.save_detected_profile("I order you to start in the name of jesus")

    profiles = tool.saved_profiles()

    assert saved
    assert "I order you to start in the name of jesus" in profiles
    assert profiles["I order you to start in the name of jesus"][0].command == ["npm", "run", "dev"]
    assert profiles["I order you to start in the name of jesus"][0].browser_url == "http://localhost:5173"

    assert tool.delete_profile("I order you to start in the name of jesus")
    assert tool.saved_profiles() == {}
