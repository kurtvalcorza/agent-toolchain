from __future__ import annotations

from pathlib import Path

import pytest

import agent_toolchain.apply as apply_module
from agent_toolchain.apply import ApplyError, apply_plan
from agent_toolchain.models import InstallPlan, Operation


def test_apply_refuses_source_mutation_between_digest_check_and_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "staging"
    source_root.mkdir()
    source = source_root / "SKILL.md"
    source.write_text("planned\n", encoding="utf-8")

    target_root = tmp_path / "target"
    destination = target_root / "skills" / "demo" / "SKILL.md"
    state_path = target_root / ".agent-toolchain" / "state.json"
    plan = InstallPlan(
        target="codex",
        profile=None,
        components=(),
        modules=("demo",),
        operations=(
            Operation(
                kind="copy_file",
                module_id="demo",
                source_relative_path="SKILL.md",
                destination_path=str(destination),
            ),
        ),
        target_root=str(target_root),
    )

    original_copy = apply_module._copy_source_to_temp

    def mutate_then_copy(source_path: Path, directory: Path) -> tuple[Path, str]:
        source_path.write_text("mutated after planned digest\n", encoding="utf-8")
        return original_copy(source_path, directory)

    monkeypatch.setattr(apply_module, "_copy_source_to_temp", mutate_then_copy)

    with pytest.raises(ApplyError, match="staged source changed while copying"):
        apply_plan(plan, source_root=source_root, state_path=state_path)

    assert not destination.exists()
    assert not state_path.exists()
