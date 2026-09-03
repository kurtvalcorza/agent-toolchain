from pathlib import Path, PurePosixPath

from .base import HarnessAdapter


class ClaudeAdapter(HarnessAdapter):
    target = "claude"

    def destination_for(self, source_relative_path: str) -> Path:
        source = PurePosixPath(source_relative_path)
        if not source.parts:
            raise ValueError("empty source path")
        namespace = source.parts[0]
        if namespace not in {"skills", "agents", "commands", "rules", "hooks"}:
            raise ValueError(f"unsupported Claude canonical namespace: {namespace}")
        return self._under_root(PurePosixPath(*source.parts))
