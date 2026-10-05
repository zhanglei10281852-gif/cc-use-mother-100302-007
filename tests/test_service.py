"""校企联合实验室成果协同服务测试。"""

from __future__ import annotations

import unittest

from joint_lab import (
    AchievementState,
    ConflictError,
    DomainError,
    JointLabService,
    MemoryEventStore,
    NotFound,
)


CONTRIBS = [
    {"party_code": "TJU", "person_code": "P-TJU", "kind": "algorithm", "description": "算法"},
    {"party_code": "ROBOTCO", "person_code": "P-ROBOT", "kind": "joint_module"},
    {"party_code": "SCENECO", "person_code": "P-SCENE", "kind": "scene_data"},
]
SCOPE_NAMED = {"scope_type": "named_parties", "allowed_parties": ["TJU", "ROBOTCO", "SCENECO"]}
IP_TERMS = "联合发明，三方共有"


class ServiceTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.service = JointLabService(MemoryEventStore())
        self.service.create_lab("LAB-01", "联合实验室")
        self.service.register_party("TJU", "天津大学", "school")
        self.service.register_party("ROBOTCO", "整机厂", "manufacturer")
        self.service.register_party("SCENECO", "应用单位", "applicant")
        self.service.create_program(
            "PRG", "协同计划", "目标", ["TJU", "ROBOTCO", "SCENECO"], budget=100.0
        )
        for code, party, name in [
            ("P-TJU", "TJU", "张"),
            ("P-ROBOT", "ROBOTCO", "李"),
            ("P-SCENE", "SCENECO", "王"),
            ("P-OTHER", "TJU", "赵"),
        ]:
            self.service.add_person(code, party, name)
        self.service.create_work_package(
            "WP1",
            "PRG",
            "工作包一",
            "TJU",
            dependencies=(),
            budget=50.0,
            responsibilities=(("TJU", "算法"), ("ROBOTCO", "模组")),
            deliverables=("算法包",),
        )

    def submit(self, code: str = "ACH1", scope: dict | None = None) -> int:
        event = self.service.submit_achievement(
            code,
            "WP1",
            "成果",
            CONTRIBS,
            "confidential",
            IP_TERMS,
            scope or SCOPE_NAMED,
            submitted_by="P-TJU",
        )
        return event.version

    def approve_tech(self, code: str = "ACH1") -> None:
        for party, person in [("TJU", "P-TJU"), ("ROBOTCO", "P-ROBOT"), ("SCENECO", "P-SCENE")]:
            self.service.technical_review(code, party, person, True)

    def approve_rights(self, code: str = "ACH1", milestone: str = "MS1") -> None:
        for party, person in [("TJU", "P-TJU"), ("ROBOTCO", "P-ROBOT"), ("SCENECO", "P-SCENE")]:
            self.service.rights_vote(milestone, code, party, person, True)

    def publish(self, code: str = "ACH1") -> None:
        self.submit(code)
        self.approve_tech(code)
        self.approve_rights(code)
        self.service.publish(code)


class ProgramAndPackageTests(ServiceTestBase):
    def test_dependency_must_exist_within_program(self) -> None:
        with self.assertRaises(NotFound):
            self.service.create_work_package(
                "WP2", "PRG", "工作包二", "TJU", dependencies=["NOPE"]
            )

    def test_self_dependency_rejected(self) -> None:
        with self.assertRaises(DomainError):
            self.service.create_work_package(
                "WPX", "PRG", "X", "TJU", dependencies=["WPX"]
            )

    def test_real_dependency_accepted(self) -> None:
        self.service.create_work_package("WP2", "PRG", "工作包二", "TJU", dependencies=["WP1"])
        packages = self.service.get_program_packages("PRG")
        self.assertEqual({p.package_code for p in packages}, {"WP1", "WP2"})

    def test_negative_budget_rejected(self) -> None:
        with self.assertRaises(DomainError):
            self.service.create_program("P2", "x", "x", ["TJU"], budget=-1)

    def test_last_party_cannot_withdraw(self) -> None:
        self.service.register_party("SOLO", "单干", "other")
        self.service.create_program("P2", "单计划", "x", ["SOLO"])
        with self.assertRaises(DomainError):
            self.service.withdraw_program("P2", "SOLO")


