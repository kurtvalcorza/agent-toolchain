from pathlib import Path, PurePosixPath

from .base import HarnessAdapter


class CodexAdapter(HarnessAdapter):
    target = "codex"

    def destination_for(self, source_relative_path: str) -> Path:
        source = PurePosixPath(source_relative_path)
        if not source.parts:
            raise ValueError("empty source path")
        namespace = source.parts[0]
        if namespace == "skills":
            relative = source
        elif namespace == "commands":
            relative = PurePosixPath("prompts", *source.parts[1:])
        else:
            raise ValueError(f"unsupported Codex canonical namespace: {namespace}")
        return self._under_root(relative)
