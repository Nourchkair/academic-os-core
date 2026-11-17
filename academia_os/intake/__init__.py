"""Universal academic intake: pasted sources to candidate facts and ChangeSets."""
from .model import CANDIDATE_STATUSES, INTAKE_STATUSES, Candidate, Intake
from .service import IntakeService
from .store import IntakeStore

__all__ = [
    "CANDIDATE_STATUSES",
    "INTAKE_STATUSES",
    "Candidate",
    "Intake",
    "IntakeService",
    "IntakeStore",
]