class AchievementGateTests(ServiceTestBase):
    def test_full_approval_chain_is_required(self) -> None:
        self.submit()
        with self.assertRaises(DomainError):
            self.service.publish("ACH1")

        self.approve_tech()
        with self.assertRaises(DomainError):
            self.service.publish("ACH1")

        self.approve_rights()
        self.service.publish("ACH1")
        self.assertEqual(self.service.get_achievement("ACH1").state, AchievementState.PUBLISHED)

    def test_technical_rejection_blocks_rights(self) -> None:
        self.submit()
        self.service.technical_review("ACH1", "TJU", "P-TJU", True)
        self.service.technical_review("ACH1", "ROBOTCO", "P-ROBOT", False, "不达标")
        self.service.technical_review("ACH1", "SCENECO", "P-SCENE", True)
        self.assertEqual(
            self.service.get_achievement("ACH1").state, AchievementState.SUBMITTED
        )
        with self.assertRaises(DomainError):
            self.approve_rights()

    def test_rights_rejection_can_be_re_voted_with_new_milestone(self) -> None:
        self.submit()
        self.approve_tech()
        self.service.rights_vote("MS1", "ACH1", "TJU", "P-TJU", True)
        self.service.rights_vote("MS1", "ACH1", "ROBOTCO", "P-ROBOT", True)
        self.service.rights_vote("MS1", "ACH1", "SCENECO", "P-SCENE", False)
        self.assertFalse(self.service.get_conclusion("MS1").approved)
        with self.assertRaises(DomainError):
            self.service.publish("ACH1")
        # 被否后不能在同一里程碑上重投，但可以用新里程碑重新确认。
        with self.assertRaises(ConflictError):
            self.service.rights_vote("MS1", "ACH1", "SCENECO", "P-SCENE", True)
        self.approve_rights(milestone="MS2")
        self.service.publish("ACH1")

    def test_milestone_has_single_conclusion(self) -> None:
        self.submit()
        self.approve_tech()
        self.approve_rights()
        conclusion = self.service.get_conclusion("MS1")
        # 结论形成后任何机构都无法再投票或形成第二个结论。
        with self.assertRaises(ConflictError):
            self.service.rights_vote("MS1", "ACH1", "TJU", "P-TJU", False)
        self.assertEqual(len(self.service.event_history() and [
            e for e in self.service.event_history() if type(e).__name__ == "MilestoneConclusionRecorded"
        ]), 1)
        self.assertTrue(conclusion.approved)

    def test_milestone_cannot_switch_target_midway(self) -> None:
        self.submit()
        self.approve_tech()
        self.submit("ACH2")
        self.approve_tech("ACH2")
        self.service.rights_vote("MS1", "ACH1", "TJU", "P-TJU", True)
        with self.assertRaises(ConflictError):
            self.service.rights_vote("MS1", "ACH2", "ROBOTCO", "P-ROBOT", True)

    def test_duplicate_party_vote_rejected(self) -> None:
        self.submit()
        self.service.technical_review("ACH1", "TJU", "P-TJU", True)
        with self.assertRaises(ConflictError):
            self.service.technical_review("ACH1", "TJU", "P-OTHER", False)

    def test_submission_requires_contribution_and_ip(self) -> None:
        with self.assertRaises(DomainError):
            self.service.submit_achievement(
                "EMPTY", "WP1", "t", [], "internal", IP_TERMS,
                {"scope_type": "all_participants"}, "P-TJU",
            )
        with self.assertRaises(DomainError):
            self.service.submit_achievement(
                "NOIP", "WP1", "t", CONTRIBS, "internal", "   ",
                {"scope_type": "all_participants"}, "P-TJU",
            )


