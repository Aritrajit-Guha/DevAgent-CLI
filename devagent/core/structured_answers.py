from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from devagent.context.scanner import iter_source_files, read_text_safely

QUESTION_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ENV_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=", re.MULTILINE)
JS_ARRAY_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\[", re.MULTILINE)
JS_PAIR_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')\s*:\s*"
    r"(?P<value>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|-?\d+(?:\.\d+)?|true|false|null)"
)

STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "at",
    "be",
    "can",
    "count",
    "do",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "like",
    "list",
    "me",
    "name",
    "names",
    "no",
    "of",
    "our",
    "please",
    "show",
    "that",
    "the",
    "them",
    "there",
    "these",
    "those",
    "to",
    "total",
    "u",
    "us",
    "what",
    "which",
}
RECORD_HINTS = {
    "catalog",
    "catalogue",
    "inventory",
    "item",
    "items",
    "listing",
    "marketplace",
    "product",
    "products",
    "shop",
    "store",
    "wholesale",
}
DEPENDENCY_HINTS = {
    "dependencies",
    "dependency",
    "libraries",
    "library",
    "node",
    "npm",
    "package",
    "packages",
    "pip",
    "requirements",
}
ENV_HINTS = {
    "config",
    "configuration",
    "dotenv",
    "env",
    "environment",
    "key",
    "keys",
    "secret",
    "secrets",
    "variable",
    "variables",
}
NAME_KEYS = ("name", "title", "label", "product_name", "item_name")
ID_KEYS = ("product_id", "id", "code", "sku", "slug")
CATEGORY_KEYS = ("category", "kind", "group", "type")
SENSITIVE_FILE_NAMES = (".env.example", ".env.sample", ".env.template")


@dataclass(frozen=True)
class StructuredAnswer:
    answer: str


@dataclass(frozen=True)
class RecordItem:
    fields: dict[str, str]
    line: int

    @property
    def name(self) -> str | None:
        return first_field(self.fields, NAME_KEYS)

    @property
    def identifier(self) -> str | None:
        return first_field(self.fields, ID_KEYS)

    @property
    def category(self) -> str | None:
        return first_field(self.fields, CATEGORY_KEYS)


@dataclass(frozen=True)
class RecordCollection:
    path: str
    label: str
    line_start: int
    line_end: int
    items: tuple[RecordItem, ...]

    @property
    def field_names(self) -> set[str]:
        names: set[str] = set()
        for item in self.items:
            names.update(item.fields.keys())
        return names

    @property
    def search_blob(self) -> str:
        parts = [self.path, self.label, " ".join(sorted(self.field_names))]
        for item in self.items[:6]:
            for value in (item.name, item.identifier, item.category):
                if value:
                    parts.append(value)
        return " ".join(parts).casefold()


@dataclass(frozen=True)
class DependencyManifest:
    path: str
    ecosystem: str
    sections: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

    @property
    def search_blob(self) -> str:
        parts = [self.path, self.ecosystem]
        for section, packages in self.sections:
            parts.append(section)
            parts.extend(name for name, _ in packages[:10])
        return " ".join(parts).casefold()

    @property
    def package_count(self) -> int:
        return sum(len(packages) for _, packages in self.sections)


@dataclass(frozen=True)
class EnvKeyDocument:
    path: str
    line_start: int
    line_end: int
    keys: tuple[str, ...]

    @property
    def search_blob(self) -> str:
        return f"{self.path} {' '.join(self.keys[:12])}".casefold()


def answer_structured_question(
    workspace: Path,
    question: str,
    *,
    intent: str,
    conversation_hint: str = "",
) -> StructuredAnswer | None:
    search_text = " ".join(part for part in (question, conversation_hint) if part).strip()
    lowered = search_text.casefold()

    if intent == "dependency" or contains_hint(lowered, DEPENDENCY_HINTS):
        manifests = extract_dependency_manifests(workspace)
        manifest_answer = build_dependency_answer(question, manifests)
        if manifest_answer:
            return StructuredAnswer(manifest_answer)

    if contains_hint(lowered, ENV_HINTS):
        env_docs = extract_env_key_documents(workspace)
        env_answer = build_env_answer(question, env_docs)
        if env_answer:
            return StructuredAnswer(env_answer)

    if intent in {"count", "list", "enumerate"} or contains_hint(lowered, RECORD_HINTS):
        collections = extract_record_collections(workspace)
        record_answer = build_record_answer(question, search_text, intent, collections)
        if record_answer:
            return StructuredAnswer(record_answer)

    return None


