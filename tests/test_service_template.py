"""Tests for hello-operator.service.template at the project root."""

import pathlib

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "hello-operator.service.template"
GITIGNORE_PATH = PROJECT_ROOT / ".gitignore"


def _substituted(content: str) -> str:
    """Apply placeholder substitution with test values."""
    return content.replace("%%INSTALL_DIR%%", "/some/path").replace("%%USER%%", "alice")


def test_template_exists():
    """hello-operator.service.template must be present at the project root."""
    assert TEMPLATE_PATH.exists(), f"Template file not found: {TEMPLATE_PATH}"


def test_template_contains_placeholders():
    """Template must contain both %%INSTALL_DIR%% and %%USER%% placeholders."""
    content = TEMPLATE_PATH.read_text()
    assert "%%INSTALL_DIR%%" in content, "Template missing %%INSTALL_DIR%% placeholder"
    assert "%%USER%%" in content, "Template missing %%USER%% placeholder"


def test_substitution_removes_all_placeholders():
    """After substituting both placeholders, no %% substrings should remain."""
    content = TEMPLATE_PATH.read_text()
    result = _substituted(content)
    assert "%%" not in result, f"Unreplaced placeholders remain after substitution: {result}"


def test_substituted_output_has_required_sections():
    """After substitution the text must contain [Unit], [Service], and [Install]."""
    content = TEMPLATE_PATH.read_text()
    result = _substituted(content)
    assert "[Unit]" in result, "Substituted output missing [Unit] section"
    assert "[Service]" in result, "Substituted output missing [Service] section"
    assert "[Install]" in result, "Substituted output missing [Install] section"


def test_substituted_exec_start_contains_path():
    """ExecStart line must contain the substituted INSTALL_DIR path."""
    content = TEMPLATE_PATH.read_text()
    result = _substituted(content)
    exec_lines = [line for line in result.splitlines() if line.startswith("ExecStart=")]
    assert exec_lines, "No ExecStart= line found in substituted output"
    assert "/some/path" in exec_lines[0], (
        f"ExecStart line does not contain substituted path: {exec_lines[0]}"
    )


def test_generated_file_not_tracked():
    """hello-operator.service (without .template) must appear in .gitignore."""
    content = GITIGNORE_PATH.read_text()
    lines = [line.strip() for line in content.splitlines()]
    assert "hello-operator.service" in lines, (
        "hello-operator.service is not listed in .gitignore"
    )