class AccessControlTests(ServiceTestBase):
    def test_published_grant_for_eligible_member(self) -> None:
        self.publish()
        decision = self.service.request_access("P-TJU", "ACH1")
        self.assertTrue(decision.allowed)
        self.assertIsNotNone(decision.grant_code)
        self.assertEqual(len(self.service.get_grants("ACH1")), 1)

    def test_unpublished_access_denied_without_grant(self) -> None:
        self.submit()
        decision = self.service.request_access("P-TJU", "ACH1")
        self.assertFalse(decision.allowed)
        self.assertEqual(self.service.get_grants(), [])

    def test_named_scope_excludes_other_party(self) -> None:
        self.service.register_party("EXTRA", "额外机构", "other")
        self.service.create_program("PRG2", "计划二", "x", ["TJU", "EXTRA"])
        self.service.add_person("P-EXTRA", "EXTRA", "钱")
        self.service.create_work_package("WP2", "PRG2", "包二", "TJU")
        self.service.submit_achievement(
            "ACHX", "WP2", "x",
            [{"party_code": "TJU", "person_code": "P-TJU", "kind": "algorithm"}],
            "internal", IP_TERMS,
            {"scope_type": "named_parties", "allowed_parties": ["TJU"]},
            "P-TJU",
        )
        for party, person in [("TJU", "P-TJU"), ("EXTRA", "P-EXTRA")]:
            self.service.technical_review("ACHX", party, person, True)
        for party, person in [("TJU", "P-TJU"), ("EXTRA", "P-EXTRA")]:
            self.service.rights_vote("MSX", "ACHX", party, person, True)
        self.service.publish("ACHX")
        self.assertFalse(self.service.request_access("P-EXTRA", "ACHX").allowed)
        self.assertTrue(self.service.request_access("P-TJU", "ACHX").allowed)

    def test_person_leaving_closes_future_access_keeps_history(self) -> None:
        self.publish()
        first = self.service.request_access("P-OTHER", "ACH1")
        self.assertTrue(first.allowed)
        self.service.person_left("P-OTHER", "离组")
        second = self.service.request_access("P-OTHER", "ACH1")
        self.assertFalse(second.allowed)
        self.assertIn("离组", second.reason)
        # 历史授权依据仍然完整保留。
        self.assertEqual(len(self.service.get_grants("ACH1")), 1)

    def test_party_withdraw_closes_future_access(self) -> None:
        self.publish()
        self.assertTrue(self.service.request_access("P-SCENE", "ACH1").allowed)
        self.service.withdraw_program("PRG", "SCENECO", "退出")
        decision = self.service.request_access("P-SCENE", "ACH1")
        self.assertFalse(decision.allowed)
        self.assertIn("退出", decision.reason)

    def test_conflict_blocks_and_clear_restores(self) -> None:
        self.publish()
        self.service.declare_conflict("P-SCENE", "PRG", "亲属在竞争企业")
        self.assertFalse(self.service.request_access("P-SCENE", "ACH1").allowed)
        self.service.clear_conflict("P-SCENE", "PRG")
        self.assertTrue(self.service.request_access("P-SCENE", "ACH1").allowed)

    def test_conflicted_person_must_abstain_from_voting(self) -> None:
        self.submit()
        self.service.declare_conflict("P-SCENE", "PRG", "利益冲突")
        with self.assertRaises(DomainError):
            self.service.technical_review("ACH1", "SCENECO", "P-SCENE", True)

    def test_freeze_blocks_submission_review_and_access(self) -> None:
        self.publish()
        self.service.freeze("ACH1", "知识产权归属争议")
        self.assertFalse(self.service.request_access("P-TJU", "ACH1").allowed)
        with self.assertRaises(ConflictError):
            self.service.submit_achievement(
                "ACH1", "WP1", "v2", CONTRIBS, "confidential", IP_TERMS,
                {"scope_type": "all_participants"}, "P-TJU", supersedes=1,
            )
        self.service.resolve_dispute("ACH1", "达成一致")
        self.assertTrue(self.service.request_access("P-TJU", "ACH1").allowed)

    def test_superseded_version_blocks_new_access_but_keeps_grants(self) -> None:
        self.publish()
        self.assertTrue(self.service.request_access("P-TJU", "ACH1").allowed)
        self.service.submit_achievement(
            "ACH1", "WP1", "v2", CONTRIBS, "confidential", IP_TERMS,
            {"scope_type": "all_participants"}, "P-TJU", supersedes=1,
        )
        old = self.service.get_achievement("ACH1", 1)
        self.assertEqual(old.state, AchievementState.SUPERSEDED)
        decision = self.service.request_access("P-TJU", "ACH1", version=1)
        self.assertFalse(decision.allowed)
        self.assertIn("替换", decision.reason)
        self.assertEqual(len(self.service.get_grants("ACH1")), 1)
        with self.assertRaises(ConflictError):
            self.service.submit_achievement(
                "ACH1", "WP1", "跳版", CONTRIBS, "confidential", IP_TERMS,
                {"scope_type": "all_participants"}, "P-TJU", supersedes=1,
            )

    def test_default_request_uses_latest_version(self) -> None:
        self.publish()
        self.service.submit_achievement(
            "ACH1", "WP1", "v2", CONTRIBS, "confidential", IP_TERMS,
            {"scope_type": "all_participants"}, "P-TJU", supersedes=1,
        )
        decision = self.service.request_access("P-TJU", "ACH1")
        self.assertEqual(decision.version, 2)
        self.assertFalse(decision.allowed)  # v2 尚未发布


