"""事件存储：内存实现与 JSONL 持久化实现。

事件一旦追加即不可变；JSONL 文件每行一个带类型标记的事件信封，
重启服务时完整重放，保证立项、评审、授权等历史依据不被破坏。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from . import events as event_types
from .events import DomainEvent
from .models import (
    Confidentiality,
    Contribution,
    ContributionKind,
    PartyKind,
    ScopeType,
    UsageScope,
)
from .serializers import event_to_envelope


class EventStore(Protocol):
    def append(self, event: DomainEvent) -> DomainEvent: ...

    def events(self) -> list[DomainEvent]: ...

    def next_seq(self) -> int: ...


class MemoryEventStore:
    """进程内事件存储，主要用于测试。"""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []

    def append(self, event: DomainEvent) -> DomainEvent:
        object.__setattr__(event, "seq", len(self._events) + 1)
        self._events.append(event)
        return event

    def events(self) -> list[DomainEvent]:
        return list(self._events)

    def next_seq(self) -> int:
        return len(self._events) + 1


def _contribution(data: dict[str, object]) -> Contribution:
    return Contribution(
        party_code=str(data["party_code"]),
        person_code=None if data.get("person_code") is None else str(data["person_code"]),
        kind=ContributionKind(data["kind"]),
        description=str(data.get("description", "")),
    )


def _scope(data: dict[str, object]) -> UsageScope:
    return UsageScope(
        scope_type=ScopeType(data["scope_type"]),
        allowed_parties=frozenset(str(x) for x in data.get("allowed_parties", ())),  # type: ignore[arg-type]
    )


def _work_package(seq: int, data: dict[str, object]) -> DomainEvent:
    return event_types.WorkPackageCreated(
        seq=seq,
        package_code=str(data["package_code"]),
        program_code=str(data["program_code"]),
        name=str(data["name"]),
        lead_party=str(data["lead_party"]),
        dependencies=frozenset(str(x) for x in data["dependencies"]),  # type: ignore[arg-type]
        budget=float(data["budget"]),
        responsibilities=tuple(
            (str(item[0]), str(item[1])) for item in data["responsibilities"]  # type: ignore[index]
        ),
        deliverables=tuple(str(x) for x in data["deliverables"]),
    )


def _achievement_submitted(seq: int, data: dict[str, object]) -> DomainEvent:
    return event_types.AchievementSubmitted(
        seq=seq,
        code=str(data["code"]),
        version=int(data["version"]),
        package_code=str(data["package_code"]),
        program_code=str(data["program_code"]),
        title=str(data["title"]),
        contributions=tuple(_contribution(item) for item in data["contributions"]),  # type: ignore[arg-type]
        confidentiality=Confidentiality(data["confidentiality"]),
        ip_terms=str(data["ip_terms"]),
        scope=_scope(data["scope"]),  # type: ignore[arg-type]
        submitted_by=str(data["submitted_by"]),
        supersedes=None if data.get("supersedes") is None else int(data["supersedes"]),
    )


def _conclusion(seq: int, data: dict[str, object]) -> DomainEvent:
    return event_types.MilestoneConclusionRecorded(
        seq=seq,
        milestone_code=str(data["milestone_code"]),
        achievement_code=str(data["achievement_code"]),
        version=int(data["version"]),
        approved=bool(data["approved"]),
        votes=tuple(
            (str(v[0]), str(v[1]), bool(v[2]), str(v[3])) for v in data["votes"]  # type: ignore[index]
        ),
    )


_DECODERS = {
    "LabCreated": lambda seq, d: event_types.LabCreated(
        seq=seq, lab_code=str(d["lab_code"]), name=str(d["name"])
    ),
    "PartyRegistered": lambda seq, d: event_types.PartyRegistered(
        seq=seq, code=str(d["code"]), name=str(d["name"]), kind=PartyKind(d["kind"])
    ),
    "ProgramCreated": lambda seq, d: event_types.ProgramCreated(
        seq=seq,
        program_code=str(d["program_code"]),
        name=str(d["name"]),
        objectives=str(d["objectives"]),
        party_codes=tuple(str(x) for x in d["party_codes"]),
        budget=float(d["budget"]),
    ),
    "PartyJoinedProgram": lambda seq, d: event_types.PartyJoinedProgram(
        seq=seq,
        program_code=str(d["program_code"]),
        party_code=str(d["party_code"]),
        responsibility=str(d.get("responsibility", "")),
    ),
    "PartyWithdrewFromProgram": lambda seq, d: event_types.PartyWithdrewFromProgram(
        seq=seq,
        program_code=str(d["program_code"]),
        party_code=str(d["party_code"]),
        reason=str(d.get("reason", "")),
    ),
    "PersonJoined": lambda seq, d: event_types.PersonJoined(
        seq=seq,
        person_code=str(d["person_code"]),
        party_code=str(d["party_code"]),
        name=str(d["name"]),
    ),
    "PersonLeft": lambda seq, d: event_types.PersonLeft(
        seq=seq, person_code=str(d["person_code"]), reason=str(d.get("reason", ""))
    ),
    "ConflictDeclared": lambda seq, d: event_types.ConflictDeclared(
        seq=seq,
        person_code=str(d["person_code"]),
        program_code=str(d["program_code"]),
        description=str(d["description"]),
    ),
    "ConflictCleared": lambda seq, d: event_types.ConflictCleared(
        seq=seq,
        person_code=str(d["person_code"]),
        program_code=str(d["program_code"]),
    ),
    "WorkPackageCreated": _work_package,
    "AchievementSubmitted": _achievement_submitted,
    "TechnicalReviewVoted": lambda seq, d: event_types.TechnicalReviewVoted(
        seq=seq,
        achievement_code=str(d["achievement_code"]),
        version=int(d["version"]),
        party_code=str(d["party_code"]),
        person_code=str(d["person_code"]),
        approved=bool(d["approved"]),
        comment=str(d.get("comment", "")),
    ),
    "TechnicalAcceptanceRecorded": lambda seq, d: event_types.TechnicalAcceptanceRecorded(
        seq=seq,
        achievement_code=str(d["achievement_code"]),
        version=int(d["version"]),
        accepted=bool(d["accepted"]),
        note=str(d.get("note", "")),
    ),
    "RightsVoteCast": lambda seq, d: event_types.RightsVoteCast(
        seq=seq,
        achievement_code=str(d["achievement_code"]),
        version=int(d["version"]),
        milestone_code=str(d["milestone_code"]),
        party_code=str(d["party_code"]),
        person_code=str(d["person_code"]),
        approved=bool(d["approved"]),
        comment=str(d.get("comment", "")),
    ),
    "MilestoneConclusionRecorded": _conclusion,
    "AchievementPublished": lambda seq, d: event_types.AchievementPublished(
        seq=seq,
        achievement_code=str(d["achievement_code"]),
        version=int(d["version"]),
    ),
    "GrantIssued": lambda seq, d: event_types.GrantIssued(
        seq=seq,
        grant_code=str(d["grant_code"]),
        achievement_code=str(d["achievement_code"]),
        version=int(d["version"]),
        person_code=str(d["person_code"]),
        party_code=str(d["party_code"]),
        confidentiality=Confidentiality(d["confidentiality"]),
        scope_type=ScopeType(d["scope_type"]),
        reason=str(d["reason"]),
    ),
    "AccessChecked": lambda seq, d: event_types.AccessChecked(
        seq=seq,
        person_code=str(d["person_code"]),
        achievement_code=str(d["achievement_code"]),
        version=int(d["version"]),
        allowed=bool(d["allowed"]),
        reason=str(d["reason"]),
        grant_code=None if d.get("grant_code") is None else str(d["grant_code"]),
    ),
    "DisputeFrozen": lambda seq, d: event_types.DisputeFrozen(
        seq=seq, target_code=str(d["target_code"]), reason=str(d["reason"])
    ),
    "DisputeResolved": lambda seq, d: event_types.DisputeResolved(
        seq=seq, target_code=str(d["target_code"]), resolution=str(d["resolution"])
    ),
}


def decode_envelope(envelope: dict[str, object]) -> DomainEvent:
    event_type = str(envelope["type"])
    decoder = _DECODERS.get(event_type)
    if decoder is None:
        raise ValueError(f"未知事件类型：{event_type}")
    return decoder(int(envelope["seq"]), envelope["data"])  # type: ignore[arg-type]


class JsonlEventStore:
    """把事件追加到 JSONL 文件，并在启动时完整重放。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._events: list[DomainEvent] = []
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        self._events.append(decode_envelope(json.loads(line)))

    def append(self, event: DomainEvent) -> DomainEvent:
        object.__setattr__(event, "seq", len(self._events) + 1)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event_to_envelope(event), ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        self._events.append(event)
        return event

    def events(self) -> list[DomainEvent]:
        return list(self._events)

    def next_seq(self) -> int:
        return len(self._events) + 1
