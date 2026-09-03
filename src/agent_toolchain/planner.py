from __future__ import annotations

from pathlib import Path

from .adapters.base import HarnessAdapter
from .models import Catalog, InstallPlan, Operation, Resolution


class PlanningError(ValueError):
    pass


def build_plan(
    catalog: Catalog,
    resolution: Resolution,
    *,
    source_root: str | Path,
    adapter: HarnessAdapter,
    hooks_enabled: bool = False,
) -> InstallPlan:
    root = Path(source_root)
    operations: list[Operation] = []
    warnings: list[str] = []
    destinations: dict[str, str] = {}

    for module_id in resolution.modules:
        module = catalog.modules[module_id]
        if module.executable and not hooks_enabled:
            raise PlanningError(
                f"executable module {module_id} requires explicit hook consent"
            )
        for declared_path in module.paths:
            source = _safe_source(root, declared_path)
            if not source.exists():
                raise PlanningError(f"declared path does not exist: {declared_path}")
            if source.is_symlink():
                raise PlanningError(f"declared path is a symlink: {declared_path}")
            files = (
                [source]
                if source.is_file()
                else sorted(path for path in source.rglob("*") if path.is_file())
            )
            for file_path in files:
                _assert_safe_source_file(root, file_path)
                relative = file_path.relative_to(root).as_posix()
                destination = adapter.destination_for(relative)
                destination_text = str(destination)
                previous = destinations.get(destination_text)
                if previous is not None:
                    raise PlanningError(
                        f"destination collision: {relative} and {previous} -> {destination_text}"
                    )
                destinations[destination_text] = relative
                operations.append(
                    Operation(
                        kind="copy_file",
                        module_id=module_id,
                        source_relative_path=relative,
                        destination_path=destination_text,
                        executable=module.executable,
                    )
                )

    operations.sort(key=lambda item: item.destination_path)
    return InstallPlan(
        target=resolution.target,
        profile=resolution.profile,
        components=resolution.components,
        modules=resolution.modules,
        operations=tuple(operations),
        target_root=str(adapter.root),
        skipped_modules=resolution.skipped_modules,
        warnings=tuple(warnings),
    )


def _safe_source(root: Path, declared_path: str) -> Path:
    relative = Path(declared_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise PlanningError(f"unsafe declared path: {declared_path}")
    candidate = root / relative
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PlanningError(f"declared path escapes source root: {declared_path}") from exc
    return candidate


def _assert_safe_source_file(root: Path, path: Path) -> None:
    if path.is_symlink():
        raise PlanningError(f"refusing to follow source symlink: {path}")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PlanningError(f"source file escapes staging root: {path}") from exc
