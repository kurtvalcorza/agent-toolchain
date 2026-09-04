from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .models import InstallState, ManagedFile

STATE_SCHEMA_VERSION = 1


class StateError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_string(raw: dict[str, Any], key: str, state_path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise StateError(f"invalid install state {state_path}: {key} must be a string")
    return value


def _string_tuple(value: Any, field: str, state_path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise StateError(f"invalid install state {state_path}: {field} must be a string list")
    return tuple(value)


def _managed_files(value: Any, state_path: Path) -> tuple[ManagedFile, ...]:
    if not isinstance(value, list):
        raise StateError(f"invalid install state {state_path}: files must be a list")

    files: list[ManagedFile] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise StateError(
                f"invalid install state {state_path}: files[{index}] must be an object"
            )
        files.append(
            ManagedFile(
                path=_required_string(item, "path", state_path),
                sha256=_required_string(item, "sha256", state_path),
                module_id=_required_string(item, "module_id", state_path),
            )
        )
    return tuple(files)


def _metadata(value: Any, state_path: Path) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise StateError(
            f"invalid install state {state_path}: "
            "metadata must map strings to strings"
        )
    return dict(value)


def load_state(path: str | Path) -> InstallState | None:
    state_path = Path(path)
    if not state_path.exists():
        return None
    try:
        raw: Any = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot load install state {state_path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != STATE_SCHEMA_VERSION:
        raise StateError(f"unsupported install state: {state_path}")

    profile = raw.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise StateError(f"invalid install state {state_path}: profile must be a string or null")

    return InstallState(
        schema_version=STATE_SCHEMA_VERSION,
        target=_required_string(raw, "target", state_path),
        target_root=_required_string(raw, "target_root", state_path),
        profile=profile,
        modules=_string_tuple(raw.get("modules", []), "modules", state_path),
        files=_managed_files(raw.get("files", []), state_path),
        metadata=_metadata(raw.get("metadata", {}), state_path),
    )


def write_state(path: str | Path, state: InstallState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": state.schema_version,
        "target": state.target,
        "target_root": state.target_root,
        "profile": state.profile,
        "modules": list(state.modules),
        "files": [
            {"path": item.path, "sha256": item.sha256, "module_id": item.module_id}
            for item in state.files
        ],
        "metadata": state.metadata,
    }
    temporary = state_path.with_name(f".{state_path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, state_path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise StateError(f"cannot write install state {state_path}: {exc}") from exc
