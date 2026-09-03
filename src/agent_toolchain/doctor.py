from __future__ import annotations

from pathlib import Path

from .models import DoctorFinding, InstallState
from .state import sha256_file


def inspect_state(state: InstallState) -> tuple[DoctorFinding, ...]:
    findings: list[DoctorFinding] = []
    for managed in state.files:
        path = Path(managed.path)
        if not path.exists():
            findings.append(DoctorFinding(path, "missing", managed.sha256, None))
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
