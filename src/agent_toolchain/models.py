from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    paths: tuple[str, ...]
    targets: frozenset[str]
    dependencies: tuple[str, ...] = ()
    executable: bool = False


@dataclass(frozen=True)
class ComponentSpec:
    id: str
    modules: tuple[str, ...]


@dataclass(frozen=True)
class ProfileSpec:
    id: str
    components: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    schema_version: int
    modules: dict[str, ModuleSpec]
    components: dict[str, ComponentSpec]
    profiles: dict[str, ProfileSpec]


@dataclass(frozen=True)
class Resolution:
    target: str
    profile: str | None
    components: tuple[str, ...]
    modules: tuple[str, ...]
    skipped_modules: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    kind: str
    module_id: str
    source_relative_path: str
    destination_path: str
    ownership: str = "managed"
    executable: bool = False


@dataclass(frozen=True)
class InstallPlan:
    target: str
    profile: str | None
    components: tuple[str, ...]
    modules: tuple[str, ...]
    operations: tuple[Operation, ...]
    target_root: str
    skipped_modules: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManagedFile:
    path: str
    sha256: str
    module_id: str


@dataclass(frozen=True)
class InstallState:
    schema_version: int
    target: str
    target_root: str
    profile: str | None
    modules: tuple[str, ...]
    files: tuple[ManagedFile, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DoctorFinding:
    path: Path
    status: str
    expected_sha256: str
    actual_sha256: str | None
