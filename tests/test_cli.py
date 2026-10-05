"""命令行端到端测试：管理方通过 CLI 追踪成果全过程。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from joint_lab.cli import main


def run_cli(*args: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(args))
    return code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = str(Path(self.tmp.name) / "store.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_ok(self, *args: str) -> dict:
        code, out, err = run_cli(*args, "--store", self.store)
        self.assertEqual(code, 0, msg=err)
        return json.loads(out)

    def test_end_to_end_flow(self) -> None:
        self.run_ok("add-party", "--party-id", "univ", "--name", "天津大学研究院", "--kind", "university")
        self.run_ok("add-party", "--party-id", "oem", "--name", "整机厂", "--kind", "enterprise")
        self.run_ok(
            "create-plan",
            "--plan-id",
            "plan-1",
            "--title",
            "共建计划",
            "--goal",
            "形成成果",
            "--budget",
            "100",
            "--party",
            "univ:算法:60",
            "--party",
            "oem:模组:40",
        )
        self.run_ok(
            "add-work-package",
            "--plan-id",
            "plan-1",
            "--wp-id",
            "wp-1",
            "--title",
            "感知控制",
            "--objective",
            "算法库",
            "--budget",
            "80",
            "--resp",
            "univ:算法",
            "--resp",
            "oem:模组",
            "--deliverable",
            "d-1:算法库",
        )
        self.run_ok("add-milestone", "--wp-id", "wp-1", "--milestone-id", "ms-1", "--name", "中期")
        result = self.run_ok("confirm-milestone", "--milestone-id", "ms-1", "--party-id", "univ", "--decision", "approve")
        self.assertIsNone(result["conclusion"])
        result = self.run_ok("confirm-milestone", "--milestone-id", "ms-1", "--party-id", "oem", "--decision", "approve")
        self.assertEqual(result["conclusion"], "achieved")

        self.run_ok("add-member", "--member-id", "m-1", "--party-id", "oem", "--name", "工程师", "--clearance", "2")
        self.run_ok(
            "submit-achievement",
            "--achievement-id",
            "ach-1",
            "--wp-id",
            "wp-1",
            "--title",
            "控制算法",
            "--summary",
            "摘要",
            "--contribution",
            "univ:算法:控制律",
            "--confidentiality",
            "2",
            "--ipr-owners",
            "univ",
            "--ipr-license",
            "共有",
            "--fulfills",
            "d-1",
        )
        # 里程碑完成但成果未发布：访问被拒绝
        result = self.run_ok("check-access", "--member-id", "m-1", "--achievement-id", "ach-1")
        self.assertFalse(result["decision"]["granted"])

        self.run_ok("tech-acceptance", "--achievement-id", "ach-1", "--passed")
        self.run_ok("rights-confirmation", "--achievement-id", "ach-1", "--confirmed")
        self.run_ok("publish", "--achievement-id", "ach-1")
        result = self.run_ok("check-access", "--member-id", "m-1", "--achievement-id", "ach-1")
        self.assertTrue(result["decision"]["granted"])

        # 成员退出后访问立即失效，历史依据保留
        self.run_ok("withdraw-member", "--member-id", "m-1")
        result = self.run_ok("check-access", "--member-id", "m-1", "--achievement-id", "ach-1")
        self.assertFalse(result["decision"]["granted"])
        self.assertIn("成员已退出", result["decision"]["reasons"])
        history = self.run_ok("access-history", "--member-id", "m-1")
        self.assertEqual([r["granted"] for r in history["records"]], [False, True, False])

        # 追踪从立项、评审到授权使用的完整过程
        trace = self.run_ok("trace", "--achievement-id", "ach-1", "--format", "json")
        types = [event["type"] for event in trace["events"]]
        self.assertIn("ACHIEVEMENT_SUBMITTED", types)
        self.assertIn("ACHIEVEMENT_PUBLISHED", types)
        self.assertIn("ACCESS_CHECKED", types)

        verify = self.run_ok("verify")
        self.assertTrue(verify["valid"])

    def test_demo_command(self) -> None:
        code, out, _ = run_cli("demo")
        self.assertEqual(code, 0)
        summary = json.loads(out)
        self.assertEqual(summary["milestone_conclusion"], "achieved")
        self.assertTrue(summary["ledger_valid"])
        granted_flags = [check["granted"] for check in summary["access_checks"]]
        self.assertEqual(granted_flags, [False, True, False, False])

    def test_domain_error_exits_nonzero(self) -> None:
        code, _, err = run_cli("withdraw-member", "--member-id", "ghost", "--store", self.store)
        self.assertEqual(code, 1)
        self.assertIn("不存在", err)

    def test_review_flag_validation(self) -> None:
        code, _, err = run_cli("tech-acceptance", "--achievement-id", "ach-1", "--store", self.store)
        self.assertEqual(code, 2)
        self.assertIn("--passed", err)


if __name__ == "__main__":
    unittest.main()
