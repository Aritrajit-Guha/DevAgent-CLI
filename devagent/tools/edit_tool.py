from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.tools.ai import AIClient

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")


@dataclass(frozen=True)
class EditProposal:
    instruction: str
    diff: str | None
    message: str


@dataclass(frozen=True)
class ParsedHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ParsedFilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[ParsedHunk, ...]


class PatchApplyError(RuntimeError):
    pass


class EditAgent:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.ai = AIClient.from_env()

    def propose(self, instruction: str) -> EditProposal:
        index = CodeIndexer(self.workspace).load_or_build()
        chunks = Retriever(index).search(instruction, limit=8)
        context = "\n\n".join(
            f"File: {chunk.path}\nLines: {chunk.start_line}-{chunk.end_line}\n{chunk.text}" for chunk in chunks
        )
        if not self.ai.available:
            files = "\n".join(f"- {chunk.path}:{chunk.start_line}-{chunk.end_line}" for chunk in chunks)
            return EditProposal(
                instruction=instruction,
                diff=None,
                message=(
                    "Gemini is not configured, so I will not invent a patch. "
                    "Set GEMINI_API_KEY and rerun this command.\n\nRelevant files:\n"
                    f"{files or 'No relevant files found.'}"
                ),
            )

        prompt = (
            "You are a careful coding agent. Produce only a valid unified diff that can be applied with git apply. "
            "Do not include Markdown fences or explanations. Keep changes minimal and scoped to the instruction. "
            "If the context is insufficient, output exactly: NO_PATCH\n\n"
            f"Instruction: {instruction}\n\nContext:\n{context}"
        )
        diff = self.ai.complete(prompt)
        if not diff or diff.strip() == "NO_PATCH" or "AI request failed:" in diff:
            return EditProposal(instruction=instruction, diff=None, message=diff or "No patch generated.")
        clean_diff = sanitize_unified_diff(diff)
        if not clean_diff:
            return EditProposal(instruction=instruction, diff=None, message="No valid unified diff was generated.")
        return EditProposal(instruction=instruction, diff=clean_diff, message="Patch generated.")

    def apply(self, proposal: EditProposal) -> None:
        if not proposal.diff:
            raise ValueError("No diff is available to apply.")

        diff_bytes = proposal.diff.encode("utf-8")
        check_result = self._run_git_apply(["--check"], diff_bytes)
        apply_result = self._run_git_apply(["--recount", "--whitespace=fix"], diff_bytes)
        if apply_result.returncode == 0:
            return

        git_errors = [
            format_git_apply_error("git apply --check", check_result),
            format_git_apply_error("git apply --recount --whitespace=fix", apply_result),
        ]
        try:
            apply_unified_diff_fallback(proposal.diff, self.workspace)
            return
        except PatchApplyError as exc:
            detail = "\n".join(error for error in git_errors if error)
            if detail:
                raise RuntimeError(f"{detail}\nFallback apply failed: {exc}") from exc
            raise RuntimeError(f"Fallback apply failed: {exc}") from exc

    def _run_git_apply(self, args: list[str], diff_bytes: bytes) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "apply", *args, "-"],
            cwd=self.workspace,
            input=diff_bytes,
            capture_output=True,
        )


def sanitize_unified_diff(raw: str) -> str | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    start_markers = ("diff --git ", "--- a/", "--- /", "Index: ")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(start_markers):
            cleaned = "\n".join(lines[index:]).strip()
            return f"{cleaned}\n" if cleaned else None
    return None


def format_git_apply_error(label: str, result: subprocess.CompletedProcess[bytes]) -> str:
    if result.returncode == 0:
        return ""
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    message = stderr or stdout
    if not message:
        return ""
    return f"{label} failed: {message}"


def apply_unified_diff_fallback(diff: str, workspace: Path) -> None:
    patches = parse_unified_diff(diff)
    if not patches:
        raise PatchApplyError("No supported file patches were found in the generated diff.")

    staged_updates: dict[Path, str] = {}
    for patch in patches:
        target_rel = patch_target_path(patch)
        target_path = workspace / target_rel

        if patch.old_path is not None and patch.new_path is not None and patch.old_path != patch.new_path:
            raise PatchApplyError("Rename and move patches are not supported by the fallback apply path.")
        if patch.old_path is None and target_path.exists():
            raise PatchApplyError(f"The fallback patch expected a new file, but `{target_rel}` already exists.")
        if patch.old_path is not None and not target_path.exists():
            raise PatchApplyError(f"The fallback patch expected `{target_rel}` to exist.")

        original_text = target_path.read_text(encoding="utf-8", errors="replace") if target_path.exists() else ""
        original_lines = original_text.splitlines()
        updated_lines = apply_hunks_to_lines(original_lines, patch, target_rel)
        trailing_newline = infer_trailing_newline(original_text, updated_lines)
        staged_updates[target_path] = render_lines(updated_lines, trailing_newline)

    for target_path, rendered in staged_updates.items():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(rendered, encoding="utf-8")


