# agent-toolchain

Host-neutral distribution and integration tooling for portable AI-agent capabilities.

`agent-toolchain` is the distribution and harness-adaptation plane for independently usable agent capabilities. Component repositories remain authoritative for behavior; this project owns packaging, target adaptation, installation planning, managed state, and integrity checks.

## v0.1 scope

The initial core provides:

- versioned module, component, and profile manifests;
- dependency and target-compatibility resolution;
- Codex and Claude harness adapters;
- deterministic copy-file planning from a canonical staging tree;
- explicit consent for executable/hook modules;
- transactional apply with full preflight validation and rollback on commit failure;
- source and destination path/symlink safety checks at apply time;
- canonical absolute managed paths in SHA-256 install state;
- refusal to overwrite unmanaged paths, locally drifted files, or unsafe filesystem objects;
- refusal to silently orphan previously managed files;
- drift inspection with conservative handling of symlinks and non-regular files;
- conservative uninstall that preserves modified, symlinked, or otherwise unsafe managed paths;
- `plan`, `apply`, `status`, `doctor`, and `uninstall` CLI primitives;
- Python 3.12/3.13 CI with Ruff, Mypy, and Pytest.

## Architectural boundary

The toolchain deliberately does **not** own component semantics. A component such as `agent-relay` or `agentic-research` remains independently usable and authoritative for its own routing, methodology, prompts, skills, and behavior.

The following capabilities are deferred until the core contract has been exercised against real sibling repositories:

- remote source acquisition and repository/version pinning;
- component self-description;
- automatic skill discovery;
- JSON/TOML merge operations for MCP or harness settings;
- repair planning;
- lifecycle-hook normalization;
- static harness security auditing;
- UI/control-pane surfaces.

## Canonical staging tree

Adapters currently understand a deliberately small canonical namespace:

```text
skills/
commands/
agents/   # Claude
rules/    # Claude
hooks/    # Claude, explicit consent required when executable
```

Codex maps canonical `commands/` content into its `prompts/` namespace. Claude preserves the canonical command namespace.

Planning never fetches source content. The caller supplies an explicit local staging root; acquisition and provenance are a separate trust boundary.

## Managed-state invariants

`apply` resolves all managed destinations to canonical absolute paths, preflights the full operation set before the first target-file mutation, revalidates sources and destinations immediately before each commit, writes through same-directory temporary files, and rolls back committed files if a later operation fails.

A destination is only considered managed after its absolute path, module owner, and SHA-256 digest have been committed to install state. Updates refuse to overwrite unmanaged content or locally drifted managed files.

`doctor` and `uninstall` fail closed when managed paths are relative, escape the recorded target root, traverse symlinked parents, are themselves symlinks, or become non-regular filesystem objects. Uninstall deletes only regular, unmodified managed files.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src
pytest
```

CI runs the quality suite on Python 3.12 and 3.13. The hardened v0.1 branch includes 15 regression tests covering ordinary lifecycle behavior and adversarial filesystem cases.
