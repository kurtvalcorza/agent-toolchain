from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_toolchain.state as state_module
from agent_toolchain.adapters.codex import CodexAdapter
from agent_toolchain.models import InstallState
from agent_toolchain.state import StateError, load_state, write_state


def test_adapter_paths_remain_stable_after_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    adapter = CodexAdapter(Path("relative-codex"))

    expected_root = tmp_path / "relative-codex"
    state_path = adapter.install_state_path()
    destination = adapter.destination_for("skills/base/SKILL.md")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert adapter.root == expected_root
    assert state_path == expected_root / ".agent-toolchain/install-state.json"
    assert adapter.install_state_path() == state_path
    assert adapter.destination_for("skills/base/SKILL.md") == destination


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1, "target": "codex", "files": []},
        {
            "schema_version": 1,
            "target": "codex",
            "target_root": "/tmp/codex",
            "files": ["not-an-object"],
        },
        {
            "schema_version": 1,
            "target": "codex",
            "target_root": "/tmp/codex",
            "metadata": {"revision": 123},
        },
    ],
)
def test_load_state_rejects_malformed_structure(tmp_path: Path, payload: object) -> None:
    state_path = tmp_path / "install-state.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StateError, match="invalid install state"):
        load_state(state_path)


def test_write_state_cleans_temporary_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = InstallState(
        schema_version=1,
        target="codex",
        target_root=str(tmp_path / "codex"),
        profile=None,
        modules=(),
        files=(),
        metadata={},
    )
    state_path = tmp_path / "state" / "install-state.json"
    temporary = state_path.with_name(f".{state_path.name}.tmp")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"cannot replace {source} -> {destination}")

    monkeypatch.setattr(state_module.os, "replace", fail_replace)

    with pytest.raises(StateError, match="cannot write install state"):
        write_state(state_path, state)

    assert not temporary.exists()
    assert not state_path.exists()
