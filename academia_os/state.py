from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback keeps atomic replacement available.
    fcntl = None  # type: ignore[assignment]


T = TypeVar("T")

_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.Lock:
    """Return the in-process lock shared by stores targeting the same file."""
    key = str(path.expanduser().resolve())
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PROCESS_LOCKS[key] = lock
        return lock


class StateCorruptionError(ValueError):
    """Durable state is unreadable or has an unexpected shape.

    The store never replaces a corrupt file with an empty default. Callers can
    preserve a diagnostic copy with ``quarantine`` and ask the student to
    restore from backup.
    """

    def __init__(self, path: Path, message: str, *, quarantine_path: Path | None = None) -> None:
        super().__init__(message)
        self.path = Path(path)
        self.quarantine_path = quarantine_path

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"path": str(self.path), "message": str(self)}
        if self.quarantine_path is not None:
            value["quarantine_path"] = str(self.quarantine_path)
        return value


class JsonStateStore:
    """Human-readable JSON state with atomic replacement and process locking."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser()
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._thread_lock = _thread_lock_for(self.lock_path)

    @contextmanager
    def locked(self) -> Iterator[None]:
        # flock coordinates separate processes. A separate mutex is needed
        # for threads: on macOS, competing flock calls from threads in one
        # process can fail with EDEADLK instead of waiting for the lock holder.
        with self._thread_lock:
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

    def _read_strict_unlocked(self, default: Any) -> Any:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return copy.deepcopy(default)
        except OSError as exc:
            # An atomic replace by another local writer can briefly make the
            # file unreadable. Retry once before calling the state corrupt.
            try:
                raw = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return copy.deepcopy(default)
            except OSError:
                raise StateCorruptionError(self.path, "state file could not be read") from exc
        try:
            value = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise StateCorruptionError(self.path, "state file is not valid JSON") from exc
        if not isinstance(value, type(default)):
            raise StateCorruptionError(
                self.path,
                f"state file has an unexpected top-level type; expected {type(default).__name__}",
            )
        return value

    def read_strict(self, default: Any, *, quarantine: bool = False) -> Any:
        """Read durable state and fail closed instead of silently resetting it."""
        try:
            return self._read_strict_unlocked(default)
        except StateCorruptionError as exc:
            if not quarantine:
                raise
            destination = self.quarantine()
            raise StateCorruptionError(
                self.path,
                str(exc),
                quarantine_path=destination,
            ) from None

    def quarantine(self) -> Path:
        """Copy a damaged durable state file for diagnosis without deleting it."""
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        counter = 1
        while destination.exists():
            destination = self.path.with_name(f"{self.path.name}.corrupt-{stamp}-{counter}")
            counter += 1
        shutil.copy2(self.path, destination)
        return destination

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

    def update_strict(self, default: T, transform: Callable[[T], T], *, quarantine: bool = False) -> T:
        """Apply a strict read-modify-write transition for durable records."""
        with self.locked():
            try:
                current = self._read_strict_unlocked(default)
            except StateCorruptionError as exc:
                if not quarantine:
                    raise
                destination = self.quarantine()
                raise StateCorruptionError(
                    self.path,
                    str(exc),
                    quarantine_path=destination,
                ) from None
            updated = transform(current)
            self._write_unlocked(updated)
            return updated

    def append_json_line(self, value: Any) -> None:
        with self.locked():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