def build_record_answer(question: str, search_text: str, intent: str, collections: list[RecordCollection]) -> str | None:
    collection = choose_record_collection(search_text, collections)
    if not collection:
        return None

    count = len(collection.items)
    noun = infer_record_noun(question, collection)
    wants_ids = any(token in question.casefold() for token in ("id", "ids", "sku", "code", "product_id"))
    names = [item.name for item in collection.items if item.name]
    if len(names) != count:
        return None

    source = f"`{collection.path}:{collection.line_start}-{collection.line_end}`"
    if intent == "count":
        return "\n".join(
            [
                f"The {noun} list currently contains **{count}** entries.",
                "",
                f"Source: {source}",
            ]
        )

    title = f"The {noun} list currently contains **{count}** entries."
    lines = [title, "", "### Items"]
    for index, item in enumerate(collection.items, start=1):
        label = item.name or "Unnamed item"
        if wants_ids and item.identifier:
            label = f"`{item.identifier}` - {label}"
        lines.append(f"{index}. {label}")
    lines.extend(["", f"Source: {source}"])
    return "\n".join(lines)


def build_dependency_answer(question: str, manifests: list[DependencyManifest]) -> str | None:
    selected = choose_dependency_manifests(question, manifests)
    if not selected:
        return None

    total = sum(manifest.package_count for manifest in selected)
    lines = [f"I found **{total}** direct dependency entries across **{len(selected)}** manifest file(s).", ""]
    for manifest in selected:
        lines.append(f"### `{manifest.path}`")
        for section, packages in manifest.sections:
            if not packages:
                continue
            lines.append(f"**{section}**")
            for name, version in packages:
                pretty = f"`{name}`"
                if version:
                    pretty += f" - `{version}`"
                lines.append(f"- {pretty}")
            lines.append("")
    return "\n".join(lines).strip()


def build_env_answer(question: str, documents: list[EnvKeyDocument]) -> str | None:
    selected = choose_env_documents(question, documents)
    if not selected:
        return None

    total = sum(len(document.keys) for document in selected)
    lines = [f"I found **{total}** documented environment key(s).", ""]
    for document in selected:
        lines.append(f"### `{document.path}`")
        for key in document.keys:
            lines.append(f"- `{key}`")
        lines.append("")
        lines.append(f"Source: `{document.path}:{document.line_start}-{document.line_end}`")
        lines.append("")
    return "\n".join(lines).strip()


def extract_record_collections(workspace: Path) -> list[RecordCollection]:
    collections: list[RecordCollection] = []
    for path in iter_source_files(workspace):
        text = read_text_safely(path)
        if not text:
            continue
        suffix = path.suffix.lower()
        if suffix == ".py":
            collections.extend(extract_python_record_collections(workspace, path, text))
        elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
            collections.extend(extract_js_record_collections(workspace, path, text))
    return collections


def extract_python_record_collections(workspace: Path, path: Path, text: str) -> list[RecordCollection]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    collections: list[RecordCollection] = []
    for node in ast.walk(tree):
        label: str | None = None
        value = None
        if isinstance(node, ast.Assign):
            value = node.value
            for target in node.targets:
                if isinstance(target, ast.Name):
                    label = target.id
                    break
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            label = node.target.id
            value = node.value
        if not label or not isinstance(value, ast.List):
            continue
        parsed_items = [extract_python_record_item(element) for element in value.elts]
        items = tuple(item for item in parsed_items if item is not None)
        if len(items) < 2:
            continue
        collections.append(
            RecordCollection(
                path=path.relative_to(workspace).as_posix(),
                label=label,
                line_start=getattr(node, "lineno", 1),
                line_end=getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                items=items,
            )
        )
    return collections


