"""校企联合实验室成果协同服务的领域行为测试。"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from joint_lab import (
    MILESTONE_ACHIEVED,
    MILESTONE_NOT_ACHIEVED,
    REASON_CLEARANCE,
    REASON_COI,
    REASON_FROZEN,
    REASON_MEMBER_WITHDRAWN,
    REASON_NOT_PUBLISHED,
    REASON_REPLACED,
    REASON_SCOPE,
    CollaborationService,
    ConflictError,
    NotFoundError,
    StateError,
    ValidationError,
)
from joint_lab.service import (
    ACCESS_CHECKED,
    ACHIEVEMENT_PUBLISHED,
    ACHIEVEMENT_RIGHTS_REVIEWED,
    ACHIEVEMENT_SUBMITTED,
    ACHIEVEMENT_TECH_REVIEWED,
    MILESTONE_CONCLUDED,
)


class FakeClock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> str:
        self.moment += timedelta(seconds=1)
        return self.moment.isoformat()


def make_service() -> CollaborationService:
    """搭建题目场景：学校、整机厂、应用单位三方共建。"""
    service = CollaborationService(clock=FakeClock())
    service.register_party(party_id="univ", name="天津大学研究院", kind="university")
    service.register_party(party_id="oem", name="关节模组整机厂", kind="enterprise")
    service.register_party(party_id="app", name="场景应用单位", kind="application_unit")
    service.create_plan(
        plan_id="plan-1",
        title="校企联合实验室共建计划",
        goals=["形成可复用成果"],
        total_budget=1000.0,
        parties=[
            {"party_id": "univ", "responsibility": "算法研发", "budget_share": 400.0},
            {"party_id": "oem", "responsibility": "关节模组", "budget_share": 400.0},
            {"party_id": "app", "responsibility": "场景数据", "budget_share": 200.0},
        ],
    )
    service.add_work_package(
        plan_id="plan-1",
        wp_id="wp-1",
        title="感知与控制",
        objectives=["完成控制算法库"],
        budget=600.0,
        responsibilities={"univ": "算法设计", "oem": "模组接口"},
        deliverables=[{"deliverable_id": "d-1", "name": "控制算法库"}],
    )
    service.add_work_package(
        plan_id="plan-1",
        wp_id="wp-2",
        title="场景验证",
        objectives=["完成场景验证"],
        depends_on=["wp-1"],
        budget=300.0,
        responsibilities={"app": "场景数据"},
    )
    service.add_milestone(wp_id="wp-1", milestone_id="ms-1", name="中期检查")
    service.add_member(member_id="m-univ", party_id="univ", name="算法工程师", clearance=3)
    service.add_member(member_id="m-oem", party_id="oem", name="模组工程师", clearance=2)
    service.add_member(member_id="m-app", party_id="app", name="数据专员", clearance=1)
    return service


def submit_achievement(service: CollaborationService, achievement_id: str = "ach-1", **overrides) -> None:
    spec = {
        "achievement_id": achievement_id,
        "wp_id": "wp-1",
        "title": "机器人关节控制算法",
        "summary": "算法、关节模组与场景数据共建成果",
        "contributions": [
            {"party_id": "univ", "kind": "算法", "description": "控制律"},
            {"party_id": "oem", "kind": "关节模组", "description": "硬件接口"},
            {"party_id": "app", "kind": "场景数据", "description": "验证数据集"},
        ],
        "confidentiality": 2,
        "ipr": {"owner_party_ids": ["univ", "oem"], "license": "共建方共有", "notes": ""},
        "usage_scope": {"kind": "plan", "party_ids": []},
        "fulfills": ["d-1"],
    }
    spec.update(overrides)
    service.submit_achievement(**spec)


def publish_achievement(service: CollaborationService, achievement_id: str = "ach-1", **overrides) -> None:
    submit_achievement(service, achievement_id, **overrides)
    service.record_technical_acceptance(achievement_id=achievement_id, passed=True)
    service.confirm_rights(achievement_id=achievement_id, confirmed=True)
    service.publish_achievement(achievement_id=achievement_id)


class PlanAndWorkPackageTests(unittest.TestCase):
    def test_plan_organizes_goals_budget_and_responsibilities(self) -> None:
        service = make_service()
        plan = service.plans["plan-1"]
        self.assertEqual(plan.goals, ["形成可复用成果"])
        self.assertEqual(plan.total_budget, 1000.0)
        self.assertEqual(plan.parties["univ"].responsibility, "算法研发")
        wp = service.work_packages["wp-2"]
        self.assertEqual(wp.depends_on, ["wp-1"])
        self.assertEqual(wp.budget, 300.0)
        self.assertEqual(service.work_packages["wp-1"].deliverables["d-1"].name, "控制算法库")

    def test_budget_overflow_is_rejected(self) -> None:
        service = make_service()
        with self.assertRaises(ValidationError):
            service.add_work_package(
                plan_id="plan-1",
                wp_id="wp-3",
                title="超预算工作包",
                objectives=["目标"],
                budget=100.01,
                responsibilities={"univ": "责任"},
            )
        service.add_work_package(
            plan_id="plan-1",
            wp_id="wp-3",
            title="剩余预算内工作包",
            objectives=["目标"],
            budget=100.0,
            responsibilities={"univ": "责任"},
        )

    def test_party_share_overflow_is_rejected(self) -> None:
        service = CollaborationService(clock=FakeClock())
        service.register_party(party_id="univ", name="高校", kind="university")
        with self.assertRaises(ValidationError):
            service.create_plan(
                plan_id="plan-x",
                title="计划",
                goals=["目标"],
                total_budget=100.0,
                parties=[{"party_id": "univ", "responsibility": "责任", "budget_share": 100.01}],
            )

    def test_work_package_validates_dependencies_and_parties(self) -> None:
        service = make_service()
        with self.assertRaises(NotFoundError):
            service.add_work_package(
                plan_id="plan-1",
                wp_id="wp-9",
                title="未知依赖",
                objectives=["目标"],
                depends_on=["wp-404"],
                budget=50.0,
                responsibilities={"univ": "责任"},
            )
        with self.assertRaises(ConflictError):
            service.add_work_package(
                plan_id="plan-1",
                wp_id="wp-1",
                title="重复标识",
                objectives=["目标"],
                budget=50.0,
                responsibilities={"univ": "责任"},
            )
        with self.assertRaises(ValidationError):
            service.add_work_package(
                plan_id="plan-1",
                wp_id="wp-10",
                title="自我依赖",
                objectives=["目标"],
                depends_on=["wp-10"],
                budget=50.0,
                responsibilities={"univ": "责任"},
            )
        with self.assertRaises(ValidationError):
            service.add_work_package(
                plan_id="plan-1",
                wp_id="wp-11",
                title="陌生责任方",
                objectives=["目标"],
                budget=50.0,
                responsibilities={"stranger": "责任"},
            )

    def test_duplicate_ids_are_rejected(self) -> None:
        service = make_service()
        with self.assertRaises(ConflictError):
            service.register_party(party_id="univ", name="重复", kind="university")
        with self.assertRaises(ConflictError):
            service.add_member(member_id="m-univ", party_id="univ", name="重复")
        with self.assertRaises(ConflictError):
            service.create_plan(
                plan_id="plan-1",
                title="重复",
                goals=["目标"],
                total_budget=1.0,
                parties=[{"party_id": "univ", "responsibility": "责任", "budget_share": 1.0}],
            )
        with self.assertRaises(ConflictError):
            service.add_milestone(wp_id="wp-1", milestone_id="ms-1", name="重复")
        submit_achievement(service)
        with self.assertRaises(ConflictError):
            submit_achievement(service)


class MilestoneTests(unittest.TestCase):
    def test_cross_institution_confirmation_forms_single_conclusion(self) -> None:
        service = make_service()
        self.assertIsNone(service.confirm_milestone(milestone_id="ms-1", party_id="univ", approve=True))
        conclusion = service.confirm_milestone(milestone_id="ms-1", party_id="oem", approve=True)
        self.assertEqual(conclusion, MILESTONE_ACHIEVED)
        # 结论形成后任何进一步确认都被拒绝，账本中只有一条结论事件
        with self.assertRaises(StateError):
            service.confirm_milestone(milestone_id="ms-1", party_id="univ", approve=False)
        concluded = [e for e in service.ledger if e.type == MILESTONE_CONCLUDED]
        self.assertEqual(len(concluded), 1)
        self.assertEqual(concluded[0].data["conclusion"], MILESTONE_ACHIEVED)

    def test_any_rejection_yields_not_achieved(self) -> None:
        service = make_service()
        service.add_milestone(wp_id="wp-1", milestone_id="ms-2", name="终验")
        service.confirm_milestone(milestone_id="ms-2", party_id="univ", approve=True)
        conclusion = service.confirm_milestone(milestone_id="ms-2", party_id="oem", approve=False, note="接口未达标")
        self.assertEqual(conclusion, MILESTONE_NOT_ACHIEVED)

    def test_only_required_parties_can_vote_and_only_once(self) -> None:
        service = make_service()
        with self.assertRaises(ValidationError):
            service.confirm_milestone(milestone_id="ms-1", party_id="app", approve=True)
        service.confirm_milestone(milestone_id="ms-1", party_id="univ", approve=True)
        with self.assertRaises(ConflictError):
            service.confirm_milestone(milestone_id="ms-1", party_id="univ", approve=True)

    def test_milestone_completion_does_not_open_access(self) -> None:
        """里程碑完成不等于成果开放：成果仍需验收、权利确认与发布。"""
        service = make_service()
        service.confirm_milestone(milestone_id="ms-1", party_id="univ", approve=True)
        service.confirm_milestone(milestone_id="ms-1", party_id="oem", approve=True)
        submit_achievement(service)
        decision = service.check_access(member_id="m-oem", achievement_id="ach-1")
        self.assertFalse(decision.granted)
        self.assertIn(REASON_NOT_PUBLISHED, decision.reasons)


class AchievementLifecycleTests(unittest.TestCase):
    def test_full_publication_flow_and_trace(self) -> None:
        service = make_service()
        publish_achievement(service)
        view = service.achievement_view("ach-1")
        self.assertEqual(view["state"], "published")
        self.assertEqual(view["confidentiality_label"], "机密")
        self.assertEqual(set(view["eligible_parties"]), {"univ", "oem", "app"})

        trace = service.trace_achievement("ach-1")
        types = [event["type"] for event in trace]
        self.assertEqual(
            types,
            [ACHIEVEMENT_SUBMITTED, ACHIEVEMENT_TECH_REVIEWED, ACHIEVEMENT_RIGHTS_REVIEWED, ACHIEVEMENT_PUBLISHED],
        )
        self.assertTrue(service.verify())

    def test_review_gates_are_enforced(self) -> None:
        service = make_service()
        submit_achievement(service)
        with self.assertRaises(StateError):
            service.confirm_rights(achievement_id="ach-1", confirmed=True)
        with self.assertRaises(StateError):
            service.publish_achievement(achievement_id="ach-1")
        service.record_technical_acceptance(achievement_id="ach-1", passed=True)
        with self.assertRaises(StateError):
            service.record_technical_acceptance(achievement_id="ach-1", passed=True)
        service.confirm_rights(achievement_id="ach-1", confirmed=True)
        service.publish_achievement(achievement_id="ach-1")
        with self.assertRaises(StateError):
            service.publish_achievement(achievement_id="ach-1")

    def test_failed_review_rejects_achievement(self) -> None:
        service = make_service()
        submit_achievement(service)
        service.record_technical_acceptance(achievement_id="ach-1", passed=False, notes="指标未达标")
        self.assertEqual(service.achievement_view("ach-1")["state"], "rejected")
        with self.assertRaises(StateError):
            service.publish_achievement(achievement_id="ach-1")

        service2 = make_service()
        submit_achievement(service2)
        service2.record_technical_acceptance(achievement_id="ach-1", passed=True)
        service2.confirm_rights(achievement_id="ach-1", confirmed=False, notes="权属存疑")
        self.assertEqual(service2.achievement_view("ach-1")["state"], "rejected")

    def test_submission_validation(self) -> None:
        service = make_service()
        with self.assertRaises(ValidationError):
            submit_achievement(service, "ach-bad-1", confidentiality=4)
        with self.assertRaises(ValidationError):
            submit_achievement(
                service, "ach-bad-2", contributions=[{"party_id": "stranger", "kind": "算法", "description": "x"}]
            )
        with self.assertRaises(ValidationError):
            submit_achievement(
                service, "ach-bad-3", ipr={"owner_party_ids": ["stranger"], "license": "许可"}
            )
        with self.assertRaises(ValidationError):
            submit_achievement(
                service, "ach-bad-4", usage_scope={"kind": "parties", "party_ids": ["stranger"]}
            )
        with self.assertRaises(ValidationError):
            submit_achievement(service, "ach-bad-5", fulfills=["d-404"])
        with self.assertRaises(ValidationError):
            submit_achievement(service, "ach-bad-6", title="  ")


class AccessControlTests(unittest.TestCase):
    def test_eligible_member_is_granted_and_recorded(self) -> None:
        service = make_service()
        publish_achievement(service)
        decision = service.check_access(member_id="m-oem", achievement_id="ach-1", purpose="集成使用")
        self.assertTrue(decision.granted)
        self.assertEqual(decision.reasons, ())
        history = service.access_history(member_id="m-oem")
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]["granted"])

    def test_clearance_and_scope_are_enforced(self) -> None:
        service = make_service()
        publish_achievement(service)
        low = service.check_access(member_id="m-app", achievement_id="ach-1")
        self.assertFalse(low.granted)
        self.assertIn(REASON_CLEARANCE, low.reasons)

        publish_achievement(
            service, "ach-2", usage_scope={"kind": "parties", "party_ids": ["univ"]}, fulfills=[]
        )
        outsider = service.check_access(member_id="m-oem", achievement_id="ach-2")
        self.assertFalse(outsider.granted)
        self.assertIn(REASON_SCOPE, outsider.reasons)
        insider = service.check_access(member_id="m-univ", achievement_id="ach-2")
        self.assertTrue(insider.granted)

    def test_member_join_and_withdraw_change_access_promptly(self) -> None:
        service = make_service()
        publish_achievement(service)
        # 新成员加入后立即按规则获得访问权
        service.add_member(member_id="m-oem-2", party_id="oem", name="新入职工程师", clearance=2)
        joined = service.check_access(member_id="m-oem-2", achievement_id="ach-1")
        self.assertTrue(joined.granted)
        # 退出前的授权记录保留，退出后的访问立即被拒绝
        before = service.check_access(member_id="m-oem", achievement_id="ach-1")
        self.assertTrue(before.granted)
        service.withdraw_member(member_id="m-oem")
        after = service.check_access(member_id="m-oem", achievement_id="ach-1")
        self.assertFalse(after.granted)
        self.assertIn(REASON_MEMBER_WITHDRAWN, after.reasons)
        history = service.access_history(member_id="m-oem")
        self.assertEqual([record["granted"] for record in history], [True, False])
        with self.assertRaises(StateError):
            service.withdraw_member(member_id="m-oem")

    def test_conflict_of_interest_blocks_and_lift_restores(self) -> None:
        service = make_service()
        publish_achievement(service)
        # 机构级冲突：与贡献方存在利益冲突的成员被拦截
        service.declare_conflict(coi_id="coi-1", member_id="m-univ", party_id="oem", reason="竞品合作")
        blocked = service.check_access(member_id="m-univ", achievement_id="ach-1")
        self.assertFalse(blocked.granted)
        self.assertIn(REASON_COI, blocked.reasons)
        service.lift_conflict(coi_id="coi-1")
        restored = service.check_access(member_id="m-univ", achievement_id="ach-1")
        self.assertTrue(restored.granted)
        # 成果级冲突
        service.declare_conflict(coi_id="coi-2", member_id="m-oem", achievement_id="ach-1")
        blocked2 = service.check_access(member_id="m-oem", achievement_id="ach-1")
        self.assertIn(REASON_COI, blocked2.reasons)
        with self.assertRaises(ValidationError):
            service.declare_conflict(coi_id="coi-3", member_id="m-oem")

    def test_replacement_redirects_future_access(self) -> None:
        service = make_service()
        publish_achievement(service)
        granted_before = service.check_access(member_id="m-univ", achievement_id="ach-1")
        self.assertTrue(granted_before.granted)
        publish_achievement(service, "ach-2", title="控制算法 2.0")
        service.replace_achievement(old_achievement_id="ach-1", new_achievement_id="ach-2")
        old_decision = service.check_access(member_id="m-univ", achievement_id="ach-1")
        self.assertFalse(old_decision.granted)
        self.assertIn(REASON_REPLACED, old_decision.reasons)
        new_decision = service.check_access(member_id="m-univ", achievement_id="ach-2")
        self.assertTrue(new_decision.granted)
        # 历史使用依据未被破坏
        history = service.access_history(achievement_id="ach-1")
        self.assertEqual([record["granted"] for record in history], [True, False])
        # 被替换的成果进入终态
        with self.assertRaises(StateError):
            service.freeze_achievement(achievement_id="ach-1", reason="争议")
        with self.assertRaises(StateError):
            service.replace_achievement(old_achievement_id="ach-1", new_achievement_id="ach-2")

    def test_replacement_requires_published_replacement(self) -> None:
        service = make_service()
        publish_achievement(service)
        submit_achievement(service, "ach-2")
        with self.assertRaises(StateError):
            service.replace_achievement(old_achievement_id="ach-1", new_achievement_id="ach-2")

    def test_freeze_and_resolve_change_access_promptly(self) -> None:
        service = make_service()
        publish_achievement(service)
        service.freeze_achievement(achievement_id="ach-1", reason="权属争议", operator="项目秘书")
        frozen = service.check_access(member_id="m-univ", achievement_id="ach-1")
        self.assertFalse(frozen.granted)
        self.assertIn(REASON_FROZEN, frozen.reasons)
        service.resolve_dispute(achievement_id="ach-1", resolution="达成补充协议")
        restored = service.check_access(member_id="m-univ", achievement_id="ach-1")
        self.assertTrue(restored.granted)
        with self.assertRaises(StateError):
            service.resolve_dispute(achievement_id="ach-1")

    def test_unpublished_achievement_cannot_be_frozen(self) -> None:
        service = make_service()
        submit_achievement(service)
        with self.assertRaises(StateError):
            service.freeze_achievement(achievement_id="ach-1", reason="争议")


class TraceAndPersistenceTests(unittest.TestCase):
    def test_trace_covers_lifecycle_to_authorized_use(self) -> None:
        service = make_service()
        publish_achievement(service)
        service.check_access(member_id="m-univ", achievement_id="ach-1", purpose="授权使用")
        trace = service.trace_achievement("ach-1")
        types = [event["type"] for event in trace]
        self.assertEqual(
            types,
            [
                ACHIEVEMENT_SUBMITTED,
                ACHIEVEMENT_TECH_REVIEWED,
                ACHIEVEMENT_RIGHTS_REVIEWED,
                ACHIEVEMENT_PUBLISHED,
                ACCESS_CHECKED,
            ],
        )
        self.assertTrue(trace[-1]["data"]["granted"])

    def test_trace_includes_replacement_and_freeze(self) -> None:
        service = make_service()
        publish_achievement(service)
        publish_achievement(service, "ach-2")
        service.replace_achievement(old_achievement_id="ach-1", new_achievement_id="ach-2")
        old_trace = [event["type"] for event in service.trace_achievement("ach-1")]
        new_trace = [event["type"] for event in service.trace_achievement("ach-2")]
        self.assertIn("ACHIEVEMENT_REPLACED", old_trace)
        self.assertIn("ACHIEVEMENT_REPLACED", new_trace)

    def test_save_and_replay_restores_state(self) -> None:
        service = make_service()
        publish_achievement(service)
        service.check_access(member_id="m-univ", achievement_id="ach-1")
        service.withdraw_member(member_id="m-oem")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            service.save(path)
            restored = CollaborationService.load(path, clock=FakeClock())
        self.assertEqual(service.snapshot(), restored.snapshot())
        self.assertTrue(restored.verify())
        # 重放后的服务可以继续推进流程
        decision = restored.check_access(member_id="m-oem", achievement_id="ach-1")
        self.assertFalse(decision.granted)
        self.assertIn(REASON_MEMBER_WITHDRAWN, decision.reasons)

    def test_store_file_is_valid_json(self) -> None:
        service = make_service()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            service.save(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["events"]), len(service.ledger))


if __name__ == "__main__":
    unittest.main()
