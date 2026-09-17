#!/usr/bin/env python3
"""Compatibility shim for the optional Hermes browser handoff adapter.

The implementation lives under adapters/hermes/scripts and is not part of the
agent-neutral Academia OS runtime.
"""
from adapters.hermes.scripts.academic_os_brightspace_handoff import *  # noqa: F401,F403

if __name__ == "__main__":
    from adapters.hermes.scripts.academic_os_brightspace_handoff import main
    raise SystemExit(main())
