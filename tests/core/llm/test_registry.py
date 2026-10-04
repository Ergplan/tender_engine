from pathlib import Path

import pytest

from core.llm.registry import UnregisteredPromptError, load_prompt

HEADER = "---\npurpose: p\ninputs: i\noutput_schema: s\nknown_failure_modes: k\n---\n"


def test_loads_the_smoke_prompt_with_its_header() -> None:
    prompt = load_prompt("smoke", "v1")
    assert prompt.name == "smoke" and prompt.version == "v1"
    assert prompt.header["output_schema"] == "core.llm.smoke.SmokeResult"
    assert "connectivity check" in prompt.text
    assert not prompt.text.startswith("---")
    assert len(prompt.sha256) == 64


def test_refuses_an_unregistered_version() -> None:
    with pytest.raises(UnregisteredPromptError, match="smoke/v99 is not registered"):
        load_prompt("smoke", "v99")


@pytest.mark.parametrize(
    ("name", "version"), [("../etc", "v1"), ("smoke", "1"), ("Smoke", "v1"), ("smoke", "v1.md")]
)
def test_refuses_malformed_references(name: str, version: str) -> None:
    with pytest.raises(UnregisteredPromptError, match="invalid prompt reference"):
        load_prompt(name, version)


def test_refuses_a_prompt_without_a_header(tmp_path: Path) -> None:
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "v1.md").write_text("Just a body.\n")
    with pytest.raises(UnregisteredPromptError, match="no header block"):
        load_prompt("bare", "v1", roots=(tmp_path,))


def test_refuses_a_header_missing_a_required_key(tmp_path: Path) -> None:
    (tmp_path / "thin").mkdir()
    (tmp_path / "thin" / "v1.md").write_text("---\npurpose: p\n---\nBody.\n")
    with pytest.raises(UnregisteredPromptError, match="missing"):
        load_prompt("thin", "v1", roots=(tmp_path,))


def test_refuses_an_empty_body(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "v1.md").write_text(HEADER)
    with pytest.raises(UnregisteredPromptError, match="empty body"):
        load_prompt("empty", "v1", roots=(tmp_path,))


def test_later_roots_are_searched(tmp_path: Path) -> None:
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "v2.md").write_text(HEADER + "Second root body.\n")
    prompt = load_prompt("extra", "v2", roots=(tmp_path / "nowhere", tmp_path))
    assert prompt.text == "Second root body."


def test_a_prompt_that_extends_another_carries_the_parents_text_and_a_hash_of_both(
    tmp_path: Path,
) -> None:
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "v1.md").write_text(HEADER + "Base rules.\n")
    (tmp_path / "child" / "sub").mkdir(parents=True)
    child = tmp_path / "child" / "sub" / "v1.md"
    child.write_text(HEADER.replace("---\n", "---\nextends: base/v1\n", 1) + "Domain guidance.\n")
    parent = load_prompt("base", "v1", roots=(tmp_path,))
    prompt = load_prompt("child/sub", "v1", roots=(tmp_path,))
    assert prompt.text == "Base rules.\n\nDomain guidance."
    assert prompt.header["extends"] == "base/v1" and prompt.sha256 != parent.sha256
    (tmp_path / "base" / "v1.md").write_text(HEADER + "Base rules, changed.\n")
    assert load_prompt("child/sub", "v1", roots=(tmp_path,)).sha256 != prompt.sha256


def test_a_prompt_cannot_extend_itself_or_an_unregistered_prompt(tmp_path: Path) -> None:
    for name, parent in (("loop", "loop/v1"), ("orphan", "missing/v1")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "v1.md").write_text(
            HEADER.replace("---\n", f"---\nextends: {parent}\n", 1) + "Body.\n"
        )
        with pytest.raises(UnregisteredPromptError):
            load_prompt(name, "v1", roots=(tmp_path,))
