from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback keeps atomic replacement available.
    fcntl = None  # type: ignore[assignment]


T = TypeVar("T")


class JsonStateStore:
    """Human-readable JSON state with atomic replacement and process locking."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self, default: Any) -> Any:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default

    def read(self, default: Any) -> Any:
        """Read atomically replaced state without creating locks/directories.

        Reads are intentionally side-effect free: absence is represented by the
        default value. Writers still use the locked transition methods.
        """
        return self._read_unlocked(default)

    def _write_unlocked(self, value: Any) -> None:
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

    def write(self, value: Any) -> None:
        with self.locked():
            self._write_unlocked(value)

    def update(self, default: T, transform: Callable[[T], T]) -> T:
        """Apply a read-modify-write transition while holding one process lock."""
        with self.locked():
            current = self._read_unlocked(default)
            if not isinstance(current, type(default)):
                current = default
            updated = transform(current)
            self._write_unlocked(updated)
            return updated

    def append_json_line(self, value: Any) -> None:
        with self.locked():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
