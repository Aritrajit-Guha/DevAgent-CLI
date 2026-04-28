from __future__ import annotations

import re
from pathlib import Path

from devagent.context.indexer import CodeIndexer
from devagent.context.retriever import Retriever
from devagent.core.project import detect_project
from devagent.core.session_store import SessionStore
from devagent.tools.ai import AIClient


class RepoAgent:
    def __init__(self, workspace: Path):
        self.workspace = workspace.expanduser().resolve()
        self.ai = AIClient.from_env()
        self.sessions = SessionStore(self.workspace)

    def clear_session(self) -> None:
        self.sessions.clear()

    def answer(self, question: str, *, deep: bool = False, new_session: bool = False) -> str:
        if new_session:
            self.clear_session()
        index = CodeIndexer(self.workspace).load_or_build()
        intent = classify_intent(question)
        queries = expand_queries(question, intent)
        chunks = Retriever(index).search_hybrid(queries, limit=12 if deep else 8)
        project = detect_project(self.workspace)
        session = self.sessions.load()
        context = "\n\n".join(render_chunk(chunk) for chunk in chunks)
        relevant_files = summarize_files(chunks)
        if self.ai.available:
            system_instruction = (
                "You are DevAgent, a workspace-aware local developer assistant. "
                "Answer like a strong repo expert: grounded, specific, detailed, and practical. "
                "Use only the supplied repo context and conversation memory. "
                "The user is on Windows. Do not suggest Unix-only commands such as cat, grep, or ls. "
                "Prefer DevAgent commands first, such as `devagent workspace status`, `devagent index`, "
                "`devagent packages`, `devagent inspect`, and `devagent run start`. "
                "If context is incomplete, say exactly what is missing, note the ambiguity, and suggest one Windows-friendly next step."
            )
            prompt = build_prompt(
                question=question,
                intent=intent,
                queries=queries,
                project=project,
                session=session,
                relevant_files=relevant_files,
                context=context,
                deep=deep,
            )
            response = self.ai.complete(prompt, deep=deep, system_instruction=system_instruction)
            if response:
                self.sessions.append_exchange(question, response)
                return response

        if not chunks:
            return "I could not find matching code context. Run `devagent index` and try a more specific question."

        fallback = build_grounded_fallback(
            question=question,
            intent=intent,
            project=project,
            session=session,
            chunks=chunks,
            relevant_files=relevant_files,
        )
        self.sessions.append_exchange(question, fallback)
        return fallback


INTENT_PATTERNS = {
    "dependency": re.compile(r"\b(package|dependency|dependencies|npm|pip|library|libraries)\b", re.IGNORECASE),
    "security": re.compile(r"\b(secret|security|token|auth|vulnerab|jwt|api key)\b", re.IGNORECASE),
    "debug": re.compile(r"\b(error|bug|issue|fail|failing|broken|debug|traceback)\b", re.IGNORECASE),
    "find": re.compile(r"\b(where|find|locate|which file|which folder)\b", re.IGNORECASE),
    "architecture": re.compile(r"\b(architecture|structure|project structure|how is .* organized|overview)\b", re.IGNORECASE),
    "how-it-works": re.compile(r"\b(flow|how does|how do|what happens|implementation)\b", re.IGNORECASE),
}


def classify_intent(question: str) -> str:
    for intent, pattern in INTENT_PATTERNS.items():
        if pattern.search(question):
            return intent
    if question.strip().casefold().startswith("explain"):
        return "explain"
    return "explain"


def expand_queries(question: str, intent: str) -> list[str]:
    queries = [question.strip()]
    keywords = extract_keywords(question)
    if keywords:
        queries.append(" ".join(keywords[:8]))

    path_terms = [token for token in question.replace("\\", "/").split() if "/" in token or "." in token]
    if path_terms:
        queries.append(" ".join(path_terms))

    intent_suffix = {
        "architecture": "project structure modules entrypoints data flow",
        "dependency": "package dependencies imports requirements package.json",
        "find": "file path module location implementation",
        "security": "auth token secret config environment",
        "debug": "error handling flow logs failing code path",
        "how-it-works": "request flow implementation control path",
        "explain": "module responsibilities key files",
    }.get(intent)
    if intent_suffix:
        queries.append(f"{question.strip()} {intent_suffix}")
    return unique_queries(queries)


