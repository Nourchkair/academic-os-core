from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from academia_os.config import hermes_config


@dataclass(frozen=True)
class HermesAdapter:
    """Translate neutral Academia OS jobs to optional Hermes operations."""

    config: dict[str, Any]

    @property
    def enabled(self) -> bool:
        return bool(hermes_config(self.config).get("enabled"))

    @property
    def executable(self) -> str | None:
        return shutil.which("hermes")

    @property
    def home(self) -> Path | None:
        value = hermes_config(self.config).get("home_directory")
        return Path(value).expanduser().resolve() if isinstance(value, str) and value.strip() else None

    @property
    def profile(self) -> str:
        return str(hermes_config(self.config).get("profile", "default"))

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"name": "Hermes", "status": "available", "configured": False, "detected": bool(self.executable), "message": "Optional adapter is disabled."}
        if not self.executable:
            return {"name": "Hermes", "status": "configured", "configured": True, "detected": False, "message": "Configured but Hermes is not installed."}
        return {"name": "Hermes", "status": "connected", "configured": True, "detected": True, "message": "Hermes executable detected; scheduling remains user-controlled."}

    def cron_command(self, spec: dict[str, Any]) -> str:
        if not self.enabled:
            raise RuntimeError("Hermes adapter is not enabled")
        args = ["hermes", "cron", "create", str(spec["schedule"]), str(spec["prompt"]), "--name", str(spec["name"]), "--deliver", "local", "--workdir", str(spec["workdir"])]
        if spec.get("profile"):
            args.extend(["--profile", str(spec["profile"])])
        for skill in spec.get("skills", []):
            args.extend(["--skill", str(skill)])
        if spec.get("script"):
            args.extend(["--script", str(spec["script"])])
        return " ".join(shlex.quote(arg) for arg in args)


def hermes_status(config: dict[str, Any]) -> dict[str, Any]:
    return HermesAdapter(config).status()
