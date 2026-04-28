from pathlib import Path

from devagent.tools.node_tool import find_node_packages


def test_find_node_packages_ignores_node_modules(tmp_path: Path) -> None:
    (tmp_path / "client").mkdir()
    (tmp_path / "client" / "package.json").write_text(
        '{"dependencies":{"react":"^19.0.0"},"devDependencies":{"vite":"^7.0.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text(
        '{"dependencies":{"ignored":"1.0.0"}}',
        encoding="utf-8",
    )

    packages = find_node_packages(tmp_path)

    assert {package.name for package in packages} == {"react", "vite"}
    assert {package.manifest for package in packages} == {"client/package.json"}
