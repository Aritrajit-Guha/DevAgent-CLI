from devagent.tools.setup_tool import dependency_install_command, normalize_github_clone_url


def test_normalize_github_url() -> None:
    assert normalize_github_clone_url("https://github.com/example/project") == "https://github.com/example/project.git"


def test_dependency_command_prefers_node(tmp_path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert dependency_install_command(tmp_path) == ["npm", "install"]
