from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Catalog, ComponentSpec, ModuleSpec, ProfileSpec

SCHEMA_VERSION = 1


class ManifestError(ValueError):
    pass


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot load manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"manifest {path} must contain a JSON object")
    return value


def _require_version(document: dict[str, Any], path: Path) -> None:
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(
            f"{path} uses unsupported schema_version={document.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}"
        )


def load_catalog(directory: str | Path) -> Catalog:
    root = Path(directory)
    module_doc = _read_object(root / "modules.json")
    component_doc = _read_object(root / "components.json")
    profile_doc = _read_object(root / "profiles.json")
    for document, path in (
        (module_doc, root / "modules.json"),
        (component_doc, root / "components.json"),
        (profile_doc, root / "profiles.json"),
    ):
        _require_version(document, path)

    modules: dict[str, ModuleSpec] = {}
    for raw in module_doc.get("modules", []):
        if not isinstance(raw, dict):
            raise ManifestError("module entries must be objects")
        module_id = _required_text(raw, "id", "module")
        if module_id in modules:
            raise ManifestError(f"duplicate module id: {module_id}")
        modules[module_id] = ModuleSpec(
            id=module_id,
            paths=_text_tuple(raw.get("paths", ()), f"module {module_id} paths"),
            targets=frozenset(_text_tuple(raw.get("targets", ()), f"module {module_id} targets")),
            dependencies=_text_tuple(
                raw.get("dependencies", ()), f"module {module_id} dependencies"
            ),
            executable=bool(raw.get("executable", False)),
        )

    components: dict[str, ComponentSpec] = {}
    for raw in component_doc.get("components", []):
        if not isinstance(raw, dict):
            raise ManifestError("component entries must be objects")
        component_id = _required_text(raw, "id", "component")
        if component_id in components:
            raise ManifestError(f"duplicate component id: {component_id}")
        components[component_id] = ComponentSpec(
            id=component_id,
            modules=_text_tuple(raw.get("modules", ()), f"component {component_id} modules"),
        )

    profiles: dict[str, ProfileSpec] = {}
    for raw in profile_doc.get("profiles", []):
        if not isinstance(raw, dict):
            raise ManifestError("profile entries must be objects")
        profile_id = _required_text(raw, "id", "profile")
        if profile_id in profiles:
            raise ManifestError(f"duplicate profile id: {profile_id}")
        profiles[profile_id] = ProfileSpec(
            id=profile_id,
            components=_text_tuple(
                raw.get("components", ()), f"profile {profile_id} components"
            ),
        )

    _validate_references(modules, components, profiles)
    return Catalog(SCHEMA_VERSION, modules, components, profiles)


def _required_text(value: dict[str, Any], key: str, kind: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ManifestError(f"{kind} {key} must be a non-empty string")
    return item


def _text_tuple(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ManifestError(f"{label} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ManifestError(f"{label} must contain only non-empty strings")
    return tuple(value)


def _validate_references(
    modules: dict[str, ModuleSpec],
    components: dict[str, ComponentSpec],
    profiles: dict[str, ProfileSpec],
) -> None:
    for module in modules.values():
        unknown = set(module.dependencies) - modules.keys()
        if unknown:
            raise ManifestError(
                f"module {module.id} references unknown dependencies: {sorted(unknown)}"
            )
    for component in components.values():
        unknown = set(component.modules) - modules.keys()
        if unknown:
            raise ManifestError(
                f"component {component.id} references unknown modules: {sorted(unknown)}"
            )
    for profile in profiles.values():
        unknown = set(profile.components) - components.keys()
        if unknown:
            raise ManifestError(
                f"profile {profile.id} references unknown components: {sorted(unknown)}"
            )