def extract_keywords(question: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_./-]*", question)
    stopwords = {"the", "this", "that", "what", "where", "which", "does", "with", "from", "into", "about", "there", "inside"}
    return [token for token in tokens if token.casefold() not in stopwords]


def unique_queries(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        compact = " ".join(value.split())
        if compact and compact not in seen:
            seen.append(compact)
    return seen


def render_chunk(chunk) -> str:
    metadata = []
    if chunk.symbols:
        metadata.append(f"Symbols: {', '.join(chunk.symbols)}")
    if chunk.imports:
        metadata.append(f"Imports: {', '.join(chunk.imports[:4])}")
    if chunk.headings:
        metadata.append(f"Headings: {', '.join(chunk.headings)}")
    metadata_block = "\n".join(metadata)
    prefix = f"File: {chunk.path}\nLines: {chunk.start_line}-{chunk.end_line}"
    if metadata_block:
        prefix += f"\n{metadata_block}"
    return f"{prefix}\n{chunk.text}"


def summarize_files(chunks) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.path in seen:
            continue
        seen.add(chunk.path)
        notes = []
        if chunk.symbols:
            notes.append(f"symbols: {', '.join(chunk.symbols[:3])}")
        if chunk.headings:
            notes.append(f"headings: {', '.join(chunk.headings[:2])}")
        detail = f" ({'; '.join(notes)})" if notes else ""
        lines.append(f"- {chunk.path}:{chunk.start_line}-{chunk.end_line}{detail}")
    return lines


def build_prompt(*, question: str, intent: str, queries: list[str], project, session, relevant_files: list[str], context: str, deep: bool) -> str:
    recent_turns = session.turns[-4:]
    history_block = "\n".join(f"{turn.role.upper()}: {turn.content}" for turn in recent_turns) or "No prior conversation."
    summary = session.summary or "No prior conversation summary."
    quality_note = "Use a broader, more thorough synthesis." if deep else "Stay concise where possible, but still be meaningfully detailed."
    return (
        f"Question intent: {intent}\n"
        f"Answer style: detailed repo expert\n"
        f"Quality mode: {'deep' if deep else 'fast'}\n"
        f"{quality_note}\n\n"
        f"Workspace summary:\n"
        f"- Path: {project.path}\n"
        f"- Project types: {', '.join(project.project_types) or 'unknown'}\n"
        f"- Package files: {', '.join(project.package_files) or 'none'}\n"
        f"- Top-level tree:\n  - " + "\n  - ".join(project.file_tree[:25]) + "\n\n"
        f"Conversation summary:\n{summary}\n\n"
        f"Recent turns:\n{history_block}\n\n"
        f"Expanded retrieval queries:\n- " + "\n- ".join(queries) + "\n\n"
        f"Most relevant files:\n" + ("\n".join(relevant_files) if relevant_files else "- none") + "\n\n"
        "When you answer:\n"
        "- Explain what you found before you generalize.\n"
        "- Cite relevant files with line references like path:start-end.\n"
        "- Describe how pieces connect.\n"
        "- Call out ambiguity clearly.\n"
        "- Suggest next repo-aware follow-ups only when useful.\n\n"
        f"Repo context:\n{context or 'No indexed code chunks matched.'}\n\n"
        f"User question:\n{question}"
    )


def build_grounded_fallback(*, question: str, intent: str, project, session, chunks, relevant_files: list[str]) -> str:
    lines = [
        f"I found grounded repo context for your {intent} question, but Gemini is not available right now.",
        "",
        "What I found:",
        *(relevant_files or ["- No indexed chunks matched directly."]),
        "",
        f"Project types: {', '.join(project.project_types) or 'unknown'}",
        f"Package files: {', '.join(project.package_files) or 'none'}",
    ]
    if session.summary:
        lines.extend(["", f"Conversation memory: {session.summary}"])
    if chunks:
        lines.extend(["", "Best next step:", "Set GEMINI_API_KEY to get a synthesized answer over these exact files."])
    else:
        lines.extend(["", "Best next step:", "Run `devagent index` and ask a more specific question about a file, route, module, or feature."])
    return "\n".join(lines)
