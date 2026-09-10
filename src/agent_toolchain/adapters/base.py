from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path, PurePath

from .._paths import lexical_absolute


class HarnessAdapter(ABC):
    target: str

    def __init__(self, root: str | Path) -> None:
        self.root = lexical_absolute(Path(root).expanduser())

    @abstractmethod
    def destination_for(self, source_relative_path: str) -> Path:
        """Map one canonical staged file to a harness-native destination."""

    def install_state_path(self) -> Path:
        return self.root / ".agent-toolchain" / "install-state.json"

    def _under_root(self, relative: PurePath) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe adapter-relative path: {relative}")
        return self.root / relative
