import subprocess
from pathlib import Path

import devagent.tools.edit_tool as edit_tool_module
from devagent.context.indexer import CodeIndexer
from devagent.tools.edit_tool import EditAgent, EditProposal, sanitize_unified_diff


def test_sanitize_unified_diff_removes_markdown_fence() -> None:
    raw = """```diff
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 Hello
+Thank you
```"""

    clean = sanitize_unified_diff(raw)

    assert clean is not None
    assert clean.startswith("--- a/README.md")
    assert "```" not in clean


def test_apply_handles_unicode_diff(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("Give it a star: \u2b50\n", encoding="utf-8")

    proposal = EditProposal(
        instruction="Add thanks",
        diff="""--- a/README.md
+++ b/README.md
@@ -1 +1,3 @@
 Give it a star: \u2b50
+
+Thank you \U0001f64f
""",
        message="Patch generated.",
    )

    EditAgent(tmp_path).apply(proposal)

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Thank you \U0001f64f" in text


def test_apply_recounts_bad_hunk_lengths(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text(
        "\n---\n\n## Support\nIf you like this project, give it a star on GitHub!\n",
        encoding="utf-8",
    )

    proposal = EditProposal(
        instruction="Add thankyou",
        diff="""--- a/README.md
+++ b/README.md
@@ -1,4 +1,4 @@
 
 ---
 
-## Support
-If you like this project, give it a star on GitHub!
+## Support Thankyou
+If you like this project, give it a star on GitHub! Thankyou
""",
        message="Patch generated.",
    )

    EditAgent(tmp_path).apply(proposal)

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "## Support Thankyou" in text


def test_apply_uses_safe_fallback_when_git_apply_rejects(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("Hello\n", encoding="utf-8")

    proposal = EditProposal(
        instruction="Change the greeting",
        diff="""--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-Hello
+Hello there
""",
        message="Patch generated.",
    )

    def fake_run(args, cwd=None, input=None, capture_output=None):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout=b"", stderr=b"patch does not apply")

    monkeypatch.setattr(edit_tool_module.subprocess, "run", fake_run)

    EditAgent(tmp_path).apply(proposal)

    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "Hello there\n"


def test_apply_fails_cleanly_for_unsupported_fallback_patch(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    source = tmp_path / "README.md"
    source.write_text("Hello\n", encoding="utf-8")

    proposal = EditProposal(
        instruction="Rename the file",
        diff="""--- a/README.md
+++ b/docs/README.md
@@ -1 +1 @@
-Hello
+Hello there
""",
        message="Patch generated.",
    )

    def fake_run(args, cwd=None, input=None, capture_output=None):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout=b"", stderr=b"patch does not apply")

    monkeypatch.setattr(edit_tool_module.subprocess, "run", fake_run)

    try:
        EditAgent(tmp_path).apply(proposal)
    except RuntimeError as exc:
        assert "Fallback apply failed" in str(exc)
    else:
        raise AssertionError("Expected fallback to reject rename-style patches.")

    assert source.read_text(encoding="utf-8") == "Hello\n"


def test_apply_handles_end_of_file_append_hunk(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("Intro\n\nAuthor\n", encoding="utf-8")

    proposal = EditProposal(
        instruction="Write a thank you at the end in README.md",
        diff="""--- a/README.md
+++ b/README.md
@@ -1,3 +1,6 @@
 Intro
 
 Author
+
+---
+Thank you for checking out this project!
""",
        message="Patch generated.",
    )

    EditAgent(tmp_path).apply(proposal)

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert text.endswith("Author\n\n---\nThank you for checking out this project!\n")


def test_apply_fallback_locates_hunk_when_line_numbers_drift(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text(
        "Intro\n\nAdd a countdown before each round\n\nAuthor\nAritrajit Guha\n",
        encoding="utf-8",
    )

    proposal = EditProposal(
        instruction="Add a thank you at the end in README.md",
        diff="""--- a/README.md
+++ b/README.md
@@ -62,3 +62,6 @@
 Add a countdown before each round
 
 Author
+
 Aritrajit Guha
+
+---
+Thank you for checking out this project!
""",
        message="Patch generated.",
    )

    def fake_run(args, cwd=None, input=None, capture_output=None):
        stderr = b"error: patch failed: README.md:62\nerror: README.md: patch does not apply"
        return subprocess.CompletedProcess(args=args, returncode=1, stdout=b"", stderr=stderr)

    monkeypatch.setattr(edit_tool_module.subprocess, "run", fake_run)

    EditAgent(tmp_path).apply(proposal)

    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert text.endswith("Author\n\nAritrajit Guha\n\n---\nThank you for checking out this project!\n")


class PromptCapturingAI:
    def __init__(self) -> None:
        self.available = True
        self.prompt = ""

    def complete(self, prompt: str, *, deep: bool = False, system_instruction: str | None = None) -> str:
        self.prompt = prompt
        return "NO_PATCH"

    def embed(self, texts):
        return None


def test_propose_rebuilds_stale_index_before_generating_diff(tmp_path: Path, monkeypatch) -> None:
    config_home = tmp_path / "config-home"
    monkeypatch.setenv("DEVAGENT_CONFIG_DIR", str(config_home))

    readme = tmp_path / "README.md"
    readme.write_text("Old ending\nAritrajit Guha\n", encoding="utf-8")
    CodeIndexer(tmp_path, chunk_lines=10).build()

    readme.write_text("New ending\nagentic and personal.\n", encoding="utf-8")

    fake_ai = PromptCapturingAI()
    monkeypatch.setattr(edit_tool_module.AIClient, "from_env", classmethod(lambda cls: fake_ai))

    proposal = EditAgent(tmp_path).propose("write a thank you at the end in README.md")

    assert proposal.diff is None
    assert "agentic and personal." in fake_ai.prompt
    assert "Aritrajit Guha" not in fake_ai.prompt
