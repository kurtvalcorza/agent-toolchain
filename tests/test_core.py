from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_toolchain.adapters.codex import CodexAdapter
from agent_toolchain.apply import ApplyError, apply_plan
from agent_toolchain.doctor import inspect_state
from agent_toolchain.manifests import load_catalog
from agent_toolchain.planner import PlanningError, build_plan
from agent_toolchain.resolver import ResolutionError, resolve
from agent_toolchain.state import load_state
from agent_toolchain.uninstall import uninstall_managed


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
                        "targets": ["codex", "claude"],
                    },
                    {
                        "id": "research",
                        "paths": ["skills/research"],
                        "targets": ["codex", "claude"],
                        "dependencies": ["base"],
                    },
                    {
                        "id": "claude-hooks",
                        "paths": ["hooks/stop.py"],
                        "targets": ["claude"],
                        "executable": True,
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
                "components": [
                    {"id": "research", "modules": ["research"]},
                    {"id": "hooks", "modules": ["claude-hooks"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "profiles.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profiles": [{"id": "research", "components": ["research"]}],
            }
        ),
        encoding="utf-8",
    )
    return root


def _staging(tmp_path: Path) -> Path:
    root = tmp_path / "staging"
    (root / "skills/base").mkdir(parents=True)
    (root / "skills/research").mkdir(parents=True)
    (root / "hooks").mkdir()
    (root / "skills/base/SKILL.md").write_text("base\n", encoding="utf-8")
    (root / "skills/research/SKILL.md").write_text("research\n", encoding="utf-8")
    (root / "hooks/stop.py").write_text("print('stop')\n", encoding="utf-8")
    return root


def test_resolution_orders_dependencies_and_skips_incompatible_module(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    resolution = resolve(
        catalog,
        target="codex",
        profile="research",
        include_components=("hooks",),
    )
    assert resolution.modules == ("base", "research")
    assert resolution.skipped_modules == ("claude-hooks",)


def test_excluding_required_dependency_fails_closed(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    with pytest.raises(ResolutionError, match="requires excluded dependency"):
        resolve(
            catalog,
            target="codex",
            profile="research",
            exclude_modules=("base",),
        )


def test_plan_maps_canonical_skills_into_codex_root(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    resolution = resolve(catalog, target="codex", profile="research")
    target = tmp_path / "codex"
    plan = build_plan(
        catalog,
        resolution,
        source_root=_staging(tmp_path),
        adapter=CodexAdapter(target),
    )
    assert [item.destination_path for item in plan.operations] == [
        str(target / "skills/base/SKILL.md"),
        str(target / "skills/research/SKILL.md"),
    ]


def test_apply_detects_drift_and_uninstall_preserves_modified_files(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    state = apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())
    assert all(item.status == "clean" for item in inspect_state(state))

    modified = target / "skills/research/SKILL.md"
    modified.write_text("local edit\n", encoding="utf-8")
    assert {item.status for item in inspect_state(state)} == {"clean", "drifted"}

    with pytest.raises(ApplyError, match="local drift"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    preserved = uninstall_managed(state)
    assert preserved == (modified,)
    assert modified.exists()
    assert not (target / "skills/base/SKILL.md").exists()

    reloaded = load_state(adapter.install_state_path())
    assert reloaded is not None
    assert reloaded.modules == ("base", "research")


def test_apply_refuses_to_orphan_previously_managed_files(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    full = resolve(catalog, target="codex", profile="research")
    full_plan = build_plan(catalog, full, source_root=staging, adapter=adapter)
    apply_plan(full_plan, source_root=staging, state_path=adapter.install_state_path())

    base_only = resolve(
        catalog,
        target="codex",
        include_components=("research",),
        exclude_modules=("research",),
    )
    base_plan = build_plan(catalog, base_only, source_root=staging, adapter=adapter)
    with pytest.raises(ApplyError, match="orphan previously managed"):
        apply_plan(base_plan, source_root=staging, state_path=adapter.install_state_path())


def test_executable_module_requires_explicit_hook_consent(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    resolution = resolve(catalog, target="claude", include_components=("hooks",))
    from agent_toolchain.adapters.claude import ClaudeAdapter

    with pytest.raises(PlanningError, match="explicit hook consent"):
        build_plan(
            catalog,
            resolution,
            source_root=staging,
            adapter=ClaudeAdapter(tmp_path / "claude"),
        )
