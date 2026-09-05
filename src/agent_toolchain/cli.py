from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .adapters.base import HarnessAdapter
from .adapters.registry import get_adapter
from .apply import apply_plan
from .doctor import inspect_state
from .manifests import load_catalog
from .models import InstallPlan
from .planner import build_plan
from .resolver import resolve
from .state import load_state
from .uninstall import uninstall_managed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-toolchain")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="resolve components and print an immutable install plan")
    _install_arguments(plan)
    plan.add_argument("--json", action="store_true")

    apply = sub.add_parser("apply", help="apply a previously resolvable installation safely")
    _install_arguments(apply)

    status = sub.add_parser("status", help="summarize managed installation state")
    status.add_argument("--state", required=True)

    doctor = sub.add_parser("doctor", help="inspect managed files for drift")
    doctor.add_argument("--state", required=True)

    uninstall = sub.add_parser("uninstall", help="remove only unmodified managed files")
    uninstall.add_argument("--state", required=True)

    return parser


def _install_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--target", choices=("codex", "claude"), required=True)
    parser.add_argument("--target-root", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--with-component", action="append", default=[])
    parser.add_argument("--exclude-module", action="append", default=[])
    parser.add_argument("--enable-hooks", action="store_true")


def _make_plan(args: argparse.Namespace) -> tuple[InstallPlan, HarnessAdapter]:
    """Build the plan and return it with the single adapter it was planned against.

    The adapter is returned rather than rebuilt by callers so that the plan and
    any adapter-derived path (notably the install-state location) can never be
    computed from two independent constructions. ``adapter.root`` is the
    normalized absolute root that ``plan.target_root`` records.
    """

    catalog = load_catalog(args.catalog)
    resolution = resolve(
        catalog,
        target=args.target,
        profile=args.profile,
        include_components=tuple(args.with_component),
        exclude_modules=tuple(args.exclude_module),
    )
    adapter = get_adapter(args.target, args.target_root)
    plan = build_plan(
        catalog,
        resolution,
        source_root=args.source_root,
        adapter=adapter,
        hooks_enabled=args.enable_hooks,
    )
    return plan, adapter


def _plan_payload(plan: InstallPlan) -> dict[str, object]:
    return {
        "target": plan.target,
        "profile": plan.profile,
        "components": list(plan.components),
        "modules": list(plan.modules),
        "skipped_modules": list(plan.skipped_modules),
        "warnings": list(plan.warnings),
        "target_root": plan.target_root,
        "operations": [
            {
                "kind": operation.kind,
                "module_id": operation.module_id,
                "source": operation.source_relative_path,
                "destination": operation.destination_path,
                "ownership": operation.ownership,
                "executable": operation.executable,
            }
            for operation in plan.operations
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "plan":
        plan, _ = _make_plan(args)
        payload = _plan_payload(plan)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"target: {plan.target}")
            print(f"modules: {', '.join(plan.modules) or '(none)'}")
            for operation in plan.operations:
                print(f"COPY {operation.source_relative_path} -> {operation.destination_path}")
            for warning in plan.warnings:
                print(f"WARN {warning}")
        return 0

    if args.command == "apply":
        plan, adapter = _make_plan(args)
        installed_state = apply_plan(
            plan,
            source_root=args.source_root,
            state_path=adapter.install_state_path(),
        )
        print(f"installed {len(installed_state.files)} managed file(s)")
        return 0

    current_state = load_state(Path(args.state))
    if current_state is None:
        raise SystemExit(f"install state not found: {args.state}")

    if args.command == "status":
        print(f"target: {current_state.target}")
        print(f"profile: {current_state.profile or '(none)'}")
        print(f"modules: {', '.join(current_state.modules) or '(none)'}")
        print(f"managed files: {len(current_state.files)}")
        return 0

    if args.command == "doctor":
        findings = inspect_state(current_state)
        for finding in findings:
            print(f"{finding.status.upper():8} {finding.path}")
        return 1 if any(item.status != "clean" for item in findings) else 0

    if args.command == "uninstall":
        preserved = uninstall_managed(current_state)
        if preserved:
            for path in preserved:
                print(f"PRESERVE {path}")
            return 1
        Path(args.state).unlink(missing_ok=True)
        print("removed all unmodified managed files")
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