def extract_python_record_item(node: ast.AST) -> RecordItem | None:
    if not isinstance(node, ast.Dict):
        return None
    fields: dict[str, str] = {}
    for key_node, value_node in zip(node.keys, node.values):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            continue
        value = python_scalar_value(value_node)
        if value is None:
            continue
        fields[key_node.value] = value
    if not fields:
        return None
    return RecordItem(fields=fields, line=getattr(node, "lineno", 1))


def python_scalar_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        if node.value is None:
            return None
        return str(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return str(-node.operand.value)
    return None


def extract_js_record_collections(workspace: Path, path: Path, text: str) -> list[RecordCollection]:
    collections: list[RecordCollection] = []
    for match in JS_ARRAY_RE.finditer(text):
        label = match.group(1)
        start = text.find("[", match.start())
        if start == -1:
            continue
        end = find_matching_bracket(text, start, "[", "]")
        if end == -1:
            continue
        items = extract_js_record_items(text[start + 1 : end])
        if len(items) < 2:
            continue
        collections.append(
            RecordCollection(
                path=path.relative_to(workspace).as_posix(),
                label=label,
                line_start=text.count("\n", 0, match.start()) + 1,
                line_end=text.count("\n", 0, end) + 1,
                items=tuple(items),
            )
        )
    return collections


def extract_js_record_items(body: str) -> list[RecordItem]:
    items: list[RecordItem] = []
    for raw_object, line in iter_js_objects(body):
        fields: dict[str, str] = {}
        for match in JS_PAIR_RE.finditer(raw_object):
            key = strip_js_quotes(match.group("key"))
            value = parse_js_scalar(match.group("value"))
            if value is not None:
                fields[key] = value
        if fields:
            items.append(RecordItem(fields=fields, line=line))
    return items


def iter_js_objects(body: str) -> list[tuple[str, int]]:
    objects: list[tuple[str, int]] = []
    depth = 0
    start = -1
    in_string: str | None = None
    escape = False
    line = 1
    start_line = 1
    for index, character in enumerate(body):
        if character == "\n":
            line += 1
        if in_string:
            if escape:
                escape = False
                continue
            if character == "\\":
                escape = True
                continue
            if character == in_string:
                in_string = None
            continue
        if character in {"'", '"'}:
            in_string = character
            continue
        if character == "{":
            if depth == 0:
                start = index
                start_line = line
            depth += 1
            continue
        if character == "}":
            depth -= 1
            if depth == 0 and start != -1:
                objects.append((body[start : index + 1], start_line))
                start = -1
    return objects


def parse_js_scalar(value: str) -> str | None:
    value = value.strip()
    if value in {"true", "false", "null"}:
        return None if value == "null" else value
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return strip_js_quotes(value)
    return value


def strip_js_quotes(value: str) -> str:
    raw = value.strip()
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')):
        try:
            return json.loads(raw.replace("'", '"'))
        except json.JSONDecodeError:
            return raw[1:-1]
    return raw


def find_matching_bracket(text: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    in_string: str | None = None
    escape = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if character == "\\":
                escape = True
                continue
            if character == in_string:
                in_string = None
            continue
        if character in {"'", '"'}:
            in_string = character
            continue
        if character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return index
    return -1


def extract_dependency_manifests(workspace: Path) -> list[DependencyManifest]:
    manifests: list[DependencyManifest] = []
    for path in iter_source_files(workspace):
        text = read_text_safely(path)
        if not text:
            continue
        relative = path.relative_to(workspace).as_posix()
        if path.name == "package.json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            sections: list[tuple[str, tuple[tuple[str, str], ...]]] = []
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                entries = data.get(section) or {}
                if not isinstance(entries, dict):
                    continue
                packages = tuple(sorted((str(name), str(version)) for name, version in entries.items()))
                if packages:
                    sections.append((section, packages))
            if sections:
                manifests.append(DependencyManifest(path=relative, ecosystem="node", sections=tuple(sections)))
        elif path.name == "requirements.txt":
            packages: list[tuple[str, str]] = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                requirement, _, version = line.partition("==")
                packages.append((requirement.strip(), version.strip()))
            if packages:
                manifests.append(
                    DependencyManifest(path=relative, ecosystem="python", sections=(("requirements", tuple(packages)),))
                )
    return manifests


def extract_env_key_documents(workspace: Path) -> list[EnvKeyDocument]:
    documents: list[EnvKeyDocument] = []
    for path in iter_source_files(workspace):
        lower_name = path.name.casefold()
        if not lower_name.startswith(".env") and not any(lower_name.endswith(name) for name in SENSITIVE_FILE_NAMES):
            continue
        text = read_text_safely(path)
        if not text:
            continue
        keys = tuple(match.group(1) for match in ENV_LINE_RE.finditer(text))
        if not keys:
            continue
        relative = path.relative_to(workspace).as_posix()
        documents.append(
            EnvKeyDocument(
                path=relative,
                line_start=1,
                line_end=len(text.splitlines()) or 1,
                keys=keys,
            )
        )
    return documents


def choose_record_collection(question: str, collections: list[RecordCollection]) -> RecordCollection | None:
    if not collections:
        return None
    tokens = question_tokens(question)
    scored = sorted(
        ((score_record_collection(tokens, collection), collection) for collection in collections),
        key=lambda item: (item[0], len(item[1].items)),
        reverse=True,
    )
    best_score, best = scored[0]
    if best_score <= 0 and len(best.items) < 5:
        return None
    return best


def score_record_collection(tokens: set[str], collection: RecordCollection) -> int:
    searchable = collection.search_blob
    score = 0
    for token in tokens:
        if token in searchable:
            score += 3
    label = collection.label.casefold()
    path = collection.path.casefold()
    if any(hint in label for hint in ("catalog", "catalogue", "inventory", "product", "item")):
        score += 4
    if any(hint in path for hint in ("shop", "catalog", "inventory", "product", "seed")):
        score += 4
    if {"shop", "store"} & tokens and "shop" in path:
        score += 4
    if {"product", "products", "item", "items"} & tokens and {"name", "product_id"} & collection.field_names:
        score += 4
    score += min(len(collection.items), 12) // 3
    return score


def choose_dependency_manifests(question: str, manifests: list[DependencyManifest]) -> list[DependencyManifest]:
    if not manifests:
        return []
    lowered = question.casefold()
    want_node = any(token in lowered for token in ("node", "npm", "frontend", "package.json", "vite", "react"))
    want_python = any(token in lowered for token in ("python", "pip", "requirements", "backend", "flask", "django", "fastapi"))
    if want_node and not want_python:
        selected = [manifest for manifest in manifests if manifest.ecosystem == "node"]
        return selected or manifests
    if want_python and not want_node:
        selected = [manifest for manifest in manifests if manifest.ecosystem == "python"]
        return selected or manifests
    return manifests


def choose_env_documents(question: str, documents: list[EnvKeyDocument]) -> list[EnvKeyDocument]:
    if not documents:
        return []
    lowered = question.casefold()
    if "backend" in lowered:
        selected = [document for document in documents if "backend" in document.path.casefold()]
        return selected or documents
    if "frontend" in lowered:
        selected = [document for document in documents if "frontend" in document.path.casefold()]
        return selected or documents
    return documents


def question_tokens(text: str) -> set[str]:
    tokens = {
        token.casefold()
        for token in QUESTION_TOKEN_RE.findall(text)
        if len(token) > 1 and token.casefold() not in STOPWORDS
    }
    normalized: set[str] = set()
    for token in tokens:
        normalized.add(token)
        if token.endswith("ies") and len(token) > 4:
            normalized.add(token[:-3] + "y")
        elif token.endswith("s") and len(token) > 3:
            normalized.add(token[:-1])
    return normalized


def contains_hint(text: str, hints: set[str]) -> bool:
    return any(hint in text for hint in hints)


def first_field(fields: dict[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = fields.get(key)
        if value:
            return value
    return None


def infer_record_noun(question: str, collection: RecordCollection) -> str:
    lowered = question.casefold()
    searchable = f"{collection.label} {collection.path}".casefold()
    if "shop" in lowered or "shop" in searchable or "marketplace" in searchable:
        return "shop catalogue"
    if "product" in lowered or "product" in searchable:
        return "product"
    if "inventory" in searchable:
        return "inventory"
    return "item"
