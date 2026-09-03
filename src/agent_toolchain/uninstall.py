from __future__ import annotations

from pathlib import Path

from .models import InstallState
from .state import sha256_file


def uninstall_managed(state: InstallState) -> tuple[Path, ...]:
    preserved: list[Path] = []
    for managed in state.files:
        path = Path(managed.path)
        if not path.exists():
            continue
        if path.is_symlink() or sha256_file(path) != managed.sha256:
            preserved.append(path)
            continue
        path.unlink()
    return tuple(preserved)
