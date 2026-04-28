from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectInfo:
    path: Path
    project_types: list[str]
    package_files: list[str]
    file_tree: list[str]


PROJECT_MARKERS: dict[str, tuple[str, ...]] = {
    "python": ("pyproject.toml", "requirements.txt", "Pipfile", "setup.py"),
    "node": ("package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"),
    "rust": ("Cargo.toml",),
    "go": ("go.mod",),
    "java": ("pom.xml", "build.gradle", "settings.gradle"),
    "dotnet": (".csproj", ".sln"),
}

IGNORED_TREE_DIRS = {".git", ".devagent", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def detect_project(path: Path, max_tree_entries: int = 60) -> ProjectInfo:
    root = path.expanduser().resolve()
    package_files: list[str] = []
    project_types: list[str] = []

    for project_type, markers in PROJECT_MARKERS.items():
        found = False
        for marker in markers:
            if marker.startswith(".") and marker not in {".csproj", ".sln"}:
                candidate = root / marker
                if candidate.exists():
                    package_files.append(marker)
                    found = True
            elif marker in {".csproj", ".sln"}:
                matches = sorted(p.name for p in root.glob(f"*{marker}"))
                if matches:
                    package_files.extend(matches)
                    found = True
            else:
                matches = find_marker_files(root, marker)
                if matches:
                    package_files.extend(matches)
                    found = True
        if found:
            project_types.append(project_type)

    tree = build_file_tree(root, max_entries=max_tree_entries)
    return ProjectInfo(path=root, project_types=project_types, package_files=sorted(set(package_files)), file_tree=tree)


def build_file_tree(root: Path, max_entries: int = 60) -> list[str]:
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in IGNORED_TREE_DIRS for part in relative.parts):
            continue
        suffix = "/" if path.is_dir() else ""
        entries.append(f"{relative.as_posix()}{suffix}")
        if len(entries) >= max_entries:
            entries.append("...")
            break
    return entries


def find_marker_files(root: Path, marker: str, max_depth: int = 3) -> list[str]:
    matches: list[str] = []
    for path in root.rglob(marker):
        relative = path.relative_to(root)
        if any(part in IGNORED_TREE_DIRS for part in relative.parts):
            continue
        if len(relative.parts) > max_depth:
            continue
        matches.append(relative.as_posix())
    return sorted(matches)
