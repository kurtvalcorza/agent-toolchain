from __future__ import annotations

from pathlib import Path

from .base import HarnessAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter

_ADAPTERS = {
    ClaudeAdapter.target: ClaudeAdapter,
    CodexAdapter.target: CodexAdapter,
}


def get_adapter(target: str, root: str | Path) -> HarnessAdapter:
    try:
        adapter_type = _ADAPTERS[target]
    except KeyError as exc:
        raise ValueError(f"unsupported target: {target}") from exc
    return adapter_type(root)
