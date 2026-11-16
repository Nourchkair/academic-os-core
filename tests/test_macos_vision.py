from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from academia_os import macos_vision


def helper(tmp_path: Path) -> Path:
    path = tmp_path / "vision_ocr"
    path.write_bytes(b"")
    return path


def test_recognize_returns_one_text_per_image(tmp_path: Path, monkeypatch: Any) -> None:
    binary = helper(tmp_path)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(macos_vision, "helper_path", lambda: binary)

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=json.dumps({"images": ["first page", ""]}), stderr="")

    monkeypatch.setattr(macos_vision.subprocess, "run", fake_run)
    images = [tmp_path / "1.png", tmp_path / "2.png"]

    assert macos_vision.recognize(images, timeout=30) == ["first page", ""]
    assert captured["command"][0] == str(binary)
    assert captured["command"][1:] == [str(images[0]), str(images[1])]


def test_recognize_returns_none_without_an_engine(monkeypatch: Any) -> None:
    monkeypatch.setattr(macos_vision, "helper_path", lambda: None)
    monkeypatch.setattr(macos_vision.shutil, "which", lambda name: None)

    assert macos_vision.recognize([Path("page.png")], timeout=5) is None


def test_recognize_rejects_mismatched_or_failed_output(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(macos_vision, "helper_path", lambda: helper(tmp_path))
    monkeypatch.setattr(
        macos_vision.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"images":[]}', stderr=""),
    )
    assert macos_vision.recognize([Path("page.png")], timeout=5) is None

    monkeypatch.setattr(
        macos_vision.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    assert macos_vision.recognize([Path("page.png")], timeout=5) is None


def test_recognize_rejects_invalid_json(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(macos_vision, "helper_path", lambda: helper(tmp_path))
    monkeypatch.setattr(
        macos_vision.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="not json", stderr=""),
    )

    assert macos_vision.recognize([Path("page.png")], timeout=5) is None


def test_available_accepts_a_packaged_helper(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(macos_vision, "helper_path", lambda: helper(tmp_path))
    monkeypatch.setattr(macos_vision.shutil, "which", lambda name: None)

    assert macos_vision.available() is True


def test_available_requires_an_engine(monkeypatch: Any) -> None:
    monkeypatch.setattr(macos_vision, "helper_path", lambda: None)
    monkeypatch.setattr(macos_vision.shutil, "which", lambda name: None)

    assert macos_vision.available() is False
