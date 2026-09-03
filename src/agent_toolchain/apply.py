from __future__ import annotations

import shutil
from pathlib import Path

from .models import InstallPlan, InstallState, ManagedFile
from .state import STATE_SCHEMA_VERSION, load_state, sha256_file, write_state


class ApplyError(RuntimeError):
    pass


def apply_plan(
    plan: InstallPlan,
    *,
    source_root: str | Path,
    state_path: str | Path,
) -> InstallState:
    source = Path(source_root)
    target_root = Path(plan.target_root).expanduser()
    state_destination = Path(state_path).expanduser()
    _assert_safe_destination(target_root, state_destination)
    previous = load_state(state_destination)
    previous_files = {item.path: item for item in previous.files} if previous else {}
    planned_destinations = {
        str(Path(item.destination_path).expanduser()) for item in plan.operations
    }
    orphaned = set(previous_files) - planned_destinations
    if orphaned:
        raise ApplyError(
            "plan would orphan previously managed files: " + ", ".join(sorted(orphaned))
        )
    managed: list[ManagedFile] = []

    for operation in plan.operations:
        if operation.kind != "copy_file":
            raise ApplyError(f"unsupported operation kind: {operation.kind}")
        source_path = source / operation.source_relative_path
        destination = Path(operation.destination_path).expanduser()
        _assert_safe_destination(target_root, destination)

        old = previous_files.get(str(destination))
        if destination.exists():
            if old is None:
                raise ApplyError(f"refusing to overwrite unmanaged path: {destination}")
            current_hash = sha256_file(destination)
            if current_hash != old.sha256:
                raise ApplyError(f"managed path has local drift: {destination}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_symlink_components(target_root, destination.parent)
        shutil.copyfile(source_path, destination)
        digest = sha256_file(destination)
        managed.append(
            ManagedFile(path=str(destination), sha256=digest, module_id=operation.module_id)
        )

    state = InstallState(
        schema_version=STATE_SCHEMA_VERSION,
        target=plan.target,
        target_root=str(target_root),
        profile=plan.profile,
        modules=plan.modules,
        files=tuple(managed),
    )
    _assert_no_symlink_components(target_root, state_destination.parent)
    write_state(state_destination, state)
    return state


def _assert_safe_destination(root: Path, destination: Path) -> None:
    root_resolved = root.resolve()
    try:
        destination.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise ApplyError(f"destination escapes target root: {destination}") from exc
    _assert_no_symlink_components(root, destination.parent)


def _assert_no_symlink_components(root: Path, directory: Path) -> None:
    root = root.expanduser()
    directory = directory.expanduser()
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"directory escapes target root: {directory}") from exc
    current = root
    if current.exists() and current.is_symlink():
        raise ApplyError(f"target root is a symlink: {current}")
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ApplyError(f"refusing to traverse symlink: {current}")
