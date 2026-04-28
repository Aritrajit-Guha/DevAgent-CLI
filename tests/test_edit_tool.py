import subprocess
from pathlib import Path

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
