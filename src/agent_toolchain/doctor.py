from __future__ import annotations

import os
from pathlib import Path

from .models import DoctorFinding, InstallState
from .state import sha256_file


def inspect_state(state: InstallState) -> tuple[DoctorFinding, ...]:
    findings: list[DoctorFinding] = []
    root = _absolute_state_path(Path(state.target_root).expanduser())

    for managed in state.files:
        raw_path = Path(managed.path).expanduser()
        path = _absolute_state_path(raw_path)
        if root is None or path is None or not _is_under_root(root, path):
            findings.append(DoctorFinding(raw_path, "drifted", managed.sha256, None))
            continue
        if _has_symlink_component(root, path.parent) or path.is_symlink():
            findings.append(DoctorFinding(path, "drifted", managed.sha256, None))
            continue
        if not path.exists():
            findings.append(DoctorFinding(path, "missing", managed.sha256, None))
            continue
        if not path.is_file():
            findings.append(DoctorFinding(path, "drifted", managed.sha256, None))
            continue

        actual = sha256_file(path)
        findings.append(
            DoctorFinding(
                path,
                "clean" if actual == managed.sha256 else "drifted",
                managed.sha256,
                actual,
            )
        )
    return tuple(findings)


def _absolute_state_path(path: Path) -> Path | None:
    if not path.is_absolute():
        return None
    return Path(os.path.abspath(path))


def _is_under_root(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_symlink_component(root: Path, directory: Path) -> bool:
    try:
        relative = directory.relative_to(root)
    except ValueError:
        return True
    current = root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False
