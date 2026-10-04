"""Prompt registry: prompts are versioned files under core/llm/prompts/<name>/vN.md.

A prompt that is not on disk under a registered root cannot be run. The version string
is stored on every llm_call_log row (and, from Stage 1, on every candidate).
"""

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel

CORE_PROMPT_ROOT = Path(__file__).parent / "prompts"
_NAME = re.compile(r"^[a-z0-9_]+(/[a-z0-9_]+)*$")
_VERSION = re.compile(r"^v[0-9]+$")


class UnregisteredPromptError(LookupError):
    pass


class Prompt(BaseModel):
    name: str
    version: str
    header: dict[str, str]
    text: str
    sha256: str


def load_prompt(name: str, version: str, roots: tuple[Path, ...] = (CORE_PROMPT_ROOT,)) -> Prompt:
    """Load prompt <name>/<version>.md from the first root that has it, or refuse."""
    if not _NAME.match(name) or not _VERSION.match(version):
        raise UnregisteredPromptError(f"invalid prompt reference {name!r} {version!r}")
    for root in roots:
        path = root / name / f"{version}.md"
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            header, text = _split(raw, path)
            return Prompt(
                name=name,
                version=version,
                header=header,
                text=text,
                sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            )
    raise UnregisteredPromptError(f"prompt {name}/{version} is not registered")


def _split(raw: str, path: Path) -> tuple[dict[str, str], str]:
    """Split the header block (between two '---' lines) from the prompt body."""
    parts = raw.split("---\n", 2)
    if len(parts) != 3 or parts[0].strip():
        raise UnregisteredPromptError(f"{path} has no header block")
    header: dict[str, str] = {}
    for line in parts[1].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            header[key.strip()] = value.strip()
    required = {"purpose", "inputs", "output_schema", "known_failure_modes"}
    missing = required - header.keys()
    if missing:
        raise UnregisteredPromptError(f"{path} header is missing {sorted(missing)}")
    body = parts[2].strip()
    if not body:
        raise UnregisteredPromptError(f"{path} has an empty body")
    return header, body
