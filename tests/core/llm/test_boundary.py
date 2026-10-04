"""Operating rule 8: no Anthropic SDK use outside core/llm/."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ("core", "tender", "api", "worker", "scripts")
PATTERN = re.compile(r"^\s*(import anthropic|from anthropic)\b", re.MULTILINE)


def test_only_core_llm_imports_the_anthropic_sdk() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for package in PACKAGES
        for path in (ROOT / package).rglob("*.py")
        if PATTERN.search(path.read_text(encoding="utf-8"))
        and not path.is_relative_to(ROOT / "core" / "llm")
    ]
    assert offenders == []
