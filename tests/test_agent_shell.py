from pathlib import Path

from typer.testing import CliRunner

from devagent.cli.main import app
from devagent.core.agent import RepoAgent
from devagent.core.shell import AgentShell, interactive_terminal
from devagent.tools.runtime_tool import LaunchSpec


class FakeAI:
    def __init__(self):
        self.available = True
        self.calls: list[dict[str, object]] = []

    def complete(self, prompt: str, *, deep: bool = False, system_instruction: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "deep": deep, "system_instruction": system_instruction})
        return "Detailed repo answer"

    def embed(self, texts):
        return None


class FakeRepoAgent:
    def __init__(self):
        self.deep_calls: list[bool] = []
        self.cleared = False

    def answer(self, question: str, *, deep: bool = False, new_session: bool = False) -> str:
        self.deep_calls.append(deep)
        return f"chat:{question}"

    def clear_session(self) -> None:
        self.cleared = True


def test_repo_agent_uses_session_memory_and_deep_mode(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "backend").mkdir()
    (workspace / "backend" / "auth.py").write_text(
        "def login_user(user):\n    return create_session(user)\n",
        encoding="utf-8",
    )
    (workspace / "backend" / "routes.py").write_text(
        "from backend.auth import login_user\n\n"
        "def login_route(payload):\n    return login_user(payload)\n",
        encoding="utf-8",
    )

    fake_ai = FakeAI()
    monkeypatch.setattr("devagent.tools.ai.AIClient.from_env", classmethod(lambda cls: fake_ai))

    agent = RepoAgent(workspace)
    first = agent.answer("Where is authentication implemented?")
    second = agent.answer("How does it connect to routes?", deep=True)
    third = agent.answer("Explain the login flow again.", new_session=True)

    assert first == "Detailed repo answer"
    assert second == "Detailed repo answer"
    assert third == "Detailed repo answer"
    assert fake_ai.calls[1]["deep"] is True
    assert "Where is authentication implemented?" in str(fake_ai.calls[1]["prompt"])
    assert "Where is authentication implemented?" not in str(fake_ai.calls[2]["prompt"])
    assert "backend/auth.py" in str(fake_ai.calls[1]["prompt"])
    assert "backend/routes.py" in str(fake_ai.calls[1]["prompt"])


def test_shell_routes_saved_phrase_runtime_and_chat(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "frontend").mkdir()
    (workspace / "frontend" / "package.json").write_text('{"scripts": {"dev": "vite"}}', encoding="utf-8")

    shell = AgentShell(workspace)
    shell.repo_agent = FakeRepoAgent()
    saved_profile = shell.run_tool.save_detected_profile("Start I Command You", open_browser=True)

    launched: list[tuple[str, bool | None]] = []
    shell.run_tool.launch_profile = lambda profile, open_browser=None: launched.append((profile.phrase, open_browser)) or profile.specs

    saved_result = shell.handle_input(" start i command you ")
    assert saved_result is not None
    assert saved_result.title == "Saved Run Phrase"
    assert launched == [("Start I Command You", None)]

    runtime_calls: list[bool] = []
    shell.run_tool.launch_detected = lambda open_browser=False: runtime_calls.append(open_browser) or [
        LaunchSpec(
            name="frontend node dev",
            cwd=workspace / "frontend",
            command=["npm", "run", "dev"],
            display_command="npm run dev",
            kind="node",
            browser_url="http://localhost:5173",
        )
    ]
    runtime_result = shell.handle_input("start the app and open the browser")
    assert runtime_result is not None
    assert runtime_calls == [True]
    assert "Opened browser at http://localhost:5173" in runtime_result.message

    deep_toggle = shell.handle_input("/deep")
    assert deep_toggle is not None
    assert shell.deep_mode is True

    chat_result = shell.handle_input("Explain the login flow")
    assert chat_result is not None
    assert chat_result.message == "chat:Explain the login flow"
    assert shell.repo_agent.deep_calls == [True]

    clear_result = shell.handle_input("/clear")
    assert clear_result is not None
    assert shell.repo_agent.cleared is True


def test_devagent_no_args_prints_help_when_not_interactive(monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr("devagent.cli.main.interactive_terminal", lambda: False)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Local-first agentic AI developer assistant." in result.stdout


def test_interactive_terminal_helper(monkeypatch) -> None:
    class FakeStream:
        def __init__(self, tty: bool):
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr("devagent.core.shell.sys.stdin", FakeStream(True))
    monkeypatch.setattr("devagent.core.shell.sys.stdout", FakeStream(True))
    assert interactive_terminal() is True
