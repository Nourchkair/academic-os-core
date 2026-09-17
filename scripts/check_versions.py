from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from academia_os.version import __version__

    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]
    tauri = json.loads((ROOT / "frontend" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    cargo_match = re.search(r"^version = \"([^\"]+)\"", (ROOT / "frontend" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"), re.MULTILINE)
    cargo = cargo_match.group(1) if cargo_match else ""
    values = {"python": __version__, "frontend": package, "tauri": tauri, "cargo": cargo}
    if len(set(values.values())) != 1:
        print(json.dumps(values, indent=2))
        return 1
    print(f"VERSION_OK: {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
