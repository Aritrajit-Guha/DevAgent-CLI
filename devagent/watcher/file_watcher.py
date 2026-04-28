from __future__ import annotations

import time
from pathlib import Path

from devagent.context.scanner import IGNORED_DIRS
from devagent.tools.git_tool import GitTool


class WatchService:
    def __init__(self, workspace: Path, interval: float = 1.0):
        self.workspace = workspace.expanduser().resolve()
        self.interval = interval
        self.git = GitTool(self.workspace)

    def run(self) -> None:
        try:
            self._run_watchdog()
        except Exception:
            self._run_polling()

    def _run_watchdog(self) -> None:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        service = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):  # type: ignore[no-untyped-def]
                if event.is_directory:
                    return
                path = Path(event.src_path)
                if should_ignore(path):
                    return
                service.report_change(event.event_type, path)

        observer = Observer()
        observer.schedule(Handler(), str(self.workspace), recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    def _run_polling(self) -> None:
        snapshot = snapshot_files(self.workspace)
        try:
            while True:
                time.sleep(self.interval)
                current = snapshot_files(self.workspace)
                added = current.keys() - snapshot.keys()
                removed = snapshot.keys() - current.keys()
                modified = {path for path in current.keys() & snapshot.keys() if current[path] != snapshot[path]}
                for path in sorted(added):
                    self.report_change("created", self.workspace / path)
                for path in sorted(modified):
                    self.report_change("modified", self.workspace / path)
                for path in sorted(removed):
                    self.report_change("deleted", self.workspace / path)
                snapshot = current
        except KeyboardInterrupt:
            return

    def report_change(self, event_type: str, path: Path) -> None:
        try:
            relative = path.relative_to(self.workspace) if path.is_absolute() else path
        except ValueError:
            relative = path
        print(f"{event_type}: {relative}")
        if self.git.is_repo and self.git.has_changes():
            changed_count = len(self.git.changed_files())
            print(f"Suggestion: {changed_count} changed file(s). Run `devagent commit suggest` before committing.")


def should_ignore(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def snapshot_files(root: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or should_ignore(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        snapshot[path.relative_to(root).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot
