from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_toolchain.adapters.codex import CodexAdapter
from agent_toolchain.apply import ApplyError, apply_plan
from agent_toolchain.manifests import load_catalog
from agent_toolchain.planner import PlanningError, build_plan
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
                        "targets": ["codex"],
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


def _staging(tmp_path: Path) -> Path:
    root = tmp_path / "staging"
    (root / "skills/base").mkdir(parents=True)
    (root / "skills/base/SKILL.md").write_text("base\n", encoding="utf-8")
    return root


def _symlink_or_skip(path: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        path.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


def test_apply_rejects_target_root_beneath_symlinked_ancestor(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)

    real_parent = tmp_path / "real-harness"
    real_parent.mkdir()
    alias = tmp_path / "harness-alias"
    _symlink_or_skip(alias, real_parent, target_is_directory=True)

    adapter = CodexAdapter(alias / "codex")
    resolution = resolve(catalog, target="codex", profile="base")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    with pytest.raises(ApplyError, match="symlink"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    assert not (real_parent / "codex").exists()


def test_planner_refuses_symlink_directory_without_traversal(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SECRET.md").write_text("outside\n", encoding="utf-8")
    _symlink_or_skip(
        staging / "skills/base/external",
        outside,
        target_is_directory=True,
    )

    resolution = resolve(catalog, target="codex", profile="base")
    with pytest.raises(PlanningError, match="source symlink"):
        build_plan(
            catalog,
            resolution,
            source_root=staging,
            adapter=CodexAdapter(tmp_path / "codex"),
        )
