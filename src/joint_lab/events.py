"""领域事件：所有状态变化都以不可变事件追加到历史中。"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Confidentiality,
    Contribution,
    ContributionKind,
    PartyKind,
    ScopeType,
    UsageScope,
)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """事件基类：seq 由事件存储按追加顺序分配。"""

    seq: int


@dataclass(frozen=True, slots=True)
class LabCreated(DomainEvent):
    lab_code: str
    name: str


@dataclass(frozen=True, slots=True)
class PartyRegistered(DomainEvent):
    code: str
    name: str
    kind: PartyKind


@dataclass(frozen=True, slots=True)
class ProgramCreated(DomainEvent):
    program_code: str
    name: str
    objectives: str
    party_codes: tuple[str, ...]
    budget: float


@dataclass(frozen=True, slots=True)
class PartyJoinedProgram(DomainEvent):
    program_code: str
    party_code: str
    responsibility: str


@dataclass(frozen=True, slots=True)
class PartyWithdrewFromProgram(DomainEvent):
    program_code: str
    party_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class PersonJoined(DomainEvent):
    person_code: str
    party_code: str
    name: str


@dataclass(frozen=True, slots=True)
class PersonLeft(DomainEvent):
    person_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ConflictDeclared(DomainEvent):
    person_code: str
    program_code: str
    description: str


@dataclass(frozen=True, slots=True)
class ConflictCleared(DomainEvent):
    person_code: str
    program_code: str


@dataclass(frozen=True, slots=True)
class WorkPackageCreated(DomainEvent):
    package_code: str
    program_code: str
    name: str
    lead_party: str
    dependencies: frozenset[str]
    budget: float
    responsibilities: tuple[tuple[str, str], ...]
    deliverables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AchievementSubmitted(DomainEvent):
    code: str
    version: int
    package_code: str
    program_code: str
    title: str
    contributions: tuple[Contribution, ...]
    confidentiality: Confidentiality
    ip_terms: str
    scope: UsageScope
    submitted_by: str
    supersedes: int | None


@dataclass(frozen=True, slots=True)
class TechnicalReviewVoted(DomainEvent):
    achievement_code: str
    version: int
    party_code: str
    person_code: str
    approved: bool
    comment: str


@dataclass(frozen=True, slots=True)
class TechnicalAcceptanceRecorded(DomainEvent):
    achievement_code: str
    version: int
    accepted: bool
    note: str


@dataclass(frozen=True, slots=True)
class RightsVoteCast(DomainEvent):
    achievement_code: str
    version: int
    milestone_code: str
    party_code: str
    person_code: str
    approved: bool
    comment: str


@dataclass(frozen=True, slots=True)
class MilestoneConclusionRecorded(DomainEvent):
    milestone_code: str
    achievement_code: str
    version: int
    approved: bool
    votes: tuple[tuple[str, str, bool, str], ...]


@dataclass(frozen=True, slots=True)
class AchievementPublished(DomainEvent):
    achievement_code: str
    version: int


@dataclass(frozen=True, slots=True)
class GrantIssued(DomainEvent):
    grant_code: str
    achievement_code: str
    version: int
    person_code: str
    party_code: str
    confidentiality: Confidentiality
    scope_type: ScopeType
    reason: str


@dataclass(frozen=True, slots=True)
class AccessChecked(DomainEvent):
    person_code: str
    achievement_code: str
    version: int
    allowed: bool
    reason: str
    grant_code: str | None


@dataclass(frozen=True, slots=True)
class DisputeFrozen(DomainEvent):
    target_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class DisputeResolved(DomainEvent):
    target_code: str
    resolution: str
