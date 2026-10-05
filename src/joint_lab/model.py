"""校企联合实验室成果协同的领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# 保密级别：1=内部，2=机密，3=秘密；成员密级不低于成果密级才可访问
MIN_CLEARANCE = 1
MAX_CLEARANCE = 3
CONFIDENTIALITY_LABELS = {1: "内部", 2: "机密", 3: "秘密"}

PARTY_KINDS = ("university", "enterprise", "application_unit", "other")
PARTY_KIND_LABELS = {
    "university": "高校/科研院所",
    "enterprise": "企业",
    "application_unit": "应用单位",
    "other": "其他",
}

# 成果状态机：submitted -> tech_accepted -> rights_confirmed -> published
# 验收或确认不通过进入 rejected；发布后可能 frozen（争议冻结）或 replaced（被替换）
STATE_SUBMITTED = "submitted"
STATE_TECH_ACCEPTED = "tech_accepted"
STATE_RIGHTS_CONFIRMED = "rights_confirmed"
STATE_PUBLISHED = "published"
STATE_REJECTED = "rejected"
STATE_FROZEN = "frozen"
STATE_REPLACED = "replaced"

ACHIEVEMENT_STATE_LABELS = {
    STATE_SUBMITTED: "已提交",
    STATE_TECH_ACCEPTED: "技术验收通过",
    STATE_RIGHTS_CONFIRMED: "权利确认完成",
    STATE_PUBLISHED: "已发布",
    STATE_REJECTED: "已驳回",
    STATE_FROZEN: "争议冻结",
    STATE_REPLACED: "已被替换",
}

# 里程碑结论：跨机构确认只能形成其中一个，且一旦形成不可更改
MILESTONE_ACHIEVED = "achieved"
MILESTONE_NOT_ACHIEVED = "not_achieved"
MILESTONE_CONCLUSION_LABELS = {
    MILESTONE_ACHIEVED: "通过",
    MILESTONE_NOT_ACHIEVED: "未通过",
}


@dataclass
class Party:
    """参与机构（学校、整机厂、应用单位等）。"""

    party_id: str
    name: str
    kind: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Party":
        return cls(party_id=data["party_id"], name=data["name"], kind=data["kind"])


@dataclass
class Member:
    """机构成员，密级决定可访问的成果保密级别。"""

    member_id: str
    party_id: str
    name: str
    clearance: int = MIN_CLEARANCE
    status: str = "active"  # active | withdrawn
    withdrawn_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Member":
        return cls(
            member_id=data["member_id"],
            party_id=data["party_id"],
            name=data["name"],
            clearance=int(data.get("clearance", MIN_CLEARANCE)),
            status=data.get("status", "active"),
            withdrawn_at=data.get("withdrawn_at"),
        )


@dataclass
class ConflictOfInterest:
    """成员申报的利益冲突，可指向某项成果或某个机构。"""

    coi_id: str
    member_id: str
    achievement_id: str | None
    party_id: str | None
    reason: str
    active: bool = True
    declared_at: str = ""
    lifted_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConflictOfInterest":
        return cls(
            coi_id=data["coi_id"],
            member_id=data["member_id"],
            achievement_id=data.get("achievement_id"),
            party_id=data.get("party_id"),
            reason=data.get("reason", ""),
            active=bool(data.get("active", True)),
            declared_at=data.get("declared_at", ""),
            lifted_at=data.get("lifted_at"),
        )


@dataclass
class PlanParty:
    """计划参与方及其责任与预算份额。"""

    party_id: str
    responsibility: str
    budget_share: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PlanParty":
        return cls(
            party_id=data["party_id"],
            responsibility=data["responsibility"],
            budget_share=float(data.get("budget_share", 0.0)),
        )


@dataclass
class CooperationPlan:
    """合作计划：组织目标、总预算与参与方责任。"""

    plan_id: str
    title: str
    goals: list[str]
    total_budget: float
    parties: dict[str, PlanParty]
    state: str = "active"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeliverableSpec:
    """工作包承诺的交付物。"""

    deliverable_id: str
    name: str
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DeliverableSpec":
        return cls(
            deliverable_id=data["deliverable_id"],
            name=data["name"],
            description=data.get("description", ""),
        )


@dataclass
class WorkPackage:
    """工作包：目标、依赖、预算、参与方责任与交付物。"""

    wp_id: str
    plan_id: str
    title: str
    objectives: list[str]
    depends_on: list[str]
    budget: float
    responsibilities: dict[str, str]  # party_id -> 责任说明
    deliverables: dict[str, DeliverableSpec]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MilestoneVote:
    """单个机构对里程碑的确认意见。"""

    approve: bool
    note: str
    at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Milestone:
    """跨机构确认的里程碑，结论一旦形成即不可更改。"""

    milestone_id: str
    wp_id: str
    name: str
    required_parties: list[str]
    votes: dict[str, MilestoneVote] = field(default_factory=dict)
    conclusion: str | None = None
    concluded_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Contribution:
    """成果的一条贡献来源。"""

    party_id: str
    kind: str
    description: str
    member_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Contribution":
        return cls(
            party_id=data["party_id"],
            kind=data["kind"],
            description=data["description"],
            member_id=data.get("member_id"),
        )


@dataclass
class IprAgreement:
    """知识产权约定：归属方与许可方式。"""

    owner_party_ids: list[str]
    license: str
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IprAgreement":
        return cls(
            owner_party_ids=list(data["owner_party_ids"]),
            license=data["license"],
            notes=data.get("notes", ""),
        )


@dataclass
class UsageScope:
    """可使用范围：plan 表示计划内全部机构，parties 表示指定机构。"""

    kind: str  # "plan" | "parties"
    party_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UsageScope":
        return cls(kind=data["kind"], party_ids=list(data.get("party_ids", [])))


@dataclass
class Achievement:
    """成果：提交时记录贡献来源、保密级别、知识产权约定与可使用范围。"""

    achievement_id: str
    wp_id: str
    title: str
    summary: str
    contributions: list[Contribution]
    confidentiality: int
    ipr: IprAgreement
    usage_scope: UsageScope
    fulfills: list[str]
    state: str = STATE_SUBMITTED
    frozen_from: str | None = None
    replaced_by: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AccessDecision:
    """一次访问评估的结论，作为历史使用依据写入账本。"""

    member_id: str
    achievement_id: str
    granted: bool
    reasons: tuple[str, ...]
    at: str

    def to_dict(self) -> dict:
        return {
            "member_id": self.member_id,
            "achievement_id": self.achievement_id,
            "granted": self.granted,
            "reasons": list(self.reasons),
            "at": self.at,
        }
