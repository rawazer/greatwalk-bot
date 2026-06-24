"""Ensure sensitive runtime files are excluded from version control."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GITIGNORE = REPO_ROOT / ".gitignore"


def _gitignore_patterns() -> set[str]:
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_config_yaml_is_gitignored():
    patterns = _gitignore_patterns()
    assert "config.yaml" in patterns


def test_runtime_directories_are_gitignored():
    patterns = _gitignore_patterns()
    assert "logs/" in patterns
    assert "data/" in patterns


def test_secret_patterns_are_gitignored():
    patterns = _gitignore_patterns()
    assert any("env" in pattern.lower() for pattern in patterns)
