"""校企联合实验室成果协同领域包。"""

from .contracts import ResearchWorkPackage, unique_by_identity
from .errors import ConflictError, DomainError, NotFound
from .events import DomainEvent
from .models import (
    AccessDecision,
    Achievement,
    AchievementState,
    Confidentiality,
    Contribution,
    ContributionKind,
    Freeze,
    Grant,
    MilestoneConclusion,
    Party,
    PartyKind,
    ScopeType,
    UsageScope,
    WorkPackagePlan,
)
from .repository import EventStore, JsonlEventStore, MemoryEventStore
from .service import JointLabService

__all__ = [
    "AccessDecision",
    "Achievement",
    "AchievementState",
    "Confidentiality",
    "ConflictError",
    "Contribution",
    "ContributionKind",
    "DomainError",
    "DomainEvent",
    "EventStore",
    "Freeze",
    "Grant",
    "JointLabService",
    "JsonlEventStore",
    "MemoryEventStore",
    "MilestoneConclusion",
    "NotFound",
    "Party",
    "PartyKind",
    "ResearchWorkPackage",
    "ScopeType",
    "UsageScope",
    "WorkPackagePlan",
    "unique_by_identity",
]
