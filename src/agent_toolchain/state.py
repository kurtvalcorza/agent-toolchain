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
    files = tuple(
        ManagedFile(path=item["path"], sha256=item["sha256"], module_id=item["module_id"])
        for item in raw.get("files", [])
    )
    return InstallState(
        schema_version=STATE_SCHEMA_VERSION,
        target=raw["target"],
        target_root=raw["target_root"],
        profile=raw.get("profile"),
        modules=tuple(raw.get("modules", [])),
        files=files,
        metadata=dict(raw.get("metadata", {})),
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
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, state_path)
