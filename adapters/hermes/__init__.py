"""Optional Hermes integration adapter.

Academia OS core does not import or require this package for ordinary workspace
operation. The adapter translates neutral local jobs into Hermes commands when
the user explicitly enables Hermes.
"""

from .adapter import HermesAdapter, hermes_status

__all__ = ["HermesAdapter", "hermes_status"]
