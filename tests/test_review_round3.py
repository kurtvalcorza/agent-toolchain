from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

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
