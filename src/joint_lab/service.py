"""联合实验室成果协同核心领域服务。

所有命令都先执行业务规则校验，再以不可变事件追加到事件存储；
当前状态由完整事件历史重放得到。授权记录（Grant）一旦生成便永久保留，
而每次访问都依据当前成员关系、冲突、替换、冻结等状态重新判定，
从而做到"状态及时改变后续访问，但不破坏历史使用依据"。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import fields

from .errors import ConflictError, DomainError, NotFound
from .events import (
    AccessChecked,
    AchievementPublished,
    AchievementSubmitted,
    ConflictCleared,
    ConflictDeclared,
    DisputeFrozen,
    DisputeResolved,
    GrantIssued,
    LabCreated,
    MilestoneConclusionRecorded,
    PartyJoinedProgram,
    PartyRegistered,
    PartyWithdrewFromProgram,
    PersonJoined,
    PersonLeft,
    ProgramCreated,
    RightsVoteCast,
    TechnicalAcceptanceRecorded,
    TechnicalReviewVoted,
    WorkPackageCreated,
)
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
from .repository import EventStore, MemoryEventStore
from .serializers import to_jsonable


class _ProgramState:
    __slots__ = ("name", "objectives", "parties", "budget")

    def __init__(self, name: str, objectives: str, parties: set[str], budget: float) -> None:
        self.name = name
        self.objectives = objectives
        self.parties = parties
        self.budget = budget


class _PersonState:
    __slots__ = ("party_code", "name", "active", "conflict_programs")

    def __init__(self, party_code: str, name: str) -> None:
        self.party_code = party_code
        self.name = name
        self.active = True
        self.conflict_programs: set[str] = set()


class JointLabService:
    """校企联合实验室成果协同服务。"""

    def __init__(self, store: EventStore | None = None) -> None:
        self.store: EventStore = store if store is not None else MemoryEventStore()
        self.lab_code: str | None = None
        self.lab_name: str | None = None
        self.parties: dict[str, Party] = {}
        self.programs: dict[str, _ProgramState] = {}
        self.persons: dict[str, _PersonState] = {}
        self.packages: dict[str, WorkPackagePlan] = {}
        self.achievements: dict[str, dict[int, Achievement]] = {}
        self.tech_votes: dict[tuple[str, int], dict[str, tuple[str, bool, str]]] = {}
        self.tech_decided: set[tuple[str, int]] = set()
        self.rights_votes: dict[str, dict[str, tuple[str, bool, str]]] = {}
        self.milestone_target: dict[str, tuple[str, int]] = {}
        self.conclusions: dict[str, MilestoneConclusion] = {}
        self.grants: list[Grant] = []
        self.frozen: dict[str, Freeze] = {}
        for event in self.store.events():
            self._apply(event)

    # ------------------------------------------------------------------ 基础

    def create_lab(self, lab_code: str, name: str) -> LabCreated:
        self._require_text(lab_code, "实验室代码")
        if self.lab_code is not None:
            raise ConflictError("联合实验室已经建立")
        return self._record(LabCreated(seq=0, lab_code=lab_code, name=name))

    def register_party(self, code: str, name: str, kind: PartyKind | str) -> PartyRegistered:
        self._require_text(code, "机构代码")
        self._require_lab()
        if code in self.parties:
            raise ConflictError(f"机构 {code} 已登记")
        return self._record(
            PartyRegistered(seq=0, code=code, name=name, kind=PartyKind(kind))
        )

    def create_program(
        self,
        program_code: str,
        name: str,
        objectives: str,
        party_codes: Iterable[str],
        budget: float = 0.0,
    ) -> ProgramCreated:
        self._require_lab()
        self._require_text(program_code, "合作计划代码")
        if program_code in self.programs:
            raise ConflictError(f"合作计划 {program_code} 已存在")
        members = tuple(dict.fromkeys(party_codes))
        if not members:
            raise DomainError("合作计划至少需要一个参与方")
        for code in members:
            if code not in self.parties:
                raise NotFound(f"参与方 {code} 尚未登记")
        if budget < 0:
            raise DomainError("预算不能为负")
        return self._record(
            ProgramCreated(
                seq=0,
                program_code=program_code,
                name=name,
                objectives=objectives,
                party_codes=members,
                budget=float(budget),
            )
        )

    def join_program(self, program_code: str, party_code: str, responsibility: str = "") -> PartyJoinedProgram:
        program = self._require_program(program_code)
        if party_code not in self.parties:
            raise NotFound(f"参与方 {party_code} 尚未登记")
        if party_code in program.parties:
            raise ConflictError(f"机构 {party_code} 已是计划 {program_code} 成员")
        return self._record(
            PartyJoinedProgram(
                seq=0,
                program_code=program_code,
                party_code=party_code,
                responsibility=responsibility,
            )
        )

    def withdraw_program(self, program_code: str, party_code: str, reason: str = "") -> PartyWithdrewFromProgram:
        program = self._require_program(program_code)
        if party_code not in program.parties:
            raise ConflictError(f"机构 {party_code} 不是计划 {program_code} 成员")
        if len(program.parties) == 1:
            raise DomainError("最后一个参与方不能退出合作计划")
        return self._record(
            PartyWithdrewFromProgram(
                seq=0,
                program_code=program_code,
                party_code=party_code,
                reason=reason,
            )
        )

    # ------------------------------------------------------------------ 人员

    def add_person(self, person_code: str, party_code: str, name: str) -> PersonJoined:
        self._require_text(person_code, "人员代码")
        if party_code not in self.parties:
            raise NotFound(f"参与方 {party_code} 尚未登记")
        if person_code in self.persons:
            raise ConflictError(f"人员 {person_code} 已在组")
        return self._record(
            PersonJoined(seq=0, person_code=person_code, party_code=party_code, name=name)
        )

    def person_left(self, person_code: str, reason: str = "") -> PersonLeft:
        self._require_person(person_code)
        person = self.persons[person_code]
        if not person.active:
            raise ConflictError(f"人员 {person_code} 已离组")
        return self._record(PersonLeft(seq=0, person_code=person_code, reason=reason))

    def declare_conflict(self, person_code: str, program_code: str, description: str) -> ConflictDeclared:
        self._require_person(person_code)
        self._require_program(program_code)
        person = self.persons[person_code]
        if program_code in person.conflict_programs:
            raise ConflictError("该利益冲突已申报")
        return self._record(
            ConflictDeclared(
                seq=0,
                person_code=person_code,
                program_code=program_code,
                description=description,
            )
        )

    def clear_conflict(self, person_code: str, program_code: str) -> ConflictCleared:
        person = self._require_person(person_code)
        if program_code not in person.conflict_programs:
            raise ConflictError("没有待解除的利益冲突申报")
        return self._record(
            ConflictCleared(seq=0, person_code=person_code, program_code=program_code)
        )

    # -------------------------------------------------------------- 工作包

    def create_work_package(
        self,
        package_code: str,
        program_code: str,
        name: str,
        lead_party: str,
        dependencies: Iterable[str] = (),
        budget: float = 0.0,
        responsibilities: dict[str, str] | Sequence[tuple[str, str]] = (),
        deliverables: Iterable[str] = (),
    ) -> WorkPackageCreated:
        program = self._require_program(program_code)
        self._require_text(package_code, "工作包代码")
        if package_code in self.packages:
            raise ConflictError(f"工作包 {package_code} 已存在")
        if lead_party not in program.parties:
            raise DomainError(f"责任方 {lead_party} 不是计划 {program_code} 成员")
        deps = frozenset(dependencies)
        if package_code in deps:
            raise DomainError("工作包不能依赖自身")
        for dep in deps:
            if dep not in self.packages:
                raise NotFound(f"依赖的工作包 {dep} 不存在")
            if self.packages[dep].program_code != program_code:
                raise DomainError(f"工作包依赖 {dep} 不属于同一合作计划")
        resp = tuple(dict(responsibilities).items())
        for party_code, _ in resp:
            if party_code not in program.parties:
                raise NotFound(f"责任分工中的机构 {party_code} 不是计划成员")
        if budget < 0:
            raise DomainError("预算不能为负")
        return self._record(
            WorkPackageCreated(
                seq=0,
                package_code=package_code,
                program_code=program_code,
                name=name,
                lead_party=lead_party,
                dependencies=deps,
                budget=float(budget),
                responsibilities=resp,
                deliverables=tuple(deliverables),
            )
        )

    # ---------------------------------------------------------------- 成果

    def submit_achievement(
        self,
        code: str,
        package_code: str,
        title: str,
        contributions: Sequence[Contribution | dict[str, object]],
        confidentiality: Confidentiality | str,
        ip_terms: str,
        scope: UsageScope | dict[str, object],
        submitted_by: str,
        supersedes: int | None = None,
    ) -> AchievementSubmitted:
        self._require_text(code, "成果代码")
        package = self._require_package(package_code)
        program = self._require_program(package.program_code)
        self._require_not_frozen_any(code, package_code, package.program_code)

        person = self._require_person(submitted_by)
        if not person.active:
            raise DomainError(f"提交人 {submitted_by} 已离组")
        if person.party_code not in program.parties:
            raise DomainError("提交人所属机构已不在该合作计划中")
        if package.program_code in person.conflict_programs:
            raise DomainError("提交人在该合作计划存在未解除的利益冲突")

        normalized_contribs = tuple(self._normalize_contribution(c) for c in contributions)
        if not normalized_contribs:
            raise DomainError("成果必须记录至少一项贡献来源")
        for contrib in normalized_contribs:
            if contrib.party_code not in self.parties:
                raise NotFound(f"贡献来源机构 {contrib.party_code} 尚未登记")
            if contrib.person_code is not None and contrib.person_code not in self.persons:
                raise NotFound(f"贡献人员 {contrib.person_code} 不存在")

        normalized_scope = self._normalize_scope(scope)
        if normalized_scope.scope_type is ScopeType.NAMED_PARTIES and not normalized_scope.allowed_parties:
            raise DomainError("指定机构使用范围必须列出可使用机构")
        for party_code in normalized_scope.allowed_parties:
            if party_code not in program.parties:
                raise DomainError(f"使用范围内的机构 {party_code} 不是计划成员")
        if not ip_terms.strip():
            raise DomainError("必须记录知识产权约定")
        if not title.strip():
            raise DomainError("成果标题不能为空")

        versions = self.achievements.setdefault(code, {})
        version = len(versions) + 1
        latest = version - 1
        if version == 1:
            if supersedes is not None:
                raise DomainError("首个版本没有可替换的旧版本")
        elif supersedes != latest:
            raise ConflictError(f"成果 {code} 只能替换最新版本 v{latest}")

        return self._record(
            AchievementSubmitted(
                seq=0,
                code=code,
                version=version,
                package_code=package_code,
                program_code=package.program_code,
                title=title,
                contributions=normalized_contribs,
                confidentiality=Confidentiality(confidentiality),
                ip_terms=ip_terms,
                scope=normalized_scope,
                submitted_by=submitted_by,
                supersedes=supersedes,
            )
        )

    # ------------------------------------------------------------ 技术验收

    def technical_review(
        self,
        achievement_code: str,
        party_code: str,
        person_code: str,
        approved: bool,
        comment: str = "",
    ) -> TechnicalReviewVoted:
        achievement = self._require_version(achievement_code)
        key = (achievement_code, achievement.version)
        if key in self.tech_decided:
            raise ConflictError("技术验收已经形成结论，投票不可更改")
        self._require_not_frozen_any(
            achievement_code, achievement.package_code, achievement.program_code
        )
        program = self._require_program(achievement.program_code)
        self._require_active_member(person_code, party_code, achievement.program_code)
        votes = self.tech_votes.setdefault(key, {})
        if party_code in votes:
            raise ConflictError(f"机构 {party_code} 已对该版本投过票")

        event = self._record(
            TechnicalReviewVoted(
                seq=0,
                achievement_code=achievement_code,
                version=achievement.version,
                party_code=party_code,
                person_code=person_code,
                approved=approved,
                comment=comment,
            )
        )
        # 所有参与机构各投一票后形成唯一验收结论：一致同意才通过。
        if len(votes) == len(program.parties):
            accepted = all(vote[1] for vote in votes.values())
            self._record(
                TechnicalAcceptanceRecorded(
                    seq=0,
                    achievement_code=achievement_code,
                    version=achievement.version,
                    accepted=accepted,
                    note="全部参与机构已投票，一致同意" if accepted else "存在不赞成票，验收不通过",
                )
            )
        return event

    # ------------------------------------------------------------ 权利确认

    def rights_vote(
        self,
        milestone_code: str,
        achievement_code: str,
        party_code: str,
        person_code: str,
        approved: bool,
        comment: str = "",
    ) -> RightsVoteCast:
        self._require_text(milestone_code, "里程碑代码")
        achievement = self._require_version(achievement_code)
        if milestone_code in self.conclusions:
            raise ConflictError(f"里程碑 {milestone_code} 已形成唯一结论，不得重新表决")
        if achievement.state not in (
            AchievementState.TECHNICALLY_ACCEPTED,
            AchievementState.RIGHTS_REJECTED,
        ):
            raise DomainError("只有技术验收通过的成果才能进行知识产权与权利确认")
        self._require_not_frozen_any(
            achievement_code, achievement.package_code, achievement.program_code
        )
        self._require_active_member(person_code, party_code, achievement.program_code)
        program = self._require_program(achievement.program_code)

        pending = self.rights_votes.setdefault(milestone_code, {})
        bound = self.milestone_target.get(milestone_code)
        if bound is None:
            self.milestone_target[milestone_code] = (achievement_code, achievement.version)
        elif bound != (achievement_code, achievement.version):
            raise ConflictError("同一里程碑只能针对同一成果版本表决，结论只能有一个")
        if party_code in pending:
            raise ConflictError(f"机构 {party_code} 已对该里程碑投过票")

        event = self._record(
            RightsVoteCast(
                seq=0,
                achievement_code=achievement_code,
                version=achievement.version,
                milestone_code=milestone_code,
                party_code=party_code,
                person_code=person_code,
                approved=approved,
                comment=comment,
            )
        )
        if len(pending) == len(program.parties):
            votes_tuple = tuple(
                (pc, vote[0], vote[1], vote[2])
                for pc, vote in sorted(pending.items())
            )
            unanimous = all(vote[1] for vote in pending.values())
            self._record(
                MilestoneConclusionRecorded(
                    seq=0,
                    milestone_code=milestone_code,
                    achievement_code=achievement_code,
                    version=achievement.version,
                    approved=unanimous,
                    votes=votes_tuple,
                )
            )
        return event

    def publish(self, achievement_code: str) -> AchievementPublished:
        achievement = self._require_version(achievement_code)
        self._require_not_frozen_any(
            achievement_code, achievement.package_code, achievement.program_code
        )
        if achievement.state is AchievementState.PUBLISHED:
            raise ConflictError("成果已发布")
        if achievement.state is not AchievementState.RIGHTS_CONFIRMED:
            raise DomainError("成果须同时通过技术验收与权利确认后才能发布")
        return self._record(
            AchievementPublished(seq=0, achievement_code=achievement_code, version=achievement.version)
        )

    # ---------------------------------------------------------------- 授权

    def request_access(
        self, person_code: str, achievement_code: str, version: int | None = None
    ) -> AccessDecision:
        """每次访问都按当前状态重新判定，并留存审计事件。"""
        achievement = self._require_version(achievement_code, version)

        allowed, reason = self._evaluate(person_code, achievement)
        grant_code: str | None = None
        if allowed:
            grant_code = (
                f"GRANT-{achievement_code}-v{achievement.version}-{person_code}-{self.store.next_seq()}"
            )
            self._record(
                GrantIssued(
                    seq=0,
                    grant_code=grant_code,
                    achievement_code=achievement_code,
                    version=achievement.version,
                    person_code=person_code,
                    party_code=self.persons[person_code].party_code,
                    confidentiality=achievement.confidentiality,
                    scope_type=achievement.scope.scope_type,
                    reason="访问条件全部满足",
                )
            )
        self._record(
            AccessChecked(
                seq=0,
                person_code=person_code,
                achievement_code=achievement_code,
                version=achievement.version,
                allowed=allowed,
                reason=reason,
                grant_code=grant_code,
            )
        )
        return AccessDecision(
            allowed=allowed,
            person_code=person_code,
            achievement_code=achievement_code,
            version=achievement.version,
            reason=reason,
            grant_code=grant_code,
        )

    def _evaluate(self, person_code: str, achievement: Achievement) -> tuple[bool, str]:
        freeze = self._freeze_reason(achievement.code, achievement.package_code, achievement.program_code)
        if freeze is not None:
            return False, freeze
        if achievement.state is AchievementState.SUPERSEDED:
            return False, (
                "成果已被新版本替换，历史授权仅作使用依据留存："
                f"{self._superseding(achievement.code, achievement.version)}"
            )
        if achievement.state is not AchievementState.PUBLISHED:
            return False, f"成果尚未发布（当前状态：{achievement.state.value}）"
        if person_code not in self.persons:
            return False, "人员不在联合实验室名册"
        person = self.persons[person_code]
        if not person.active:
            return False, "人员已离组，访问随即关闭"
        program = self.programs[achievement.program_code]
        if person.party_code not in program.parties:
            return False, "人员所属机构已退出该合作计划"
        if achievement.program_code in person.conflict_programs:
            return False, "人员在该合作计划存在未解除的利益冲突"
        if not achievement.scope.covers(person.party_code):
            return False, "成果可使用范围不包含人员所属机构"
        return True, "符合全部访问条件"

    # ---------------------------------------------------------------- 争议

    def freeze(self, target_code: str, reason: str) -> DisputeFrozen:
        self._require_text(target_code, "争议对象代码")
        if not reason.strip():
            raise DomainError("争议冻结必须说明原因")
        if target_code in self.frozen:
            raise ConflictError(f"对象 {target_code} 已处于争议冻结中")
        if not self._target_exists(target_code):
            raise NotFound(f"争议对象 {target_code} 不存在（可为合作计划、工作包或成果代码）")
        return self._record(DisputeFrozen(seq=0, target_code=target_code, reason=reason))

    def resolve_dispute(self, target_code: str, resolution: str) -> DisputeResolved:
        if target_code not in self.frozen:
            raise ConflictError(f"对象 {target_code} 未处于争议冻结中")
        return self._record(
            DisputeResolved(seq=0, target_code=target_code, resolution=resolution)
        )

    # ---------------------------------------------------------------- 查询

    def get_achievement(self, code: str, version: int | None = None) -> Achievement:
        return self._require_version(code, version)

    def get_program_packages(self, program_code: str) -> list[WorkPackagePlan]:
        self._require_program(program_code)
        return [pkg for pkg in self.packages.values() if pkg.program_code == program_code]

    def get_grants(self, achievement_code: str | None = None) -> list[Grant]:
        if achievement_code is None:
            return list(self.grants)
        return [grant for grant in self.grants if grant.achievement_code == achievement_code]

    def get_conclusion(self, milestone_code: str) -> MilestoneConclusion:
        if milestone_code not in self.conclusions:
            raise NotFound(f"里程碑 {milestone_code} 尚无结论")
        return self.conclusions[milestone_code]

    def event_history(self) -> list[object]:
        """返回不可变事件全历史，供管理方审计。"""
        return self.store.events()

    def trace(self, achievement_code: str) -> list[dict[str, object]]:
        """追踪一项成果从立项、评审到授权使用的完整过程。"""
        latest = self._require_version(achievement_code)
        package_code = latest.package_code
        program_code = latest.program_code
        timeline: list[dict[str, object]] = []
        for event in self.store.events():
            kind = type(event).__name__
            entry: dict[str, object] | None = None
            if kind == "ProgramCreated" and event.program_code == program_code:  # type: ignore[attr-defined]
                entry = {
                    "seq": event.seq,
                    "stage": "立项",
                    "event": kind,
                    "detail": {
                        "program_code": event.program_code,
                        "name": event.name,
                        "objectives": event.objectives,
                        "parties": list(event.party_codes),
                        "budget": event.budget,
                    },
                }
            elif kind == "WorkPackageCreated" and event.package_code == package_code:  # type: ignore[attr-defined]
                entry = {
                    "seq": event.seq,
                    "stage": "立项",
                    "event": kind,
                    "detail": {
                        "package_code": event.package_code,
                        "program_code": event.program_code,
                        "name": event.name,
                        "lead_party": event.lead_party,
                        "dependencies": sorted(event.dependencies),
                        "budget": event.budget,
                        "responsibilities": [list(item) for item in event.responsibilities],
                        "deliverables": list(event.deliverables),
                    },
                }
            elif kind == "AchievementSubmitted" and event.code == achievement_code:  # type: ignore[attr-defined]
                entry = {
                    "seq": event.seq,
                    "stage": _STAGE_BY_EVENT.get(kind, "其他"),
                    "event": kind,
                    "detail": _event_detail(event),
                }
            elif hasattr(event, "achievement_code") and event.achievement_code == achievement_code:  # type: ignore[attr-defined]
                entry = {
                    "seq": event.seq,
                    "stage": _STAGE_BY_EVENT.get(kind, "其他"),
                    "event": kind,
                    "detail": _event_detail(event),
                }
            elif kind in ("DisputeFrozen", "DisputeResolved") and event.target_code in (  # type: ignore[attr-defined]
                achievement_code,
                package_code,
                program_code,
            ):
                entry = {
                    "seq": event.seq,
                    "stage": "争议",
                    "event": kind,
                    "detail": _event_detail(event),
                }
            if entry is not None:
                timeline.append(entry)
        return timeline

    # ---------------------------------------------------------------- 内部

    def _record(self, event: object) -> object:
        stored = self.store.append(event)  # type: ignore[arg-type]
        self._apply(stored)
        return stored

    def _apply(self, event: object) -> None:
        kind = type(event).__name__
        if kind == "LabCreated":
            self.lab_code = event.lab_code
            self.lab_name = event.name
        elif kind == "PartyRegistered":
            self.parties[event.code] = Party(code=event.code, name=event.name, kind=event.kind)
        elif kind == "ProgramCreated":
            self.programs[event.program_code] = _ProgramState(
                event.name, event.objectives, set(event.party_codes), event.budget
            )
        elif kind == "PartyJoinedProgram":
            self.programs[event.program_code].parties.add(event.party_code)
        elif kind == "PartyWithdrewFromProgram":
            self.programs[event.program_code].parties.discard(event.party_code)
        elif kind == "PersonJoined":
            self.persons[event.person_code] = _PersonState(event.party_code, event.name)
        elif kind == "PersonLeft":
            self.persons[event.person_code].active = False
        elif kind == "ConflictDeclared":
            self.persons[event.person_code].conflict_programs.add(event.program_code)
        elif kind == "ConflictCleared":
            self.persons[event.person_code].conflict_programs.discard(event.program_code)
        elif kind == "WorkPackageCreated":
            self.packages[event.package_code] = WorkPackagePlan(
                package_code=event.package_code,
                program_code=event.program_code,
                name=event.name,
                lead_party=event.lead_party,
                dependencies=event.dependencies,
                budget=event.budget,
                responsibilities=event.responsibilities,
                deliverables=event.deliverables,
            )
        elif kind == "AchievementSubmitted":
            versions = self.achievements.setdefault(event.code, {})
            versions[event.version] = Achievement(
                code=event.code,
                version=event.version,
                package_code=event.package_code,
                program_code=event.program_code,
                title=event.title,
                contributions=event.contributions,
                confidentiality=event.confidentiality,
                ip_terms=event.ip_terms,
                scope=event.scope,
                submitted_by=event.submitted_by,
                supersedes=event.supersedes,
            )
            if event.supersedes is not None:
                old = versions[event.supersedes]
                versions[event.supersedes] = _with_state(old, AchievementState.SUPERSEDED)
        elif kind == "TechnicalReviewVoted":
            self.tech_votes.setdefault(
                (event.achievement_code, event.version), {}
            ).setdefault(event.party_code, (event.person_code, event.approved, event.comment))
        elif kind == "TechnicalAcceptanceRecorded":
            self.tech_decided.add((event.achievement_code, event.version))
            if event.accepted:
                old = self.achievements[event.achievement_code][event.version]
                self.achievements[event.achievement_code][event.version] = _with_state(
                    old, AchievementState.TECHNICALLY_ACCEPTED
                )
        elif kind == "RightsVoteCast":
            self.rights_votes.setdefault(event.milestone_code, {}).setdefault(
                event.party_code, (event.person_code, event.approved, event.comment)
            )
            self.milestone_target[event.milestone_code] = (
                event.achievement_code,
                event.version,
            )
        elif kind == "MilestoneConclusionRecorded":
            self.conclusions[event.milestone_code] = MilestoneConclusion(
                milestone_code=event.milestone_code,
                achievement_code=event.achievement_code,
                version=event.version,
                approved=event.approved,
                votes=event.votes,
                at_seq=event.seq,
            )
            old = self.achievements[event.achievement_code][event.version]
            self.achievements[event.achievement_code][event.version] = _with_state(
                old,
                AchievementState.RIGHTS_CONFIRMED if event.approved else AchievementState.RIGHTS_REJECTED,
            )
        elif kind == "AchievementPublished":
            old = self.achievements[event.achievement_code][event.version]
            self.achievements[event.achievement_code][event.version] = _with_state(
                old, AchievementState.PUBLISHED
            )
        elif kind == "GrantIssued":
            self.grants.append(
                Grant(
                    grant_code=event.grant_code,
                    achievement_code=event.achievement_code,
                    version=event.version,
                    person_code=event.person_code,
                    party_code=event.party_code,
                    confidentiality=event.confidentiality,
                    scope_type=event.scope_type,
                    reason=event.reason,
                    at_seq=event.seq,
                )
            )
        elif kind == "DisputeFrozen":
            self.frozen[event.target_code] = Freeze(
                target_code=event.target_code, reason=event.reason, at_seq=event.seq
            )
        elif kind == "DisputeResolved":
            self.frozen.pop(event.target_code, None)
        # AccessChecked 是纯审计事件，不改变投影状态。

    def _normalize_contribution(self, value: Contribution | dict[str, object]) -> Contribution:
        if isinstance(value, Contribution):
            return value
        person_code = value.get("person_code")
        return Contribution(
            party_code=str(value["party_code"]),
            person_code=None if person_code is None else str(person_code),
            kind=ContributionKind(value["kind"]),
            description=str(value.get("description", "")),
        )

    def _normalize_scope(self, value: UsageScope | dict[str, object]) -> UsageScope:
        if isinstance(value, UsageScope):
            return value
        return UsageScope(
            scope_type=ScopeType(value["scope_type"]),
            allowed_parties=frozenset(value.get("allowed_parties", ())),  # type: ignore[arg-type]
        )

    def _require_active_member(
        self, person_code: str, party_code: str, program_code: str
    ) -> _PersonState:
        person = self._require_person(person_code)
        if person.party_code != party_code:
            raise DomainError("投票人不属于所代表的机构")
        if not person.active:
            raise DomainError("投票人已离组")
        if party_code not in self.programs[program_code].parties:
            raise DomainError("机构已退出该合作计划")
        if program_code in person.conflict_programs:
            raise DomainError("投票人存在未解除的利益冲突，应当回避")
        return person

    def _superseding(self, code: str, version: int) -> str:
        for ver, achievement in self.achievements[code].items():
            if achievement.supersedes == version:
                return f"v{ver}"
        return "新版本"

    def _freeze_reason(self, *codes: str) -> str | None:
        for code in codes:
            freeze = self.frozen.get(code)
            if freeze is not None:
                return f"争议冻结中：{freeze.reason}"
        return None

    def _target_exists(self, code: str) -> bool:
        return code in self.programs or code in self.packages or code in self.achievements

    def _require_not_frozen_any(self, *codes: str) -> None:
        reason = self._freeze_reason(*codes)
        if reason is not None:
            raise ConflictError(reason)

    def _require_lab(self) -> None:
        if self.lab_code is None:
            raise DomainError("请先建立联合实验室")

    def _require_text(self, value: str, label: str) -> None:
        if not value or not value.strip():
            raise DomainError(f"{label}不能为空")

    def _require_program(self, code: str) -> _ProgramState:
        program = self.programs.get(code)
        if program is None:
            raise NotFound(f"合作计划 {code} 不存在")
        return program

    def _require_package(self, code: str) -> WorkPackagePlan:
        package = self.packages.get(code)
        if package is None:
            raise NotFound(f"工作包 {code} 不存在")
        return package

    def _require_person(self, code: str) -> _PersonState:
        person = self.persons.get(code)
        if person is None:
            raise NotFound(f"人员 {code} 不存在")
        return person

    def _require_version(self, code: str, version: int | None = None) -> Achievement:
        versions = self.achievements.get(code)
        if not versions:
            raise NotFound(f"成果 {code} 不存在")
        if version is None:
            return versions[max(versions)]
        achievement = versions.get(version)
        if achievement is None:
            raise NotFound(f"成果 {code} 版本 v{version} 不存在")
        return achievement


_STAGE_BY_EVENT = {
    "AchievementSubmitted": "提交",
    "TechnicalReviewVoted": "技术验收",
    "TechnicalAcceptanceRecorded": "技术验收",
    "RightsVoteCast": "权利确认",
    "MilestoneConclusionRecorded": "权利确认",
    "AchievementPublished": "发布",
    "GrantIssued": "授权使用",
    "AccessChecked": "授权使用",
}


def _with_state(achievement: Achievement, state: AchievementState) -> Achievement:
    return Achievement(
        code=achievement.code,
        version=achievement.version,
        package_code=achievement.package_code,
        program_code=achievement.program_code,
        title=achievement.title,
        contributions=achievement.contributions,
        confidentiality=achievement.confidentiality,
        ip_terms=achievement.ip_terms,
        scope=achievement.scope,
        submitted_by=achievement.submitted_by,
        supersedes=achievement.supersedes,
        state=state,
    )


def _event_detail(event: object) -> dict[str, object]:
    detail: dict[str, object] = {}
    for item in fields(event):
        if item.name == "seq":
            continue
        detail[item.name] = to_jsonable(getattr(event, item.name))
    return detail
