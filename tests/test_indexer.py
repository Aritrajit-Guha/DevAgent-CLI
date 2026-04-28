from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever


def test_indexer_ignores_dependency_folders(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("def login_secret(): pass\n", encoding="utf-8")

    index = CodeIndexer(tmp_path, chunk_lines=10).build()
    paths = {record.path for record in index.records}

    assert "app.py" in paths
    assert "node_modules/ignored.py" not in paths


def test_retriever_finds_matching_chunk(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def login_user():\n    validate_password()\n", encoding="utf-8")
    index = CodeIndexer(tmp_path, chunk_lines=10).build()

    results = Retriever(index).search("where is login validation", limit=1)

    assert results
    assert results[0].path == "auth.py"


def test_load_or_build_rebuilds_when_source_files_change(tmp_path: Path, monkeypatch) -> None:
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("DEVAGENT_CONFIG_DIR", str(config_home))

    readme = tmp_path / "README.md"
    readme.write_text("Old ending\nAritrajit Guha\n", encoding="utf-8")
    indexer = CodeIndexer(tmp_path, chunk_lines=10)
    original = indexer.build()

    assert any("Aritrajit Guha" in record.text for record in original.records)

    readme.write_text("New ending\nagentic and personal.\n", encoding="utf-8")

    refreshed = indexer.load_or_build()

    assert any("agentic and personal." in record.text for record in refreshed.records)
    assert all("Aritrajit Guha" not in record.text for record in refreshed.records)
