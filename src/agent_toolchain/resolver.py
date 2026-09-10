from __future__ import annotations

from .models import Catalog, Resolution


class ResolutionError(ValueError):
    pass


def resolve(
    catalog: Catalog,
    *,
    target: str,
    profile: str | None = None,
    include_components: tuple[str, ...] = (),
    exclude_modules: tuple[str, ...] = (),
) -> Resolution:
    component_ids: list[str] = []
    if profile is not None:
        selected_profile = catalog.profiles.get(profile)
        if selected_profile is None:
            raise ResolutionError(f"unknown profile: {profile}")
        component_ids.extend(selected_profile.components)
    component_ids.extend(include_components)
    component_ids = _dedupe(component_ids)

    for component_id in component_ids:
        if component_id not in catalog.components:
            raise ResolutionError(f"unknown component: {component_id}")

    excluded = set(exclude_modules)
    unknown_exclusions = excluded - catalog.modules.keys()
    if unknown_exclusions:
        raise ResolutionError(f"unknown excluded modules: {sorted(unknown_exclusions)}")

    selected: list[str] = []
    skipped: list[str] = []
    visiting: set[str] = set()
    resolved: set[str] = set()

    def add_module(module_id: str, *, required_by: str | None = None) -> None:
        if module_id in excluded:
            if required_by is not None:
                raise ResolutionError(
                    f"module {required_by} requires excluded dependency {module_id}"
                )
            return
        if module_id in resolved:
            return
        if module_id in visiting:
            raise ResolutionError(f"circular module dependency involving {module_id}")
        module = catalog.modules[module_id]
        if module.targets and target not in module.targets:
            skipped.append(module_id)
            return

        visiting.add(module_id)
        for dependency in module.dependencies:
            dependency_spec = catalog.modules[dependency]
            if dependency_spec.targets and target not in dependency_spec.targets:
                raise ResolutionError(
                    f"module {module_id} requires {dependency}, which does not support "
                    f"target {target}"
                )
            add_module(dependency, required_by=module_id)
        visiting.remove(module_id)
        resolved.add(module_id)
        selected.append(module_id)

    for component_id in component_ids:
        for module_id in catalog.components[component_id].modules:
            add_module(module_id)

    return Resolution(
        target=target,
        profile=profile,
        components=tuple(component_ids),
        modules=tuple(selected),
        skipped_modules=tuple(_dedupe(skipped)),
    )


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
