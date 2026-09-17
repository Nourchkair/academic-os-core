from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class JsonStateStore:
    """Small atomic JSON store for rebuildable local state."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()

    def read(self, default: Any) -> Any:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value
        except (OSError, ValueError, TypeError):
            return default

    def write(self, value: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
