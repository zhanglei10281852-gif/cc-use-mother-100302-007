"""校企联合实验室成果协同领域包。"""

from .contracts import ResearchWorkPackage, unique_by_identity
from .errors import ConflictError, DomainError, NotFoundError, StateError, ValidationError
from .events import Event, Ledger
from .model import (
    ACHIEVEMENT_STATE_LABELS,
    CONFIDENTIALITY_LABELS,
    MILESTONE_ACHIEVED,
    MILESTONE_NOT_ACHIEVED,
    AccessDecision,
)
from .service import (
    ACCESS_CHECKED,
    REASON_CLEARANCE,
    REASON_COI,
    REASON_FROZEN,
    REASON_MEMBER_WITHDRAWN,
    REASON_NOT_PUBLISHED,
    REASON_REPLACED,
    REASON_SCOPE,
    CollaborationService,
)

__all__ = [
    "ACCESS_CHECKED",
    "ACHIEVEMENT_STATE_LABELS",
    "CONFIDENTIALITY_LABELS",
    "MILESTONE_ACHIEVED",
    "MILESTONE_NOT_ACHIEVED",
    "REASON_CLEARANCE",
    "REASON_COI",
    "REASON_FROZEN",
    "REASON_MEMBER_WITHDRAWN",
    "REASON_NOT_PUBLISHED",
    "REASON_REPLACED",
    "REASON_SCOPE",
    "AccessDecision",
    "CollaborationService",
    "ConflictError",
    "DomainError",
    "Event",
    "Ledger",
    "NotFoundError",
    "ResearchWorkPackage",
    "StateError",
    "ValidationError",
    "unique_by_identity",
]
