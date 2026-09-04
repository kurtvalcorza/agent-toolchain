from __future__ import annotations

import os
from pathlib import Path


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without resolving symlinks."""

    return Path(os.path.abspath(path))


def absolute_state_path(path: Path) -> Path | None:
    """Normalize an already-absolute state path, rejecting legacy relative paths."""

    if not path.is_absolute():
        return None
    return lexical_absolute(path)


def is_under_root(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def has_symlink_component(root: Path, directory: Path) -> bool:
    """Return whether root/directory containment crosses a symlink component."""

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
