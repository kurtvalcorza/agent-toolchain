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

## v0.1 filesystem threat model

The v0.1 apply path is fail-closed for the staged bytes it commits: the source is checked against
the planned SHA-256 before copying, and the SHA-256 of the bytes actually copied into the temporary
file is checked against the same planned digest before `os.replace()` may publish the destination.
A source rewrite or replacement in that interval therefore aborts and rolls back instead of
silently installing bytes that were not present in the immutable plan.

Path safety in v0.1 is intentionally scoped to a local filesystem that is not concurrently mutated
by an adversary while `apply` is running. The implementation repeatedly checks target-root
containment and rejects symlink components, but those pathname checks are not yet coupled to the
subsequent `mkdir`, `mkstemp`, and `os.replace` operations through directory file descriptors and
no-follow primitives. A hostile process with permission to replace a validated destination parent
between those operations remains outside the v0.1 guarantee. Closing that race requires a later
fd-relative/no-follow implementation; until then, documentation and release claims must not state
that `apply` is safe against concurrent hostile filesystem mutation.

## Deferred work

The first core intentionally leaves these outside the implementation:

- remote source acquisition and version pinning;
- JSON/TOML merge operations for MCP or harness settings;
- repair planning;
- component self-description;
- automatic skill discovery;
- lifecycle-hook normalization;
- static harness security scanning;
- fd-relative/no-follow hardening against concurrent hostile destination-path mutation;
- a UI/control pane.

Those should be added only after the resolver/planner/ownership contract is exercised by real
`agent-relay` and `agentic-research` integrations.
