from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from devagent.context.scanner import IGNORED_DIRS


@dataclass(frozen=True)
class NodePackage:
    manifest: str
    section: str
    name: str
    version: str


def find_node_packages(workspace: Path) -> list[NodePackage]:
    root = workspace.expanduser().resolve()
    packages: list[NodePackage] = []
    for manifest in sorted(root.rglob("package.json")):
        relative = manifest.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        packages.extend(read_manifest_packages(root, manifest))
    return packages


def read_manifest_packages(root: Path, manifest: Path) -> list[NodePackage]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    relative = manifest.relative_to(root).as_posix()
    packages: list[NodePackage] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = data.get(section, {})
        if not isinstance(values, dict):
            continue
        for name, version in sorted(values.items()):
            packages.append(NodePackage(manifest=relative, section=section, name=name, version=str(version)))
    return packages
