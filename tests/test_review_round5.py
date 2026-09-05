from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from agent_toolchain import apply as apply_module
from agent_toolchain import state as state_module
from agent_toolchain.adapters.claude import ClaudeAdapter
from agent_toolchain.apply import ApplyError, apply_plan
from agent_toolchain.manifests import load_catalog
from agent_toolchain.models import InstallPlan, InstallState
from agent_toolchain.planner import build_plan
from agent_toolchain.resolver import resolve
from agent_toolchain.state import StateError, write_state


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


def test_state_write_does_not_follow_a_planted_temp_symlink(tmp_path: Path) -> None:
    """A symlink pre-planted at the state temp path must not capture the write.

    write_state() staged the payload at the caller-derivable sibling path
    '.<name>.tmp' with write_text(), which follows symlinks. Pre-planting that
    path as a symlink to an out-of-root file therefore captured the whole
    install state outside target_root and left the in-root state path as a
    symlink after os.replace renamed the link into place - no race window
    needed. Staging through tempfile.mkstemp(dir=...) uses O_EXCL, so the write
    cannot land on any pre-existing path.
    """

    staging, outside, adapter, plan = _fixture(tmp_path)
    state_path = adapter.install_state_path()
    state_path.parent.mkdir(parents=True)
    legacy_temp = state_path.with_name(f".{state_path.name}.tmp")
    os.symlink(outside / "captured.json", legacy_temp)

    apply_plan(plan, source_root=staging, state_path=state_path)

    assert _leaked_state_files(outside) == []
    assert not (outside / "captured.json").exists()
    assert state_path.is_file()
    assert not state_path.is_symlink()
    # The planted symlink is simply bypassed, not followed and not consumed.
    assert legacy_temp.is_symlink()
    # mkstemp creates 0600; managed files written by apply.py already land 0600.
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


def test_state_write_leaves_no_temporary_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cleanup is pinned by directory contents, not by a predictable name.

    tests/test_copilot_regressions.py::test_write_state_cleans_temporary_file_
    when_replace_fails asserts a fixed '.<name>.tmp' path is absent, which the
    randomized mkstemp name makes vacuous. This asserts the property that test
    intended: after a failed os.replace no staged file survives anywhere in the
    state directory.
    """

    state = InstallState(
        schema_version=1,
        target="claude",
        target_root=str(tmp_path / "harness"),
        profile=None,
        modules=(),
        files=(),
        metadata={},
    )
    state_path = tmp_path / "harness" / ".agent-toolchain" / "install-state.json"

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        raise OSError(f"cannot replace {source} -> {destination}")

    monkeypatch.setattr(state_module.os, "replace", fail_replace)

    with pytest.raises(StateError, match="cannot write install state"):
        write_state(state_path, state)

    assert not state_path.exists()
    assert list(state_path.parent.iterdir()) == []
