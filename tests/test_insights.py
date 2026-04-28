from devagent.tools.insights import is_sensitive_file, python_function_findings, secret_findings, sensitive_file_findings


def test_secret_detection() -> None:
    findings = secret_findings("config.py", 'API_KEY = "1234567890abcdef1234"')  # devagent: ignore-secret
    assert findings


def test_large_function_detection() -> None:
    body = "\n".join("    x = 1" for _ in range(101))
    text = f"def huge():\n{body}\n"
    findings = python_function_findings("app.py", text, max_lines=100)
    assert findings


def test_detects_mongo_uri_and_jwt() -> None:
    text = 'MONGO_URI = "mongodb+srv://user:pass@example.mongodb.net/app"\nTOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiYWRtaW4ifQ.signaturetoken123"\n'
    findings = secret_findings("config.env", text)

    messages = {finding.message for finding in findings}
    assert "Mongo connection string exposed" in messages
    assert "JWT-like token exposed" in messages


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
    assert not is_sensitive_file("client/package.json")
