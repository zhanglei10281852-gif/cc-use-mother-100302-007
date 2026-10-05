"""校企联合实验室成果协同的领域模型与取值约定。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PartyKind(str, Enum):
    """参与机构类型：学校、整机厂、应用单位或其他。"""

    SCHOOL = "school"
    MANUFACTURER = "manufacturer"
    APPLICANT = "applicant"
    OTHER = "other"


class ContributionKind(str, Enum):
    """成果贡献来源类型：算法、关节模组、场景数据或其他。"""

    ALGORITHM = "algorithm"
    JOINT_MODULE = "joint_module"
    SCENE_DATA = "scene_data"
    OTHER = "other"


class Confidentiality(str, Enum):
    """保密级别。"""

    PUBLIC = "public"            # 公开
    INTERNAL = "internal"        # 内部
    CONFIDENTIAL = "confidential"  # 保密


class ScopeType(str, Enum):
    """可使用范围：全体计划参与方，或仅指定机构。"""

    ALL_PARTICIPANTS = "all_participants"
    NAMED_PARTIES = "named_parties"


class AchievementState(str, Enum):
    """成果生命周期状态。"""

    SUBMITTED = "submitted"                       # 已提交
    TECHNICALLY_ACCEPTED = "technically_accepted"  # 技术验收通过
    RIGHTS_CONFIRMED = "rights_confirmed"          # 知识产权与权利确认通过
    RIGHTS_REJECTED = "rights_rejected"            # 权利确认未形成同意结论
    PUBLISHED = "published"                        # 已发布授权
    SUPERSEDED = "superseded"                      # 被新版本替换


@dataclass(frozen=True, slots=True)
class Party:
    """参与联合实验室的机构。"""

    code: str
    name: str
    kind: PartyKind


@dataclass(frozen=True, slots=True)
class Contribution:
    """单项贡献来源：某机构成员贡献了算法、关节模组或场景数据等。"""

    party_code: str
    person_code: str | None
    kind: ContributionKind
    description: str = ""


@dataclass(frozen=True, slots=True)
class UsageScope:
    """成果可使用范围。"""

    scope_type: ScopeType
    allowed_parties: frozenset[str] = frozenset()

    def covers(self, party_code: str) -> bool:
        if self.scope_type is ScopeType.ALL_PARTICIPANTS:
            return True
        return party_code in self.allowed_parties


@dataclass(frozen=True, slots=True)
class WorkPackagePlan:
    """工作包：目标、依赖、预算、参与方责任与交付物清单。"""

    package_code: str
    program_code: str
    name: str
    lead_party: str
    dependencies: frozenset[str] = frozenset()
    budget: float = 0.0
    responsibilities: tuple[tuple[str, str], ...] = ()
    deliverables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Achievement:
    """提交的成果版本及其保密、知识产权与使用范围约定。"""

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
    supersedes: int | None = None
    state: AchievementState = AchievementState.SUBMITTED


@dataclass(frozen=True, slots=True)
class MilestoneConclusion:
    """跨机构里程碑（权利确认）只能形成的唯一一个结论。"""

    milestone_code: str
    achievement_code: str
    version: int
    approved: bool
    votes: tuple[tuple[str, str, bool, str], ...]  # (party_code, person_code, approved, comment)
    at_seq: int


@dataclass(frozen=True, slots=True)
class Grant:
    """授权使用记录：不可变的历史使用依据。"""

    grant_code: str
    achievement_code: str
    version: int
    person_code: str
    party_code: str
    confidentiality: Confidentiality
    scope_type: ScopeType
    reason: str
    at_seq: int


@dataclass(frozen=True, slots=True)
class Freeze:
    """争议冻结。"""

    target_code: str
    reason: str
    at_seq: int


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """访问判定结果。"""

    allowed: bool
    person_code: str
    achievement_code: str
    version: int
    reason: str
    grant_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "person_code": self.person_code,
            "achievement_code": self.achievement_code,
            "version": self.version,
            "reason": self.reason,
            "grant_code": self.grant_code,
        }
