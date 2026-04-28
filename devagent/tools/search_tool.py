from __future__ import annotations

from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever


class SearchTool:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()

    def search(self, query: str, limit: int = 5) -> list[str]:
        index = CodeIndexer(self.workspace).load_or_build()
        chunks = Retriever(index).search(query, limit=limit)
        return [f"{chunk.path}:{chunk.start_line}-{chunk.end_line}" for chunk in chunks]
