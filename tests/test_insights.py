from pathlib import Path

from devagent.tools.insights import Inspector, is_sensitive_file, secret_findings, sensitive_file_findings


def test_secret_detection() -> None:
    findings = secret_findings("config.py", 'API_KEY = "1234567890abcdef1234"')  # devagent: ignore-secret
    assert findings


def test_large_functions_are_not_reported_anymore(tmp_path: Path) -> None:
    body = "\n".join("    x = 1" for _ in range(101))
    (tmp_path / "app.py").write_text(f"def huge():\n{body}\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("API_KEY=placeholder\n", encoding="utf-8")

    findings = Inspector(tmp_path).run()

    assert not any("Large function" in finding.message for finding in findings)


def test_detects_mongo_uri_and_jwt() -> None:
    text = 'MONGO_URI = "mongodb+srv://user:pass@example.mongodb.net/app"\nTOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWRtaW4ifQ.signaturetoken123"\n'
    findings = secret_findings("config.env", text)

    messages = {finding.message for finding in findings}
    assert "Mongo connection string exposed" in messages
    assert "JWT-like token exposed" in messages


def test_skips_example_mongo_uri_in_docs() -> None:
    text = 'Example: MONGO_URI="mongodb+srv://<username>:<password>@cluster.example.mongodb.net/dbname"\n'

    findings = secret_findings("README.md", text)

    assert findings == []


def test_skips_ignored_env_secret_contents() -> None:
    findings = secret_findings(".env", 'JWT_SECRET="super-secret-value"', tracked=False, ignored=True)

    assert findings == []


def test_sensitive_file_tracking_and_ignore_logic() -> None:
    tracked = sensitive_file_findings(".env", tracked=True, ignored=False)
    unignored = sensitive_file_findings(".env.local", tracked=False, ignored=False)
    ignored = sensitive_file_findings(".env.production", tracked=False, ignored=True)

    assert tracked and tracked[0].severity == "high"
    assert unignored and unignored[0].severity == "high"
    assert ignored == []


def test_sensitive_file_name_detection() -> None:
    assert is_sensitive_file(".env")
    assert is_sensitive_file(".env.production")
    assert is_sensitive_file("keys/service.key")
    assert not is_sensitive_file(".env.production.example")
    assert not is_sensitive_file("client/package.json")


def test_nested_env_template_satisfies_env_example_requirement(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / ".env.example").write_text("MONGO_URI=placeholder\n", encoding="utf-8")

    findings = Inspector(tmp_path).run()

    assert not any(finding.message.startswith("Missing .env.example") for finding in findings)
