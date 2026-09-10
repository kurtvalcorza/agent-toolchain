from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_toolchain.apply as apply_module
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


def _install(tmp_path: Path):
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)
    state = apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())
    return catalog, staging, target, adapter, plan, state


def _symlink_or_skip(path: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        path.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


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


def test_unknown_module_exclusion_fails_closed(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    with pytest.raises(ResolutionError, match="unknown excluded modules"):
        resolve(
            catalog,
            target="codex",
            profile="research",
            exclude_modules=("typo-module",),
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
    _, staging, target, adapter, plan, state = _install(tmp_path)
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
    catalog, staging, _, adapter, _, _ = _install(tmp_path)
    base_only = resolve(
        catalog,
        target="codex",
        include_components=("research",),
        exclude_modules=("research",),
    )
    base_plan = build_plan(catalog, base_only, source_root=staging, adapter=adapter)
    with pytest.raises(ApplyError, match="orphan previously managed"):
        apply_plan(base_plan, source_root=staging, state_path=adapter.install_state_path())


def test_apply_preflights_all_destinations_before_writing(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    unmanaged = target / "skills/research/SKILL.md"
    unmanaged.parent.mkdir(parents=True)
    unmanaged.write_text("local\n", encoding="utf-8")

    with pytest.raises(ApplyError, match="unmanaged path"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    assert not (target / "skills/base/SKILL.md").exists()
    assert unmanaged.read_text(encoding="utf-8") == "local\n"


def test_apply_rolls_back_when_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    original = apply_module._copy_source_to_temp
    calls = 0

    def fail_second_copy(source: Path, directory: Path) -> tuple[Path, str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated write failure")
        return original(source, directory)

    monkeypatch.setattr(apply_module, "_copy_source_to_temp", fail_second_copy)
    with pytest.raises(ApplyError, match="simulated write failure"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    assert not (target / "skills/base/SKILL.md").exists()
    assert not (target / "skills/research/SKILL.md").exists()
    assert not adapter.install_state_path().exists()


def test_apply_persists_absolute_paths_for_relative_target_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    monkeypatch.chdir(tmp_path)

    adapter = CodexAdapter(Path("relative-codex"))
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)
    state = apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    assert Path(state.target_root).is_absolute()
    assert all(Path(item.path).is_absolute() for item in state.files)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert all(item.status == "clean" for item in inspect_state(state))


def test_apply_rejects_destination_symlink(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    destination = target / "skills/base/SKILL.md"
    destination.parent.mkdir(parents=True)
    _symlink_or_skip(destination, outside)

    with pytest.raises(ApplyError, match="symlink destination"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())

    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_apply_revalidates_source_symlinks(tmp_path: Path) -> None:
    catalog = load_catalog(_catalog(tmp_path))
    staging = _staging(tmp_path)
    target = tmp_path / "codex"
    adapter = CodexAdapter(target)
    resolution = resolve(catalog, target="codex", profile="research")
    plan = build_plan(catalog, resolution, source_root=staging, adapter=adapter)

    outside = tmp_path / "outside-source.txt"
    outside.write_text("outside\n", encoding="utf-8")
    source = staging / "skills/base/SKILL.md"
    source.unlink()
    _symlink_or_skip(source, outside)

    with pytest.raises(ApplyError, match="source symlink"):
        apply_plan(plan, source_root=staging, state_path=adapter.install_state_path())


def test_doctor_classifies_non_file_as_drift(tmp_path: Path) -> None:
    _, _, target, _, _, state = _install(tmp_path)
    managed = target / "skills/research/SKILL.md"
    managed.unlink()
    managed.mkdir()

    findings = {item.path: item.status for item in inspect_state(state)}
    assert findings[managed] == "drifted"


def test_uninstall_preserves_dangling_symlink(tmp_path: Path) -> None:
    _, _, target, _, _, state = _install(tmp_path)
    managed = target / "skills/research/SKILL.md"
    managed.unlink()
    _symlink_or_skip(managed, target / "missing-target")

    preserved = uninstall_managed(state)
    assert preserved == (managed,)
    assert managed.is_symlink()


def test_uninstall_preserves_path_beneath_symlinked_parent(tmp_path: Path) -> None:
    _, _, target, _, _, state = _install(tmp_path)
    managed = target / "skills/research/SKILL.md"
    managed.unlink()
    managed.parent.rmdir()

    outside = tmp_path / "outside-research"
    outside.mkdir()
    outside_file = outside / "SKILL.md"
    outside_file.write_text("research\n", encoding="utf-8")
    _symlink_or_skip(managed.parent, outside, target_is_directory=True)

    preserved = uninstall_managed(state)
    assert preserved == (managed,)
    assert outside_file.read_text(encoding="utf-8") == "research\n"


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
