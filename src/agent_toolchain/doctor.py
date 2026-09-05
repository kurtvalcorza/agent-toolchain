from __future__ import annotations

from pathlib import Path

from ._paths import absolute_state_path, has_symlink_component, is_under_root
from .models import DoctorFinding, InstallState
from .state import sha256_file


def inspect_state(state: InstallState) -> tuple[DoctorFinding, ...]:
    findings: list[DoctorFinding] = []
    root = absolute_state_path(Path(state.target_root).expanduser())

    for managed in state.files:
        raw_path = Path(managed.path).expanduser()
        path = absolute_state_path(raw_path)
        if root is None or path is None or not is_under_root(root, path):
            findings.append(DoctorFinding(raw_path, "drifted", managed.sha256, None))
            continue
        if has_symlink_component(root, path.parent) or path.is_symlink():
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
