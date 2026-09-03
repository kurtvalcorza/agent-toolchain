# agent-toolchain

Host-neutral distribution and integration tooling for portable AI-agent capabilities.

`agent-toolchain` installs, configures, validates, and maintains agent capabilities across AI coding harnesses without moving domain or runtime semantics into the installer.

> Capabilities own behavior. The toolchain owns distribution, harness adaptation, managed installation state, and drift detection.

## Scope

The toolchain is intended to compose independently usable projects such as:

- `agent-relay` — multi-agent roles, handoffs, review, verification, and convergence;
- `agent-router` — provider/model/executor routing;
- `agent-control` — lifecycle, policy, budgets, authorization, recovery, and audit;
- `agentic-vault` — durable human/agent knowledge and governance;
- `agentic-research` — literature and systematic-review capabilities;
- `agentic-analytics` — analytical execution, provenance, artifacts, and validation.

Every component must remain independently usable without `agent-toolchain`.

## Architectural boundary

```text
canonical component metadata
          |
          v
profile -> component -> module dependency resolution
          |
          v
harness adapter
          |
          v
immutable install plan
          |
          v
safe apply -> content-hashed managed state
          |
          +-> doctor / repair / uninstall
```

The initial implementation deliberately does **not** provide:

- an agent loop or planner;
- model routing;
- domain execution;
- shared conversational memory;
- autonomous self-modification;
- a new policy engine;
- host-specific domain logic.

## Design principles

1. **Plan before mutation.** Resolution and planning are deterministic and inspectable before anything is written.
2. **Capabilities remain authoritative for their own semantics.** Harness adapters translate packaging, not behavior.
3. **Managed files have explicit ownership.** Installed content is content-hashed so drift can be detected without overwriting local edits.
4. **Executable automation requires explicit consent.** Installing skills/configuration must not silently enable hooks.
5. **Target-specific concerns live at the edge.** Canonical component metadata must not depend on Claude Code, Codex, or another harness.
6. **Deterministic facts precede model judgment.** Installation, compatibility, state, and integrity findings are runtime facts.
7. **No mandatory parent dependency.** Components work without the toolchain.

## Initial milestone

The first stable slice targets **Codex** and **Claude Code** and implements:

- versioned manifests;
- profile/component/module resolution;
- target compatibility checks;
- deterministic install-plan generation;
- Codex and Claude harness adapters;
- safe managed application;
- SHA-256 install state;
- `status`, `doctor`, and `uninstall` primitives;
- external integration fixtures for `agent-relay` and `agentic-research`.

## Status

Initial implementation in progress.

## License

MIT.
