from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .models import InstallPlan, InstallState, ManagedFile, Operation
from .state import STATE_SCHEMA_VERSION, load_state, sha256_file, write_state


class ApplyError(RuntimeError):
    pass


@dataclass(frozen=True)
class _PreparedOperation:
    operation: Operation
    source: Path
    source_sha256: str
    destination: Path
    destination_existed: bool
    destination_sha256: str | None


def apply_plan(
    plan: InstallPlan,
    *,
    source_root: str | Path,
    state_path: str | Path,
) -> InstallState:
    source = _absolute(Path(source_root).expanduser())
    target_root = _absolute(Path(plan.target_root).expanduser())
    state_destination = _absolute(Path(state_path).expanduser())

    _assert_safe_destination(target_root, state_destination)
    previous = load_state(state_destination)
    previous_files = _previous_files(previous)
    prepared = _preflight_operations(
        plan,
        source_root=source,
        target_root=target_root,
        previous_files=previous_files,
    )

    planned_destinations = {str(item.destination) for item in prepared}
    orphaned = set(previous_files) - planned_destinations
    if orphaned:
        raise ApplyError(
            "plan would orphan previously managed files: " + ", ".join(sorted(orphaned))
        )

    backups: dict[Path, Path] = {}
    written: list[tuple[Path, str]] = []
    temporary_paths: set[Path] = set()
    managed: list[ManagedFile] = []

    try:
        for item in prepared:
            source_path = _safe_source_file(source, item.operation.source_relative_path)
            if sha256_file(source_path) != item.source_sha256:
                raise ApplyError(
                    f"staged source changed after planning: {item.operation.source_relative_path}"
                )

            destination = item.destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            _assert_safe_destination(target_root, destination)
            _revalidate_destination(item)

            temporary, digest = _copy_source_to_temp(source_path, destination.parent)
            temporary_paths.add(temporary)

            if item.destination_existed:
                backup = _copy_destination_to_backup(destination)
                backups[destination] = backup
                temporary_paths.add(backup)

            os.replace(temporary, destination)
            temporary_paths.discard(temporary)
            written.append((destination, digest))
            managed.append(
                ManagedFile(path=str(destination), sha256=digest, module_id=item.operation.module_id)
            )

        state = InstallState(
            schema_version=STATE_SCHEMA_VERSION,
            target=plan.target,
            target_root=str(target_root),
            profile=plan.profile,
            modules=plan.modules,
            files=tuple(managed),
        )
        _assert_safe_destination(target_root, state_destination)
        write_state(state_destination, state)
    except Exception as exc:
        _rollback(written, backups)
        if isinstance(exc, ApplyError):
            raise
        raise ApplyError(f"apply failed: {exc}") from exc
    finally:
        for temporary in temporary_paths:
            temporary.unlink(missing_ok=True)

    for backup in backups.values():
        backup.unlink(missing_ok=True)
    return state


def _preflight_operations(
    plan: InstallPlan,
    *,
    source_root: Path,
    target_root: Path,
    previous_files: dict[str, ManagedFile],
) -> tuple[_PreparedOperation, ...]:
    prepared: list[_PreparedOperation] = []
    for operation in plan.operations:
        if operation.kind != "copy_file":
            raise ApplyError(f"unsupported operation kind: {operation.kind}")

        source = _safe_source_file(source_root, operation.source_relative_path)
        destination = _absolute(Path(operation.destination_path).expanduser())
        _assert_safe_destination(target_root, destination)

        old = previous_files.get(str(destination))
        existed = destination.exists()
        current_hash: str | None = None
        if destination.is_symlink():
            raise ApplyError(f"refusing symlink destination: {destination}")
        if existed:
            if not destination.is_file():
                if old is not None:
                    raise ApplyError(f"managed path has local drift: {destination}")
                raise ApplyError(f"refusing to overwrite unmanaged path: {destination}")
            if old is None:
                raise ApplyError(f"refusing to overwrite unmanaged path: {destination}")
            current_hash = sha256_file(destination)
            if current_hash != old.sha256:
                raise ApplyError(f"managed path has local drift: {destination}")

        prepared.append(
            _PreparedOperation(
                operation=operation,
                source=source,
                source_sha256=sha256_file(source),
                destination=destination,
                destination_existed=existed,
                destination_sha256=current_hash,
            )
        )
    return tuple(prepared)


def _previous_files(previous: InstallState | None) -> dict[str, ManagedFile]:
    if previous is None:
        return {}
    result: dict[str, ManagedFile] = {}
    for item in previous.files:
        path = Path(item.path).expanduser()
        if not path.is_absolute():
            raise ApplyError(
                "existing install state contains relative managed paths; reinstall is required"
            )
        result[str(_absolute(path))] = item
    return result


def _safe_source_file(root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts:
        raise ApplyError(f"unsafe source path: {relative_text}")
    candidate = _absolute(root / relative)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"source path escapes staging root: {relative_text}") from exc
    _assert_no_symlink_components(root, candidate.parent)
    if candidate.is_symlink():
        raise ApplyError(f"refusing source symlink: {candidate}")
    if not candidate.exists() or not candidate.is_file():
        raise ApplyError(f"source is not a regular file: {candidate}")
    return candidate


def _revalidate_destination(item: _PreparedOperation) -> None:
    destination = item.destination
    if destination.is_symlink():
        raise ApplyError(f"refusing symlink destination: {destination}")
    if item.destination_existed:
        if not destination.exists() or not destination.is_file():
            raise ApplyError(f"managed path changed after preflight: {destination}")
        if sha256_file(destination) != item.destination_sha256:
            raise ApplyError(f"managed path changed after preflight: {destination}")
    elif destination.exists():
        raise ApplyError(f"destination appeared after preflight: {destination}")


def _copy_source_to_temp(source: Path, directory: Path) -> tuple[Path, str]:
    descriptor, raw_path = tempfile.mkstemp(prefix=".agent-toolchain-", suffix=".tmp", dir=directory)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
        return temporary, sha256_file(temporary)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _copy_destination_to_backup(destination: Path) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=".agent-toolchain-backup-", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    backup = Path(raw_path)
    try:
        shutil.copyfile(destination, backup)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _rollback(written: list[tuple[Path, str]], backups: dict[Path, Path]) -> None:
    for destination, written_hash in reversed(written):
        backup = backups.get(destination)
        if backup is not None:
            os.replace(backup, destination)
            continue
        if (
            destination.exists()
            and not destination.is_symlink()
            and destination.is_file()
            and sha256_file(destination) == written_hash
        ):
            destination.unlink()


def _assert_safe_destination(root: Path, destination: Path) -> None:
    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"destination escapes target root: {destination}") from exc
    _assert_no_symlink_components(root, destination.parent)
    if destination.is_symlink():
        raise ApplyError(f"refusing symlink destination: {destination}")


def _assert_no_symlink_components(root: Path, directory: Path) -> None:
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise ApplyError(f"directory escapes target root: {directory}") from exc
    current = root
    if current.is_symlink():
        raise ApplyError(f"target root is a symlink: {current}")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ApplyError(f"refusing to traverse symlink: {current}")


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))
