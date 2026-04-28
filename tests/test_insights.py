from devagent.tools.insights import python_function_findings, secret_findings


def test_secret_detection() -> None:
    findings = secret_findings("config.py", 'API_KEY = "1234567890abcdef1234"')  # devagent: ignore-secret
    assert findings


def test_large_function_detection() -> None:
    body = "\n".join("    x = 1" for _ in range(101))
    text = f"def huge():\n{body}\n"
    findings = python_function_findings("app.py", text, max_lines=100)
    assert findings
