from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table


def visible_directories(path: Path, limit: int = 50) -> list[Path]:
    directories = [item for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")]
    return sorted(directories, key=lambda item: item.name.lower())[:limit]


def choose_directory(console: Console, start: Path, title: str) -> Path:
    current = start.expanduser().resolve()
    while True:
        table = Table(title=f"{title}: {current}")
        table.add_column("#", justify="right")
        table.add_column("Folder")
        folders = visible_directories(current)
        for index, folder in enumerate(folders, start=1):
            table.add_row(str(index), folder.name)
        console.print(table)
        console.print("Enter a number to open a folder, [bold].[/bold] to choose this folder, [bold]..[/bold] to go up, or paste/type a path.")
        choice = Prompt.ask("Directory").strip()
        if choice == ".":
            return current
        if choice == "..":
            current = current.parent
            continue
        if choice.isdigit():
            selected = int(choice)
            if 1 <= selected <= len(folders):
                current = folders[selected - 1]
                continue
            console.print("[yellow]That folder number is not in the list.[/yellow]")
            continue
        candidate = Path(choice).expanduser()
        if not candidate.is_absolute():
            candidate = current / candidate
        candidate = candidate.resolve()
        if candidate.exists() and candidate.is_dir():
            return candidate
        if Confirm.ask(f"Create folder {candidate}?", default=True):
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
