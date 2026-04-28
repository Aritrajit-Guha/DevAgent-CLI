from devagent.tools.git_tool import infer_action, infer_area, normalize_status_path


def test_normalize_status_path() -> None:
    assert normalize_status_path(" M devagent/app.py") == "devagent/app.py"
    assert normalize_status_path("?? README.md") == "README.md"


def test_commit_message_helpers() -> None:
    assert infer_action(["?? devagent/app.py"], "") == "add"
    assert infer_area(["devagent/app.py", "devagent/cli.py"]) == "devagent changes"
