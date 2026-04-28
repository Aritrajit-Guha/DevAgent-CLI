from pathlib import Path

from devagent.core.project import detect_project


def test_detect_python_and_node_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"scripts": {}}', encoding="utf-8")

    project = detect_project(tmp_path)

    assert "python" in project.project_types
    assert "node" in project.project_types
    assert "pyproject.toml" in project.package_files
    assert "package.json" in project.package_files


def test_detect_nested_node_projects(tmp_path: Path) -> None:
    (tmp_path / "client").mkdir()
    (tmp_path / "server").mkdir()
    (tmp_path / "client" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "server" / "package.json").write_text("{}", encoding="utf-8")

    project = detect_project(tmp_path)

    assert "node" in project.project_types
    assert "client/package.json" in project.package_files
    assert "server/package.json" in project.package_files
