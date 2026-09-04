from __future__ import annotations

import os
from pathlib import Path

from .models import InstallState
from .state import sha256_file


def uninstall_managed(state: InstallState) -> tuple[Path, ...]:
    preserved: list[Path] = []
    root = _absolute_state_path(Path(state.target_root).expanduser())

    for managed in state.files:
        raw_path = Path(managed.path).expanduser()
        path = _absolute_state_path(raw_path)
        if root is None or path is None or not _is_under_root(root, path):
            preserved.append(raw_path)
            continue
        if _has_symlink_component(root, path.parent) or path.is_symlink():
            preserved.append(path)
            continue
        if not path.exists():
            continue
        if not path.is_file() or sha256_file(path) != managed.sha256:
            preserved.append(path)
            continue
        path.unlink()
    return tuple(preserved)


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
