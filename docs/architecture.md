# Architecture

## Purpose

`agent-toolchain` is the distribution and harness-adaptation plane for independently usable agent
capabilities. It deliberately does not own the semantics of those capabilities.

## Core pipeline

```text
catalog
  -> profile/component selection
  -> dependency and target resolution
  -> harness adapter
  -> exact copy-file operations
  -> safe apply
  -> SHA-256 managed state
  -> doctor / uninstall
```

Resolution and planning are pure with respect to the target filesystem. `apply` is the only stage
that mutates managed harness state.

## Canonical staging contract

The initial implementation plans from an already staged canonical component tree. Source
acquisition from Git repositories is intentionally deferred: fetching, version pinning, signature
verification, and cache policy form a separate trust boundary and should not be hidden inside
planning.

Canonical namespaces currently understood by adapters are intentionally small:

- `skills/`
- `commands/` (Claude keeps the namespace; Codex maps it to `prompts/`)
- Claude additionally accepts `agents/`, `rules/`, and `hooks/`.

A module marked `executable` is not planned unless hook execution is explicitly enabled.

## Managed ownership

An installed file is managed only after its destination path, module owner, and SHA-256 digest are
written to install state. Subsequent apply refuses to overwrite:

- an existing destination absent from prior managed state; or
- a previously managed destination whose bytes no longer match the recorded digest.

Uninstall uses the same rule in reverse: modified or symlinked files are preserved.

## Deferred work

The first core intentionally leaves these outside the implementation:

- remote source acquisition and version pinning;
- JSON/TOML merge operations for MCP or harness settings;
- repair planning;
- component self-description;
- automatic skill discovery;
- lifecycle-hook normalization;
- static harness security scanning;
- a UI/control pane.

Those should be added only after the resolver/planner/ownership contract is exercised by real
`agent-relay` and `agentic-research` integrations.
