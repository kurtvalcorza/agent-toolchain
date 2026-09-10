from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_toolchain import cli
from agent_toolchain.adapters.base import HarnessAdapter
from agent_toolchain.adapters.registry import get_adapter as real_get_adapter


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


def _install_arguments(catalog: Path, staging: Path, target_root: str) -> list[str]:
    return [
        "--catalog",
        str(catalog),
        "--source-root",
        str(staging),
        "--target",
        "claude",
        "--target-root",
        target_root,
        "--profile",
        "base",
    ]


def _spy_on_adapter_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> list[HarnessAdapter]:
    """Record every harness adapter the CLI constructs during one invocation."""

    built: list[HarnessAdapter] = []

    def spy(target: str, root: Any) -> HarnessAdapter:
        adapter = real_get_adapter(target, root)
        built.append(adapter)
        return adapter

    monkeypatch.setattr(cli, "get_adapter", spy)
    return built


def test_apply_constructs_the_harness_adapter_once_for_a_relative_target_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = _catalog(tmp_path)
    staging = _staging(tmp_path / "staging")
    monkeypatch.chdir(tmp_path)
    built = _spy_on_adapter_construction(monkeypatch)

    exit_code = cli.main(["apply", *_install_arguments(catalog, staging, "rel-harness")])

    assert exit_code == 0
    assert len(built) == 1, f"apply constructed {len(built)} adapters: {built}"


def test_apply_constructs_the_harness_adapter_once_for_a_tilde_target_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    catalog = _catalog(tmp_path)
    staging = _staging(tmp_path / "staging")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    built = _spy_on_adapter_construction(monkeypatch)

    exit_code = cli.main(["apply", *_install_arguments(catalog, staging, "~/harness")])

    assert exit_code == 0
    assert len(built) == 1, f"apply constructed {len(built)} adapters: {built}"
    assert built[0].root == home / "harness"


def test_apply_state_file_sits_under_the_plan_normalized_target_root_when_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = _catalog(tmp_path)
    staging = _staging(tmp_path / "staging")
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["apply", *_install_arguments(catalog, staging, "rel-harness")])

    assert exit_code == 0
    state_path = tmp_path / "rel-harness" / ".agent-toolchain" / "install-state.json"
    assert state_path.is_file()
    recorded_root = json.loads(state_path.read_text(encoding="utf-8"))["target_root"]
    assert Path(recorded_root).is_absolute()
    assert Path(recorded_root) / ".agent-toolchain" / "install-state.json" == state_path


def test_apply_state_file_sits_under_the_plan_normalized_target_root_when_tilde(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    catalog = _catalog(tmp_path)
    staging = _staging(tmp_path / "staging")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    exit_code = cli.main(["apply", *_install_arguments(catalog, staging, "~/harness")])

    assert exit_code == 0
    state_path = home / "harness" / ".agent-toolchain" / "install-state.json"
    assert state_path.is_file()
    recorded_root = json.loads(state_path.read_text(encoding="utf-8"))["target_root"]
    assert Path(recorded_root) / ".agent-toolchain" / "install-state.json" == state_path


def test_plan_command_still_reports_the_normalized_target_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = _catalog(tmp_path)
    staging = _staging(tmp_path / "staging")
    monkeypatch.chdir(tmp_path)
    built = _spy_on_adapter_construction(monkeypatch)

    exit_code = cli.main(
        ["plan", "--json", *_install_arguments(catalog, staging, "rel-harness")]
    )

    assert exit_code == 0
    assert len(built) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["target_root"] == str(tmp_path / "rel-harness")
