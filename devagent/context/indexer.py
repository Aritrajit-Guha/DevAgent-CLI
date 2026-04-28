from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from devagent.config.settings import ConfigManager
from devagent.context.scanner import iter_source_files, read_text_safely
from devagent.tools.ai import AIClient


@dataclass(frozen=True)
class CodeChunk:
    path: str
    start_line: int
    end_line: int
    text: str
    embedding: list[float] | None = None


@dataclass(frozen=True)
class CodeIndex:
    root: Path
    records: list[CodeChunk]


class CodeIndexer:
    def __init__(self, root: Path, chunk_lines: int = 80, overlap: int = 12):
        self.root = root.expanduser().resolve()
        self.chunk_lines = chunk_lines
        self.overlap = overlap
        self.index_dir = ConfigManager.workspace_cache_dir(self.root)
        self.index_file = self.index_dir / "index.json"
        self.ai = AIClient.from_env()

    def build(self) -> CodeIndex:
        chunks: list[CodeChunk] = []
        for path in iter_source_files(self.root):
            text = read_text_safely(path)
            if not text:
                continue
            chunks.extend(self._chunk_file(path, text))

        embeddings = self.ai.embed([chunk.text for chunk in chunks])
        if embeddings and len(embeddings) == len(chunks):
            chunks = [
                CodeChunk(
                    path=chunk.path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    text=chunk.text,
                    embedding=embedding,
                )
                for chunk, embedding in zip(chunks, embeddings)
            ]

        index = CodeIndex(root=self.root, records=chunks)
        self.save(index)
        return index

    def load_or_build(self) -> CodeIndex:
        if self.index_file.exists():
            return self.load()
        return self.build()

    def load(self) -> CodeIndex:
        data = json.loads(self.index_file.read_text(encoding="utf-8"))
        records = [CodeChunk(**item) for item in data.get("records", [])]
        return CodeIndex(root=self.root, records=records)

    def save(self, index: CodeIndex) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        payload = {"root": str(index.root), "records": [asdict(record) for record in index.records]}
        self.index_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _chunk_file(self, path: Path, text: str) -> list[CodeChunk]:
        lines = text.splitlines()
        if not lines:
            return []
        relative = path.relative_to(self.root).as_posix()
        chunks: list[CodeChunk] = []
        step = max(1, self.chunk_lines - self.overlap)
        for start in range(0, len(lines), step):
            end = min(len(lines), start + self.chunk_lines)
            chunk_text = "\n".join(lines[start:end]).strip()
            if chunk_text:
                chunks.append(CodeChunk(path=relative, start_line=start + 1, end_line=end, text=chunk_text))
            if end >= len(lines):
                break
        return chunks
