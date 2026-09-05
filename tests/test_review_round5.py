from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_toolchain import apply as apply_module
from agent_toolchain.adapters.claude import ClaudeAdapter
from agent_toolchain.apply import ApplyError, apply_plan
from agent_toolchain.manifests import load_catalog
from agent_toolchain.models import InstallPlan
from agent_toolchain.planner import build_plan
from agent_toolchain.resolver import resolve


def _catalog(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    root.mkdir()
    (root / "modules.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "modules": [
                    {
                        "id": "base",
                        "paths": ["skills/base"],
                        "targets": ["claude"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "components.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": [{"id": "base", "modules": ["base"]}],
            }
        ),
        encoding="utf-8",
    )
    (root / "profiles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [{"id": "base", "components": ["base"]}],
            }
        ),
        encoding="utf-8",
    )
    return root


def _staging(root: Path) -> Path:
    skill = root / "skills" / "base"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("base\n", encoding="utf-8")
    return root


def _fixture(tmp_path: Path) -> tuple[Path, Path, ClaudeAdapter, InstallPlan]:
    staging = _staging(tmp_path / "staging")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "harness"
    target.mkdir()

    catalog = load_catalog(_catalog(tmp_path))
    resolution = resolve(catalog, target="claude", profile="base")
    adapter = ClaudeAdapter(target)
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)
    return staging, outside, adapter, plan


def _leaked_state_files(outside: Path) -> list[str]:
    """Files under `outside` whose content is install-state JSON."""

    leaked: list[str] = []
    for path in sorted(outside.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8")
        if '"schema_version"' in text and '"target_root"' in text:
            leaked.append(str(path.relative_to(outside)))
    return leaked


def test_install_state_parent_is_materialized_before_write_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink created at the state parent just before the write must not take.

    apply_plan() asserted destination safety and then let write_state() create
    the parent chain with mkdir(parents=True), so at the instant of that assert
    the parent did not exist yet. A single symlink(2) on the still-free path
    therefore succeeded and mkdir(exist_ok=True) followed it, writing install
    state outside target_root. Materializing and re-validating the parent in
    apply_plan() leaves a real directory in place, so a create-only plant at
    that instant fails with EEXIST and the write stays inside the root.
    """

    staging, outside, adapter, plan = _fixture(tmp_path)
    state_path = adapter.install_state_path()
    original = apply_module.write_state
    plant_succeeded: list[bool] = []

    def plant_then_write(path: str | Path, state: object) -> None:
        parent = Path(path).parent
        try:
            os.symlink(outside, parent)
        except FileExistsError:
            plant_succeeded.append(False)
        else:
            plant_succeeded.append(True)
        original(path, state)  # type: ignore[arg-type]

    monkeypatch.setattr(apply_module, "write_state", plant_then_write)

    apply_plan(plan, source_root=staging, state_path=state_path)

    assert _leaked_state_files(outside) == []
    assert not state_path.is_symlink()
    assert state_path.is_file()
    assert plant_succeeded == [False]
    assert not (state_path.parent).is_symlink()


def test_state_parent_symlink_planted_during_commit_loop_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant guard, not an escape reproduction.

    A symlink planted at the state parent during the managed-file commit loop
    is already refused by the assert that precedes the state write; this test
    pins that behaviour so the reordering cannot regress it.
    """

    staging, outside, adapter, plan = _fixture(tmp_path)
    state_path = adapter.install_state_path()
    original = apply_module._copy_source_to_temp
    planted = False

    def plant_symlink_then_copy(source: Path, directory: Path) -> tuple[Path, str]:
        nonlocal planted
        if not planted:
            planted = True
            os.symlink(outside, state_path.parent)
        return original(source, directory)

    monkeypatch.setattr(apply_module, "_copy_source_to_temp", plant_symlink_then_copy)

    with pytest.raises(ApplyError, match="target path"):
        apply_plan(plan, source_root=staging, state_path=state_path)

    assert planted
    assert _leaked_state_files(outside) == []
    assert not state_path.is_file()
