"""Local macOS Vision OCR for page images that Academia has already rendered.

Academia renders PDF pages itself, so this bridge only recognizes images. A
packaged app ships a compiled helper next to this module; a source checkout
compiles the embedded Swift source once into the user cache. Both paths keep
recognition entirely on the local machine.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

HELPER_NAME = "vision_ocr"

VISION_SWIFT_SOURCE = r'''import Foundation
import ImageIO
import Vision

let paths = Array(CommandLine.arguments.dropFirst())
var results: [String] = []
for path in paths {
    guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        results.append("")
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["en-US"]
    do {
        try VNImageRequestHandler(cgImage: image).perform([request])
    } catch {
        results.append("")
        continue
    }
    let text = (request.results ?? [])
        .compactMap { $0.topCandidates(1).first?.string }
        .joined(separator: "\n")
    results.append(text)
}
let payload: [String: Any] = ["images": results]
let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
'''


def _usable(candidate: Path) -> Path | None:
    if not candidate.is_file():
        return None
    if not os.access(candidate, os.X_OK):
        try:
            os.chmod(candidate, 0o755)
        except OSError:
            return None
    return candidate


def helper_path() -> Path | None:
    """Return the compiled helper shipped with the app, if one is present."""

    override = os.environ.get("ACADEMIA_VISION_OCR")
    if override:
        return _usable(Path(override).expanduser())
    return _usable(Path(__file__).resolve().parent / "_bin" / HELPER_NAME)


def _cache_directory() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "academia-os" / "vision-ocr"


def compiled_helper() -> Path | None:
    """Compile the embedded source once for source checkouts without a bundle."""

    compiler = shutil.which("swiftc") if sys.platform == "darwin" else None
    if compiler is None:
        return None
    digest = hashlib.sha256(VISION_SWIFT_SOURCE.encode("utf-8")).hexdigest()[:16]
    target = _cache_directory() / digest / HELPER_NAME
    if target.is_file():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        source = target.parent / "vision_ocr.swift"
        source.write_text(VISION_SWIFT_SOURCE, encoding="utf-8")
        staging = target.with_suffix(".tmp")
        compiled = subprocess.run(
            [compiler, "-O", "-o", str(staging), str(source)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if compiled.returncode or not staging.is_file():
            staging.unlink(missing_ok=True)
            return None
        os.replace(staging, target)
        return target
    except (OSError, subprocess.TimeoutExpired):
        return None


def available() -> bool:
    """Whether this machine can recognize images with Vision right now."""

    if helper_path() is not None:
        return True
    return sys.platform == "darwin" and (
        shutil.which("swiftc") is not None or shutil.which("swift") is not None
    )


def recognize(paths: Sequence[Path], *, timeout: float) -> list[str] | None:
    """Return one recognized string per image, or None when Vision cannot run.

    A package build compiles ``VISION_SWIFT_SOURCE`` into a small helper, so
    students need no developer tools. Source checkouts compile the same source
    into the user cache, and fall back to the Swift interpreter only when no
    compiler is available.
    """

    if not paths:
        return []
    helper = helper_path() or compiled_helper()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if helper is not None:
            command = [str(helper), *(str(path) for path in paths)]
        else:
            swift = shutil.which("swift") if sys.platform == "darwin" else None
            if swift is None:
                return None
            temporary = tempfile.TemporaryDirectory(prefix="academia-vision-")
            script = Path(temporary.name) / "vision_ocr.swift"
            script.write_text(VISION_SWIFT_SOURCE, encoding="utf-8")
            command = [swift, str(script), *(str(path) for path in paths)]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(1.0, timeout),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        images = payload.get("images") if isinstance(payload, dict) else None
        if not isinstance(images, list) or len(images) != len(paths):
            return None
        return [value if isinstance(value, str) else "" for value in images]
    finally:
        if temporary is not None:
            temporary.cleanup()
