from __future__ import annotations

from pathlib import Path

from ._paths import absolute_state_path, has_symlink_component, is_under_root
from .models import InstallState
from .state import sha256_file


def uninstall_managed(state: InstallState) -> tuple[Path, ...]:
    preserved: list[Path] = []
    root = absolute_state_path(Path(state.target_root).expanduser())

    for managed in state.files:
        raw_path = Path(managed.path).expanduser()
        path = absolute_state_path(raw_path)
        if root is None or path is None or not is_under_root(root, path):
            preserved.append(raw_path)
            continue
        if has_symlink_component(root, path.parent) or path.is_symlink():
            preserved.append(path)
            continue
        if not path.exists():
            continue
        if not path.is_file() or sha256_file(path) != managed.sha256:
            preserved.append(path)
            continue
        path.unlink()
    return tuple(preserved)
