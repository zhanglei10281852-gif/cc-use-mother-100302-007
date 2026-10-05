"""校企联合实验室成果协同服务。

以合作计划与工作包组织目标、依赖、预算、参与方责任与交付物；
成果提交时记录贡献来源、保密级别、知识产权约定与可使用范围，
经过技术验收与权利确认后才发布给符合条件的成员。
成员加入、退出、利益冲突、成果替换与争议冻结会即时改变后续访问结论，
所有历史访问依据保存在追加式事件账本中，不被改写。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import ConflictError, NotFoundError, StateError, ValidationError
from .events import Event, Ledger
from .model import (
    ACHIEVEMENT_STATE_LABELS,
    CONFIDENTIALITY_LABELS,
    MAX_CLEARANCE,
    MILESTONE_ACHIEVED,
    MILESTONE_NOT_ACHIEVED,
    MIN_CLEARANCE,
    PARTY_KINDS,
    STATE_FROZEN,
    STATE_PUBLISHED,
    STATE_REJECTED,
    STATE_REPLACED,
    STATE_RIGHTS_CONFIRMED,
    STATE_SUBMITTED,
    STATE_TECH_ACCEPTED,
    AccessDecision,
    Achievement,
    ConflictOfInterest,
    Contribution,
    CooperationPlan,
    DeliverableSpec,
    IprAgreement,
    Member,
    Milestone,
    MilestoneVote,
    Party,
    PlanParty,
    UsageScope,
    WorkPackage,
)

# 事件类型
PARTY_REGISTERED = "PARTY_REGISTERED"
MEMBER_ADDED = "MEMBER_ADDED"
MEMBER_WITHDRAWN = "MEMBER_WITHDRAWN"
CONFLICT_DECLARED = "CONFLICT_DECLARED"
CONFLICT_LIFTED = "CONFLICT_LIFTED"
PLAN_CREATED = "PLAN_CREATED"
WORK_PACKAGE_ADDED = "WORK_PACKAGE_ADDED"
MILESTONE_ADDED = "MILESTONE_ADDED"
MILESTONE_VOTED = "MILESTONE_VOTED"
MILESTONE_CONCLUDED = "MILESTONE_CONCLUDED"
ACHIEVEMENT_SUBMITTED = "ACHIEVEMENT_SUBMITTED"
ACHIEVEMENT_TECH_REVIEWED = "ACHIEVEMENT_TECH_REVIEWED"
ACHIEVEMENT_RIGHTS_REVIEWED = "ACHIEVEMENT_RIGHTS_REVIEWED"
ACHIEVEMENT_PUBLISHED = "ACHIEVEMENT_PUBLISHED"
ACHIEVEMENT_FROZEN = "ACHIEVEMENT_FROZEN"
ACHIEVEMENT_DISPUTE_RESOLVED = "ACHIEVEMENT_DISPUTE_RESOLVED"
ACHIEVEMENT_REPLACED = "ACHIEVEMENT_REPLACED"
ACCESS_CHECKED = "ACCESS_CHECKED"

# 访问拒绝原因（稳定常量，供审计与测试引用）
REASON_NOT_PUBLISHED = "成果尚未发布"
REASON_FROZEN = "成果处于争议冻结中"
REASON_REPLACED = "成果已被新版本替换"
REASON_MEMBER_WITHDRAWN = "成员已退出"
REASON_CLEARANCE = "成员保密等级不足"
REASON_SCOPE = "所在机构不在成果可使用范围内"
REASON_COI = "成员存在未解除的利益冲突"

_EPS = 1e-6

Clock = Callable[[], str]


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field}不能为空")
    return value.strip()


def _require_text_list(values: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if values is None:
        if allow_empty:
            return []
        raise ValidationError(f"{field}不能为空")
    if not isinstance(values, (list, tuple)):
        raise ValidationError(f"{field}必须是字符串列表")
    result = [_require_text(item, field) for item in values]
    if not allow_empty and not result:
        raise ValidationError(f"{field}不能为空")
    return result


def _money(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field}必须是数字")
    amount = round(float(value), 2)
    if amount < 0:
        raise ValidationError(f"{field}不能为负数")
    return amount


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field}必须是布尔值")
    return value


def _require_clearance(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field}必须是 {MIN_CLEARANCE} 到 {MAX_CLEARANCE} 的整数")
    if not MIN_CLEARANCE <= value <= MAX_CLEARANCE:
        raise ValidationError(f"{field}必须是 {MIN_CLEARANCE} 到 {MAX_CLEARANCE} 的整数")
    return value


class CollaborationService:
    """校企联合实验室成果协同的核心服务：命令、查询与访问评估。"""

    def __init__(self, clock: Clock | None = None, ledger: Ledger | None = None) -> None:
        self._clock: Clock = clock or _default_clock
        self.ledger: Ledger = ledger if ledger is not None else Ledger()
        self.parties: dict[str, Party] = {}
        self.members: dict[str, Member] = {}
        self.conflicts: dict[str, ConflictOfInterest] = {}
        self.plans: dict[str, CooperationPlan] = {}
        self.work_packages: dict[str, WorkPackage] = {}
        self.milestones: dict[str, Milestone] = {}
        self.achievements: dict[str, Achievement] = {}
        for event in self.ledger:
            self._apply(event)

    # ------------------------------------------------------------------
    # 事件写入与状态重放
    # ------------------------------------------------------------------

    def _emit(self, type_: str, data: dict) -> Event:
        event = self.ledger.append(type_, data, self._clock())
        self._apply(event)
        return event

    def _apply(self, event: Event) -> None:
        type_, data = event.type, event.data
        if type_ == PARTY_REGISTERED:
            self.parties[data["party_id"]] = Party.from_dict(data)
        elif type_ == MEMBER_ADDED:
            self.members[data["member_id"]] = Member.from_dict(data)
        elif type_ == MEMBER_WITHDRAWN:
            member = self.members[data["member_id"]]
            member.status = "withdrawn"
            member.withdrawn_at = event.at
        elif type_ == CONFLICT_DECLARED:
            self.conflicts[data["coi_id"]] = ConflictOfInterest(
                coi_id=data["coi_id"],
                member_id=data["member_id"],
                achievement_id=data.get("achievement_id"),
                party_id=data.get("party_id"),
                reason=data.get("reason", ""),
                active=True,
                declared_at=event.at,
            )
        elif type_ == CONFLICT_LIFTED:
            conflict = self.conflicts[data["coi_id"]]
            conflict.active = False
            conflict.lifted_at = event.at
        elif type_ == PLAN_CREATED:
            self.plans[data["plan_id"]] = CooperationPlan(
                plan_id=data["plan_id"],
                title=data["title"],
                goals=list(data["goals"]),
                total_budget=float(data["total_budget"]),
                parties={p["party_id"]: PlanParty.from_dict(p) for p in data["parties"]},
            )
        elif type_ == WORK_PACKAGE_ADDED:
            self.work_packages[data["wp_id"]] = WorkPackage(
                wp_id=data["wp_id"],
                plan_id=data["plan_id"],
                title=data["title"],
                objectives=list(data["objectives"]),
                depends_on=list(data["depends_on"]),
                budget=float(data["budget"]),
                responsibilities=dict(data["responsibilities"]),
                deliverables={d["deliverable_id"]: DeliverableSpec.from_dict(d) for d in data["deliverables"]},
            )
        elif type_ == MILESTONE_ADDED:
            self.milestones[data["milestone_id"]] = Milestone(
                milestone_id=data["milestone_id"],
                wp_id=data["wp_id"],
                name=data["name"],
                required_parties=list(data["required_parties"]),
            )
        elif type_ == MILESTONE_VOTED:
            milestone = self.milestones[data["milestone_id"]]
            milestone.votes[data["party_id"]] = MilestoneVote(
                approve=bool(data["approve"]), note=data.get("note", ""), at=event.at
            )
        elif type_ == MILESTONE_CONCLUDED:
            milestone = self.milestones[data["milestone_id"]]
            milestone.conclusion = data["conclusion"]
            milestone.concluded_at = event.at
        elif type_ == ACHIEVEMENT_SUBMITTED:
            self.achievements[data["achievement_id"]] = Achievement(
                achievement_id=data["achievement_id"],
                wp_id=data["wp_id"],
                title=data["title"],
                summary=data["summary"],
                contributions=[Contribution.from_dict(c) for c in data["contributions"]],
                confidentiality=int(data["confidentiality"]),
                ipr=IprAgreement.from_dict(data["ipr"]),
                usage_scope=UsageScope.from_dict(data["usage_scope"]),
                fulfills=list(data["fulfills"]),
                state=STATE_SUBMITTED,
            )
        elif type_ == ACHIEVEMENT_TECH_REVIEWED:
            achievement = self.achievements[data["achievement_id"]]
            achievement.state = STATE_TECH_ACCEPTED if data["passed"] else STATE_REJECTED
        elif type_ == ACHIEVEMENT_RIGHTS_REVIEWED:
            achievement = self.achievements[data["achievement_id"]]
            achievement.state = STATE_RIGHTS_CONFIRMED if data["confirmed"] else STATE_REJECTED
        elif type_ == ACHIEVEMENT_PUBLISHED:
            self.achievements[data["achievement_id"]].state = STATE_PUBLISHED
        elif type_ == ACHIEVEMENT_FROZEN:
            achievement = self.achievements[data["achievement_id"]]
            achievement.frozen_from = data["previous_state"]
            achievement.state = STATE_FROZEN
        elif type_ == ACHIEVEMENT_DISPUTE_RESOLVED:
            achievement = self.achievements[data["achievement_id"]]
            achievement.state = data["restored_state"]
            achievement.frozen_from = None
        elif type_ == ACHIEVEMENT_REPLACED:
            achievement = self.achievements[data["achievement_id"]]
            achievement.state = STATE_REPLACED
            achievement.replaced_by = data["new_achievement_id"]
        elif type_ == ACCESS_CHECKED:
            pass  # 仅审计留痕，不改变领域状态
        else:  # pragma: no cover - 防御未知事件
            raise ValueError(f"未知事件类型 {type_}")

    # ------------------------------------------------------------------
    # 查找辅助
    # ------------------------------------------------------------------

    def _party(self, party_id: Any) -> Party:
        party_id = _require_text(party_id, "机构标识")
        party = self.parties.get(party_id)
        if party is None:
            raise NotFoundError(f"机构 {party_id} 不存在")
        return party

    def _member(self, member_id: Any) -> Member:
        member_id = _require_text(member_id, "成员标识")
        member = self.members.get(member_id)
        if member is None:
            raise NotFoundError(f"成员 {member_id} 不存在")
        return member

    def _plan(self, plan_id: Any) -> CooperationPlan:
        plan_id = _require_text(plan_id, "计划标识")
        plan = self.plans.get(plan_id)
        if plan is None:
            raise NotFoundError(f"合作计划 {plan_id} 不存在")
        return plan

    def _work_package(self, wp_id: Any) -> WorkPackage:
        wp_id = _require_text(wp_id, "工作包标识")
        work_package = self.work_packages.get(wp_id)
        if work_package is None:
            raise NotFoundError(f"工作包 {wp_id} 不存在")
        return work_package

    def _milestone(self, milestone_id: Any) -> Milestone:
        milestone_id = _require_text(milestone_id, "里程碑标识")
        milestone = self.milestones.get(milestone_id)
        if milestone is None:
            raise NotFoundError(f"里程碑 {milestone_id} 不存在")
        return milestone

    def _achievement(self, achievement_id: Any) -> Achievement:
        achievement_id = _require_text(achievement_id, "成果标识")
        achievement = self.achievements.get(achievement_id)
        if achievement is None:
            raise NotFoundError(f"成果 {achievement_id} 不存在")
        return achievement

    # ------------------------------------------------------------------
    # 机构与成员
    # ------------------------------------------------------------------

    def register_party(self, *, party_id: str, name: str, kind: str) -> None:
        party_id = _require_text(party_id, "机构标识")
        name = _require_text(name, "机构名称")
        kind = _require_text(kind, "机构类型")
        if kind not in PARTY_KINDS:
            raise ValidationError(f"机构类型必须是 {list(PARTY_KINDS)} 之一")
        if party_id in self.parties:
            raise ConflictError(f"机构 {party_id} 已存在")
        self._emit(PARTY_REGISTERED, {"party_id": party_id, "name": name, "kind": kind})

    def add_member(self, *, member_id: str, party_id: str, name: str, clearance: int = MIN_CLEARANCE) -> None:
        member_id = _require_text(member_id, "成员标识")
        party = self._party(party_id)
        name = _require_text(name, "成员姓名")
        clearance = _require_clearance(clearance, "成员密级")
        if member_id in self.members:
            raise ConflictError(f"成员 {member_id} 已存在")
        self._emit(
            MEMBER_ADDED,
            {"member_id": member_id, "party_id": party.party_id, "name": name, "clearance": clearance},
        )

    def withdraw_member(self, *, member_id: str) -> None:
        member = self._member(member_id)
        if member.status != "active":
            raise StateError(f"成员 {member.member_id} 已退出")
        self._emit(MEMBER_WITHDRAWN, {"member_id": member.member_id, "party_id": member.party_id})

    def declare_conflict(
        self,
        *,
        coi_id: str,
        member_id: str,
        achievement_id: str | None = None,
        party_id: str | None = None,
        reason: str = "",
    ) -> None:
        coi_id = _require_text(coi_id, "利益冲突标识")
        member = self._member(member_id)
        if bool(achievement_id) == bool(party_id):
            raise ValidationError("利益冲突必须且只能指向一个成果或一个机构")
        if achievement_id is not None:
            self._achievement(achievement_id)
        if party_id is not None:
            self._party(party_id)
        if coi_id in self.conflicts:
            raise ConflictError(f"利益冲突 {coi_id} 已存在")
        self._emit(
            CONFLICT_DECLARED,
            {
                "coi_id": coi_id,
                "member_id": member.member_id,
                "achievement_id": achievement_id,
                "party_id": party_id,
                "reason": reason or "",
            },
        )

    def lift_conflict(self, *, coi_id: str) -> None:
        coi_id = _require_text(coi_id, "利益冲突标识")
        conflict = self.conflicts.get(coi_id)
        if conflict is None:
            raise NotFoundError(f"利益冲突 {coi_id} 不存在")
        if not conflict.active:
            raise StateError(f"利益冲突 {coi_id} 已解除")
        self._emit(CONFLICT_LIFTED, {"coi_id": conflict.coi_id})

    # ------------------------------------------------------------------
    # 合作计划、工作包与里程碑
    # ------------------------------------------------------------------

    def create_plan(
        self,
        *,
        plan_id: str,
        title: str,
        goals: list[str],
        total_budget: float,
        parties: list[dict],
    ) -> None:
        plan_id = _require_text(plan_id, "计划标识")
        title = _require_text(title, "计划名称")
        goals = _require_text_list(goals, "计划目标", allow_empty=False)
        total_budget = _money(total_budget, "计划预算")
        if not isinstance(parties, (list, tuple)) or not parties:
            raise ValidationError("合作计划至少需要一个参与方")
        plan_parties: dict[str, dict] = {}
        for entry in parties:
            if not isinstance(entry, dict):
                raise ValidationError("参与方必须是对象")
            pid = self._party(entry.get("party_id")).party_id
            if pid in plan_parties:
                raise ValidationError(f"参与方 {pid} 在计划中重复")
            plan_parties[pid] = {
                "party_id": pid,
                "responsibility": _require_text(entry.get("responsibility"), f"参与方 {pid} 的责任"),
                "budget_share": _money(entry.get("budget_share", 0), f"参与方 {pid} 的预算份额"),
            }
        if sum(p["budget_share"] for p in plan_parties.values()) > total_budget + _EPS:
            raise ValidationError("参与方预算份额之和不能超过计划总预算")
        if plan_id in self.plans:
            raise ConflictError(f"合作计划 {plan_id} 已存在")
        self._emit(
            PLAN_CREATED,
            {
                "plan_id": plan_id,
                "title": title,
                "goals": goals,
                "total_budget": total_budget,
                "parties": list(plan_parties.values()),
            },
        )

    def add_work_package(
        self,
        *,
        plan_id: str,
        wp_id: str,
        title: str,
        objectives: list[str],
        depends_on: list[str] | None = None,
        budget: float = 0,
        responsibilities: dict[str, str] | None = None,
        deliverables: list[dict] | None = None,
    ) -> None:
        plan = self._plan(plan_id)
        wp_id = _require_text(wp_id, "工作包标识")
        title = _require_text(title, "工作包名称")
        objectives = _require_text_list(objectives, "工作包目标", allow_empty=False)
        depends_on = _require_text_list(depends_on, "依赖工作包")
        budget = _money(budget, "工作包预算")
        if wp_id in self.work_packages:
            raise ConflictError(f"工作包 {wp_id} 已存在")
        if wp_id in depends_on:
            raise ValidationError("工作包不能依赖自身")
        for dep_id in depends_on:
            dep = self.work_packages.get(dep_id)
            if dep is None:
                raise NotFoundError(f"依赖的工作包 {dep_id} 不存在")
            if dep.plan_id != plan.plan_id:
                raise ValidationError("工作包只能依赖同一计划下的其他工作包")
        used_budget = sum(wp.budget for wp in self.work_packages.values() if wp.plan_id == plan.plan_id)
        if used_budget + budget > plan.total_budget + _EPS:
            raise ValidationError("工作包预算超出计划剩余预算")
        if not isinstance(responsibilities, dict) or not responsibilities:
            raise ValidationError("工作包至少需要一个责任方")
        clean_responsibilities: dict[str, str] = {}
        for pid, responsibility in responsibilities.items():
            if pid not in plan.parties:
                raise ValidationError(f"责任方 {pid} 未参与计划 {plan.plan_id}")
            clean_responsibilities[pid] = _require_text(responsibility, f"责任方 {pid} 的责任")
        deliverable_map: dict[str, dict] = {}
        for entry in deliverables or []:
            if not isinstance(entry, dict):
                raise ValidationError("交付物必须是对象")
            deliverable_id = _require_text(entry.get("deliverable_id"), "交付物标识")
            if deliverable_id in deliverable_map:
                raise ValidationError(f"交付物 {deliverable_id} 在工作包中重复")
            deliverable_map[deliverable_id] = {
                "deliverable_id": deliverable_id,
                "name": _require_text(entry.get("name"), f"交付物 {deliverable_id} 的名称"),
                "description": entry.get("description") or "",
            }
        self._emit(
            WORK_PACKAGE_ADDED,
            {
                "plan_id": plan.plan_id,
                "wp_id": wp_id,
                "title": title,
                "objectives": objectives,
                "depends_on": depends_on,
                "budget": budget,
                "responsibilities": clean_responsibilities,
                "deliverables": list(deliverable_map.values()),
            },
        )

    def add_milestone(
        self,
        *,
        wp_id: str,
        milestone_id: str,
        name: str,
        required_parties: list[str] | None = None,
    ) -> None:
        work_package = self._work_package(wp_id)
        milestone_id = _require_text(milestone_id, "里程碑标识")
        name = _require_text(name, "里程碑名称")
        if milestone_id in self.milestones:
            raise ConflictError(f"里程碑 {milestone_id} 已存在")
        plan = self.plans[work_package.plan_id]
        if required_parties is None:
            required = sorted(work_package.responsibilities)
        else:
            required = sorted(set(_require_text_list(required_parties, "里程碑确认方", allow_empty=False)))
        for pid in required:
            if pid not in plan.parties:
                raise ValidationError(f"确认方 {pid} 未参与计划 {plan.plan_id}")
        self._emit(
            MILESTONE_ADDED,
            {
                "milestone_id": milestone_id,
                "wp_id": work_package.wp_id,
                "name": name,
                "required_parties": required,
            },
        )

    def confirm_milestone(self, *, milestone_id: str, party_id: str, approve: bool, note: str = "") -> str | None:
        """跨机构确认里程碑；全部确认方投票后形成唯一结论，结论形成后不可再投票。"""
        milestone = self._milestone(milestone_id)
        party_id = _require_text(party_id, "确认方标识")
        approve = _require_bool(approve, "确认意见")
        if milestone.conclusion is not None:
            raise StateError(f"里程碑 {milestone_id} 已形成结论，不能重复确认")
        if party_id not in milestone.required_parties:
            raise ValidationError(f"机构 {party_id} 不是该里程碑的确认方")
        if party_id in milestone.votes:
            raise ConflictError(f"机构 {party_id} 已提交过确认")
        self._emit(
            MILESTONE_VOTED,
            {"milestone_id": milestone_id, "party_id": party_id, "approve": approve, "note": note or ""},
        )
        conclusion = None
        if set(milestone.votes) == set(milestone.required_parties):
            conclusion = (
                MILESTONE_ACHIEVED if all(vote.approve for vote in milestone.votes.values()) else MILESTONE_NOT_ACHIEVED
            )
            self._emit(
                MILESTONE_CONCLUDED,
                {
                    "milestone_id": milestone_id,
                    "wp_id": milestone.wp_id,
                    "conclusion": conclusion,
                    "votes": {pid: vote.approve for pid, vote in sorted(milestone.votes.items())},
                },
            )
        return conclusion

    # ------------------------------------------------------------------
    # 成果提交、评审与发布
    # ------------------------------------------------------------------

    def submit_achievement(
        self,
        *,
        achievement_id: str,
        wp_id: str,
        title: str,
        summary: str,
        contributions: list[dict],
        confidentiality: int,
        ipr: dict,
        usage_scope: dict,
        fulfills: list[str] | None = None,
    ) -> None:
        achievement_id = _require_text(achievement_id, "成果标识")
        work_package = self._work_package(wp_id)
        plan = self.plans[work_package.plan_id]
        title = _require_text(title, "成果名称")
        summary = _require_text(summary, "成果摘要")
        if achievement_id in self.achievements:
            raise ConflictError(f"成果 {achievement_id} 已存在")

        if not isinstance(contributions, (list, tuple)) or not contributions:
            raise ValidationError("成果必须记录至少一条贡献来源")
        clean_contributions: list[dict] = []
        for entry in contributions:
            if not isinstance(entry, dict):
                raise ValidationError("贡献来源必须是对象")
            pid = _require_text(entry.get("party_id"), "贡献方标识")
            if pid not in plan.parties:
                raise ValidationError(f"贡献方 {pid} 未参与计划 {plan.plan_id}")
            kind = _require_text(entry.get("kind"), "贡献类型")
            description = _require_text(entry.get("description"), "贡献说明")
            member_id = entry.get("member_id")
            if member_id is not None:
                member = self._member(member_id)
                if member.party_id != pid:
                    raise ValidationError(f"贡献成员 {member_id} 不属于贡献方 {pid}")
            clean_contributions.append(
                {"party_id": pid, "kind": kind, "description": description, "member_id": member_id}
            )

        confidentiality = _require_clearance(confidentiality, "成果保密级别")

        if not isinstance(ipr, dict):
            raise ValidationError("知识产权约定不能为空")
        owners = sorted(set(_require_text_list(ipr.get("owner_party_ids"), "知识产权归属方", allow_empty=False)))
        for pid in owners:
            if pid not in plan.parties:
                raise ValidationError(f"知识产权归属方 {pid} 未参与计划 {plan.plan_id}")
        license_text = _require_text(ipr.get("license"), "知识产权许可方式")
        ipr_notes = ipr.get("notes") or ""

        if not isinstance(usage_scope, dict):
            raise ValidationError("可使用范围不能为空")
        scope_kind = usage_scope.get("kind")
        if scope_kind not in ("plan", "parties"):
            raise ValidationError("可使用范围类型必须是 plan 或 parties")
        scope_parties: list[str] = []
        if scope_kind == "parties":
            scope_parties = sorted(set(_require_text_list(usage_scope.get("party_ids"), "可使用范围机构", allow_empty=False)))
            for pid in scope_parties:
                if pid not in plan.parties:
                    raise ValidationError(f"可使用范围机构 {pid} 未参与计划 {plan.plan_id}")

        fulfills_clean = _require_text_list(fulfills, "交付物标识")
        for deliverable_id in fulfills_clean:
            if deliverable_id not in work_package.deliverables:
                raise ValidationError(f"交付物 {deliverable_id} 不属于工作包 {work_package.wp_id}")

        self._emit(
            ACHIEVEMENT_SUBMITTED,
            {
                "achievement_id": achievement_id,
                "wp_id": work_package.wp_id,
                "title": title,
                "summary": summary,
                "contributions": clean_contributions,
                "confidentiality": confidentiality,
                "ipr": {"owner_party_ids": owners, "license": license_text, "notes": ipr_notes},
                "usage_scope": {"kind": scope_kind, "party_ids": scope_parties},
                "fulfills": fulfills_clean,
            },
        )

    def record_technical_acceptance(
        self, *, achievement_id: str, passed: bool, notes: str = "", reviewer: str = ""
    ) -> None:
        achievement = self._achievement(achievement_id)
        passed = _require_bool(passed, "验收结论")
        if achievement.state != STATE_SUBMITTED:
            raise StateError(
                f"成果当前状态为「{ACHIEVEMENT_STATE_LABELS[achievement.state]}」，不能进行技术验收"
            )
        self._emit(
            ACHIEVEMENT_TECH_REVIEWED,
            {
                "achievement_id": achievement.achievement_id,
                "passed": passed,
                "notes": notes or "",
                "reviewer": reviewer or "",
            },
        )

    def confirm_rights(
        self, *, achievement_id: str, confirmed: bool, notes: str = "", confirmer: str = ""
    ) -> None:
        achievement = self._achievement(achievement_id)
        confirmed = _require_bool(confirmed, "权利确认结论")
        if achievement.state != STATE_TECH_ACCEPTED:
            raise StateError("成果尚未通过技术验收，不能进行权利确认")
        self._emit(
            ACHIEVEMENT_RIGHTS_REVIEWED,
            {
                "achievement_id": achievement.achievement_id,
                "confirmed": confirmed,
                "notes": notes or "",
                "confirmer": confirmer or "",
            },
        )

    def publish_achievement(self, *, achievement_id: str) -> None:
        achievement = self._achievement(achievement_id)
        if achievement.state != STATE_RIGHTS_CONFIRMED:
            raise StateError("成果未完成技术验收与权利确认，不能发布")
        self._emit(ACHIEVEMENT_PUBLISHED, {"achievement_id": achievement.achievement_id, "wp_id": achievement.wp_id})

    def freeze_achievement(self, *, achievement_id: str, reason: str, operator: str = "") -> None:
        achievement = self._achievement(achievement_id)
        reason = _require_text(reason, "冻结原因")
        if achievement.state != STATE_PUBLISHED:
            raise StateError("只有已发布的成果才能进入争议冻结")
        self._emit(
            ACHIEVEMENT_FROZEN,
            {
                "achievement_id": achievement.achievement_id,
                "reason": reason,
                "operator": operator or "",
                "previous_state": achievement.state,
            },
        )

    def resolve_dispute(self, *, achievement_id: str, resolution: str = "") -> None:
        achievement = self._achievement(achievement_id)
        if achievement.state != STATE_FROZEN:
            raise StateError("成果不在争议冻结中")
        self._emit(
            ACHIEVEMENT_DISPUTE_RESOLVED,
            {
                "achievement_id": achievement.achievement_id,
                "resolution": resolution or "",
                "restored_state": achievement.frozen_from or STATE_PUBLISHED,
            },
        )

    def replace_achievement(self, *, old_achievement_id: str, new_achievement_id: str) -> None:
        old = self._achievement(old_achievement_id)
        new = self._achievement(new_achievement_id)
        if old.achievement_id == new.achievement_id:
            raise ValidationError("成果不能替换自身")
        if old.state != STATE_PUBLISHED:
            raise StateError("只有已发布的成果才能被替换")
        if new.state != STATE_PUBLISHED:
            raise StateError("替换成果必须先完成技术验收、权利确认并发布")
        self._emit(
            ACHIEVEMENT_REPLACED,
            {"achievement_id": old.achievement_id, "new_achievement_id": new.achievement_id},
        )

    # ------------------------------------------------------------------
    # 访问评估：每次访问都按当前状态实时评估，结论写入账本作为使用依据
    # ------------------------------------------------------------------

    def check_access(self, *, member_id: str, achievement_id: str, purpose: str = "") -> AccessDecision:
        member = self._member(member_id)
        achievement = self._achievement(achievement_id)
        reasons = self._evaluate_access(member, achievement)
        event = self._emit(
            ACCESS_CHECKED,
            {
                "member_id": member.member_id,
                "achievement_id": achievement.achievement_id,
                "granted": not reasons,
                "reasons": list(reasons),
                "purpose": purpose or "",
            },
        )
        return AccessDecision(
            member_id=member.member_id,
            achievement_id=achievement.achievement_id,
            granted=not reasons,
            reasons=tuple(reasons),
            at=event.at,
        )

    def _evaluate_access(self, member: Member, achievement: Achievement) -> list[str]:
        if achievement.state == STATE_REPLACED:
            return [REASON_REPLACED]
        if achievement.state == STATE_FROZEN:
            return [REASON_FROZEN]
        if achievement.state != STATE_PUBLISHED:
            return [REASON_NOT_PUBLISHED]
        reasons: list[str] = []
        if member.status != "active":
            reasons.append(REASON_MEMBER_WITHDRAWN)
        if member.clearance < achievement.confidentiality:
            reasons.append(REASON_CLEARANCE)
        if member.party_id not in self._scope_parties(achievement):
            reasons.append(REASON_SCOPE)
        contributing_parties = {c.party_id for c in achievement.contributions}
        for conflict in self.conflicts.values():
            if not conflict.active or conflict.member_id != member.member_id:
                continue
            if conflict.achievement_id == achievement.achievement_id or (
                conflict.party_id and conflict.party_id in contributing_parties
            ):
                reasons.append(REASON_COI)
                break
        return reasons

    def _scope_parties(self, achievement: Achievement) -> set[str]:
        if achievement.usage_scope.kind == "parties":
            return set(achievement.usage_scope.party_ids)
        work_package = self.work_packages[achievement.wp_id]
        plan = self.plans[work_package.plan_id]
        return set(plan.parties)

    # ------------------------------------------------------------------
    # 查询与追溯
    # ------------------------------------------------------------------

    def achievement_view(self, achievement_id: str) -> dict:
        achievement = self._achievement(achievement_id)
        work_package = self.work_packages[achievement.wp_id]
        plan = self.plans[work_package.plan_id]
        return {
            **asdict(achievement),
            "state_label": ACHIEVEMENT_STATE_LABELS[achievement.state],
            "confidentiality_label": CONFIDENTIALITY_LABELS[achievement.confidentiality],
            "plan_id": plan.plan_id,
            "eligible_parties": sorted(self._scope_parties(achievement)),
        }

    def milestone_view(self, milestone_id: str) -> dict:
        milestone = self._milestone(milestone_id)
        return {
            **asdict(milestone),
            "pending_parties": [p for p in milestone.required_parties if p not in milestone.votes],
        }

    def trace_achievement(self, achievement_id: str) -> list[dict]:
        """按时间顺序返回一项成果从提交、评审到授权使用的全部事件。"""
        achievement = self._achievement(achievement_id)
        keys = ("achievement_id", "new_achievement_id")
        return [
            {"seq": event.seq, "at": event.at, "type": event.type, "data": event.data}
            for event in self.ledger
            if any(event.data.get(key) == achievement.achievement_id for key in keys)
        ]

    def access_history(self, *, member_id: str | None = None, achievement_id: str | None = None) -> list[dict]:
        """返回访问评估留痕，可按成员或成果过滤；历史记录只增不改。"""
        records = []
        for event in self.ledger:
            if event.type != ACCESS_CHECKED:
                continue
            if member_id is not None and event.data.get("member_id") != member_id:
                continue
            if achievement_id is not None and event.data.get("achievement_id") != achievement_id:
                continue
            records.append({"seq": event.seq, "at": event.at, **event.data})
        return records

    def verify(self) -> bool:
        return self.ledger.verify()

    def snapshot(self) -> dict:
        return {
            "parties": {k: v.to_dict() for k, v in sorted(self.parties.items())},
            "members": {k: v.to_dict() for k, v in sorted(self.members.items())},
            "conflicts": {k: v.to_dict() for k, v in sorted(self.conflicts.items())},
            "plans": {k: v.to_dict() for k, v in sorted(self.plans.items())},
            "work_packages": {k: v.to_dict() for k, v in sorted(self.work_packages.items())},
            "milestones": {k: v.to_dict() for k, v in sorted(self.milestones.items())},
            "achievements": {k: v.to_dict() for k, v in sorted(self.achievements.items())},
            "event_count": len(self.ledger),
        }

    # ------------------------------------------------------------------
    # 持久化：保存/重放事件账本
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        path = Path(path)
        payload = {"version": 1, "events": self.ledger.to_list()}
        tmp_path = path.with_name(path.name + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    @classmethod
    def load(cls, path: str | Path, clock: Clock | None = None) -> "CollaborationService":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        ledger = Ledger.from_list(payload["events"])
        return cls(clock=clock, ledger=ledger)