def parse_unified_diff(diff: str) -> tuple[ParsedFilePatch, ...]:
    lines = diff.splitlines()
    patches: list[ParsedFilePatch] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git ") or line.startswith("Index: ") or line.startswith("index "):
            index += 1
            continue
        if line.startswith(("new file mode", "deleted file mode", "similarity index", "rename from ", "rename to ")):
            index += 1
            continue
        if not line.startswith("--- "):
            index += 1
            continue

        old_path = parse_patch_path(line[4:])
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise PatchApplyError("Generated diff is missing the `+++` file header.")
        new_path = parse_patch_path(lines[index][4:])
        index += 1

        hunks: list[ParsedHunk] = []
        while index < len(lines):
            current = lines[index]
            if current.startswith("--- "):
                break
            if current.startswith(("diff --git ", "Index: ")):
                break
            if current.startswith("@@ "):
                hunks.append(parse_hunk(lines, index))
                index = advance_past_hunk(lines, index)
                continue
            if current.startswith(("new file mode", "deleted file mode", "index ", "similarity index", "rename from ", "rename to ")):
                index += 1
                continue
            if current.strip():
                raise PatchApplyError(f"Unsupported patch content: {current}")
            index += 1

        patches.append(ParsedFilePatch(old_path=old_path, new_path=new_path, hunks=tuple(hunks)))
    return tuple(patches)


def parse_hunk(lines: list[str], start_index: int) -> ParsedHunk:
    header = lines[start_index]
    match = HUNK_RE.match(header)
    if not match:
        raise PatchApplyError(f"Unsupported hunk header: {header}")
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")

    hunk_lines: list[str] = []
    index = start_index + 1
    while index < len(lines):
        line = lines[index]
        if line.startswith(("diff --git ", "Index: ", "--- ", "@@ ")):
            break
        if line.startswith("\\ No newline at end of file"):
            hunk_lines.append("\\ No newline at end of file")
            index += 1
            continue
        if not line or line[0] not in {" ", "+", "-"}:
            raise PatchApplyError(f"Unsupported hunk line: {line}")
        hunk_lines.append(line)
        index += 1

    return ParsedHunk(
        old_start=old_start,
        old_count=old_count,
        new_start=new_start,
        new_count=new_count,
        lines=tuple(hunk_lines),
    )


def advance_past_hunk(lines: list[str], start_index: int) -> int:
    index = start_index + 1
    while index < len(lines):
        line = lines[index]
        if line.startswith(("diff --git ", "Index: ", "--- ", "@@ ")):
            return index
        index += 1
    return index


def parse_patch_path(raw: str) -> str | None:
    value = raw.strip().split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        return value[2:]
    return value


def patch_target_path(patch: ParsedFilePatch) -> str:
    if patch.old_path is None and patch.new_path is None:
        raise PatchApplyError("Patch is missing both source and target paths.")
    if patch.old_path is not None and patch.new_path is not None and patch.old_path != patch.new_path:
        raise PatchApplyError("Rename patches are not supported by the fallback apply path.")
    return patch.new_path or patch.old_path or ""


def apply_hunks_to_lines(original_lines: list[str], patch: ParsedFilePatch, target_rel: str) -> list[str]:
    result: list[str] = []
    cursor = 0
    for hunk in patch.hunks:
        start_index = locate_hunk_source_index(original_lines, hunk, cursor, target_rel)
        if start_index < cursor:
            raise PatchApplyError(f"Patch hunks overlap while updating `{target_rel}`.")
        result.extend(original_lines[cursor:start_index])
        source_index = start_index
        for line in hunk.lines:
            if line.startswith("\\ No newline at end of file"):
                continue
            prefix = line[:1]
            text = line[1:]
            if prefix == " ":
                if source_index >= len(original_lines) or original_lines[source_index] != text:
                    raise PatchApplyError(f"Context mismatch while updating `{target_rel}`.")
                result.append(text)
                source_index += 1
            elif prefix == "-":
                if source_index >= len(original_lines) or original_lines[source_index] != text:
                    raise PatchApplyError(f"Removal mismatch while updating `{target_rel}`.")
                source_index += 1
            elif prefix == "+":
                result.append(text)
            else:
                raise PatchApplyError(f"Unsupported patch line while updating `{target_rel}`: {line}")
        cursor = source_index
    result.extend(original_lines[cursor:])
    return result


def locate_hunk_source_index(
    original_lines: list[str],
    hunk: ParsedHunk,
    cursor: int,
    target_rel: str,
) -> int:
    preferred = max(hunk.old_start - 1, cursor, 0)
    source_lines = [line[1:] for line in hunk.lines if line and line[:1] in {" ", "-"}]

    if not source_lines:
        return min(preferred, len(original_lines))

    if hunk_matches_at(original_lines, preferred, source_lines):
        return preferred

    search_limit = len(original_lines) - len(source_lines) + 1
    candidates = [
        index
        for index in range(cursor, max(cursor, search_limit))
        if hunk_matches_at(original_lines, index, source_lines)
    ]
    if not candidates:
        raise PatchApplyError(f"Context mismatch while updating `{target_rel}`.")
    return min(candidates, key=lambda index: abs(index - preferred))


def hunk_matches_at(original_lines: list[str], start_index: int, source_lines: list[str]) -> bool:
    if start_index < 0:
        return False
    end_index = start_index + len(source_lines)
    if end_index > len(original_lines):
        return False
    return original_lines[start_index:end_index] == source_lines


def infer_trailing_newline(original_text: str, updated_lines: list[str]) -> bool:
    if not updated_lines:
        return False
    return original_text.endswith("\n") or not original_text


def render_lines(lines: list[str], trailing_newline: bool) -> str:
    rendered = "\n".join(lines)
    if trailing_newline:
        rendered += "\n"
    return rendered