class TraceTests(ServiceTestBase):
    def test_trace_covers_full_lifecycle(self) -> None:
        self.publish()
        self.service.request_access("P-TJU", "ACH1")
        self.service.freeze("WP1", "争议")
        self.service.resolve_dispute("WP1", "解决")
        timeline = self.service.trace("ACH1")
        stages = [entry["stage"] for entry in timeline]
        self.assertIn("立项", stages)
        self.assertIn("提交", stages)
        self.assertIn("技术验收", stages)
        self.assertIn("权利确认", stages)
        self.assertIn("发布", stages)
        self.assertIn("授权使用", stages)
        self.assertIn("争议", stages)
        self.assertEqual(stages, sorted(stages, key=lambda s: [e["seq"] for e in timeline if e["stage"] == s][0]))
        seqs = [entry["seq"] for entry in timeline]
        self.assertEqual(seqs, sorted(seqs))


class PersistenceTests(ServiceTestBase):
    def test_jsonl_store_replays_history(self) -> None:
        import tempfile
        from pathlib import Path

        from joint_lab import JsonlEventStore

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            first = JointLabService(JsonlEventStore(path))
            first.create_lab("LAB", "实验室")
            first.register_party("TJU", "天大", "school")
            first.create_program("PRG", "计划", "目标", ["TJU"])
            first.add_person("P1", "TJU", "张")
            first.create_work_package("WP1", "PRG", "包", "TJU")
            first.submit_achievement(
                "ACH1", "WP1", "成果",
                [{"party_code": "TJU", "person_code": "P1", "kind": "algorithm"}],
                "confidential", IP_TERMS,
                {"scope_type": "named_parties", "allowed_parties": ["TJU"]},
                "P1",
            )
            first.technical_review("ACH1", "TJU", "P1", True)
            first.rights_vote("MS1", "ACH1", "TJU", "P1", True)
            first.publish("ACH1")
            grant = first.request_access("P1", "ACH1")
            self.assertTrue(grant.allowed)

            first_count = len(first.event_history())

            replayed = JointLabService(JsonlEventStore(path))
            self.assertEqual(replayed.lab_name, "实验室")
            self.assertEqual(replayed.get_achievement("ACH1").state, AchievementState.PUBLISHED)
            self.assertEqual(len(replayed.get_grants()), 1)
            self.assertEqual(len(replayed.event_history()), first_count)
            self.assertTrue(replayed.request_access("P1", "ACH1").allowed)


if __name__ == "__main__":
    unittest.main()
