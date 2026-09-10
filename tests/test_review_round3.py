from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_toolchain import apply as apply_module
from agent_toolchain.adapters.claude import ClaudeAdapter
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


def test_build_plan_expands_user_source_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    _staging(home / "staging")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    catalog = load_catalog(_catalog(tmp_path))
    resolution = resolve(catalog, target="claude", profile="base")
    adapter = ClaudeAdapter("~/harness")

    plan = build_plan(catalog, resolution, source_root="~/staging", adapter=adapter)

    assert [operation.source_relative_path for operation in plan.operations] == [
        "skills/base/SKILL.md"
    ]
    assert plan.target_root == str(home / "harness")


def test_build_plan_names_missing_source_root(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    resolution = resolve(catalog, target="claude", profile="base")
    missing = tmp_path / "absent-staging"

    with pytest.raises(PlanningError) as error:
        build_plan(
            catalog,
            resolution,
            source_root=missing,
            adapter=ClaudeAdapter(tmp_path / "harness"),
        )

    message = str(error.value)
    assert str(missing) in message
    assert "source root" in message


def test_source_symlink_refusal_names_source_path(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    os.symlink(real, link)
    _staging(link / "staging")

    catalog = load_catalog(_catalog(tmp_path))
    resolution = resolve(catalog, target="claude", profile="base")
    adapter = ClaudeAdapter(tmp_path / "harness")
    plan = build_plan(catalog, resolution, source_root=link / "staging", adapter=adapter)

    with pytest.raises(ApplyError) as error:
        apply_plan(
            plan,
            source_root=link / "staging",
            state_path=adapter.install_state_path(),
        )

    message = str(error.value)
    assert "source path" in message
    assert "target path" not in message


def _nested_catalog(tmp_path: Path) -> Path:
    root = tmp_path / "catalog-nested"
    root.mkdir()
    (root / "modules.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "modules": [
                    {"id": "base", "paths": ["skills/base"], "targets": ["claude"]},
                    {
                        "id": "deep",
                        "paths": ["skills/deep/nested"],
                        "targets": ["claude"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "components.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": [{"id": "both", "modules": ["base", "deep"]}],
            }
        ),
        encoding="utf-8",
    )
    (root / "profiles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [{"id": "both", "components": ["both"]}],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_apply_does_not_create_directories_through_a_planted_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symlink planted between preflight and commit must be refused before mkdir.

    mkdir(parents=True) follows symlinks, so creating destination parents before
    revalidating the destination let a symlink introduced after preflight
    materialize directories outside the target root.
    """
    staging = _staging(tmp_path / "staging")
    nested = staging / "skills" / "deep" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("deep\n", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "harness"

    catalog = load_catalog(_nested_catalog(tmp_path))
    resolution = resolve(catalog, target="claude", profile="both")
    adapter = ClaudeAdapter(target)
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    original = apply_module._copy_source_to_temp
    planted = False

    def plant_symlink_then_copy(source: Path, directory: Path) -> tuple[Path, str]:
        nonlocal planted
        if not planted:
            planted = True
            os.symlink(outside, target / "skills" / "deep")
        return original(source, directory)

    monkeypatch.setattr(apply_module, "_copy_source_to_temp", plant_symlink_then_copy)

    with pytest.raises(ApplyError, match="target path"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    assert planted
    assert not (outside / "nested").exists()
    assert list(outside.iterdir()) == []
    assert not adapter.install_state_path().exists()
