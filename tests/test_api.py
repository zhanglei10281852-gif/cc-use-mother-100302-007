"""JSON API 层测试：管理方通过 API 追踪成果全过程。"""

import http.client
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone

from joint_lab.api import create_server, handle_request
from joint_lab.service import CollaborationService


class FakeClock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> str:
        self.moment += timedelta(seconds=1)
        return self.moment.isoformat()


def post(service: CollaborationService, path: str, body: dict) -> tuple[int, dict]:
    return handle_request(service, "POST", path, body)


def get(service: CollaborationService, path: str) -> tuple[int, dict]:
    return handle_request(service, "GET", path)


def build_published_service() -> CollaborationService:
    service = CollaborationService(clock=FakeClock())
    status, _ = post(service, "/parties", {"party_id": "univ", "name": "高校", "kind": "university"})
    assert status == 201
    post(service, "/parties", {"party_id": "oem", "name": "整机厂", "kind": "enterprise"})
    post(
        service,
        "/plans",
        {
            "plan_id": "plan-1",
            "title": "共建计划",
            "goals": ["目标"],
            "total_budget": 100.0,
            "parties": [
                {"party_id": "univ", "responsibility": "算法", "budget_share": 60.0},
                {"party_id": "oem", "responsibility": "模组", "budget_share": 40.0},
            ],
        },
    )
    post(
        service,
        "/plans/plan-1/work-packages",
        {
            "wp_id": "wp-1",
            "title": "工作包",
            "objectives": ["目标"],
            "budget": 80.0,
            "responsibilities": {"univ": "算法", "oem": "模组"},
            "deliverables": [{"deliverable_id": "d-1", "name": "算法库"}],
        },
    )
    post(service, "/work-packages/wp-1/milestones", {"milestone_id": "ms-1", "name": "中期"})
    post(service, "/members", {"member_id": "m-1", "party_id": "oem", "name": "工程师", "clearance": 2})
    post(
        service,
        "/achievements",
        {
            "achievement_id": "ach-1",
            "wp_id": "wp-1",
            "title": "成果",
            "summary": "摘要",
            "contributions": [{"party_id": "univ", "kind": "算法", "description": "控制律"}],
            "confidentiality": 2,
            "ipr": {"owner_party_ids": ["univ"], "license": "共有"},
            "usage_scope": {"kind": "plan", "party_ids": []},
            "fulfills": ["d-1"],
        },
    )
    post(service, "/achievements/ach-1/tech-acceptance", {"passed": True})
    post(service, "/achievements/ach-1/rights-confirmation", {"confirmed": True})
    post(service, "/achievements/ach-1/publish", {})
    return service


class ApiDispatchTests(unittest.TestCase):
    def test_full_flow_and_trace_via_api(self) -> None:
        service = build_published_service()
        status, milestone = post(service, "/milestones/ms-1/confirmations", {"party_id": "univ", "approve": True})
        self.assertEqual(status, 200)
        self.assertIsNone(milestone["result"]["conclusion"])
        status, milestone = post(service, "/milestones/ms-1/confirmations", {"party_id": "oem", "approve": True})
        self.assertEqual(milestone["result"]["conclusion"], "achieved")
        # 结论只能形成一次
        status, _ = post(service, "/milestones/ms-1/confirmations", {"party_id": "oem", "approve": True})
        self.assertEqual(status, 409)

        status, decision = post(service, "/access/checks", {"member_id": "m-1", "achievement_id": "ach-1"})
        self.assertEqual(status, 200)
        self.assertTrue(decision["result"]["granted"])

        status, trace = get(service, "/achievements/ach-1/trace")
        self.assertEqual(status, 200)
        types = [event["type"] for event in trace["result"]["events"]]
        self.assertIn("ACHIEVEMENT_SUBMITTED", types)
        self.assertIn("ACHIEVEMENT_PUBLISHED", types)
        self.assertIn("ACCESS_CHECKED", types)

        status, view = get(service, "/achievements/ach-1")
        self.assertEqual(view["result"]["state"], "published")
        status, verify = get(service, "/ledger/verify")
        self.assertTrue(verify["result"]["valid"])

    def test_withdrawal_via_api_changes_access(self) -> None:
        service = build_published_service()
        post(service, "/members/m-1/withdraw", {})
        status, decision = post(service, "/access/checks", {"member_id": "m-1", "achievement_id": "ach-1"})
        self.assertEqual(status, 200)
        self.assertFalse(decision["result"]["granted"])
        self.assertIn("成员已退出", decision["result"]["reasons"])

    def test_error_mapping(self) -> None:
        service = build_published_service()
        status, body = post(service, "/parties", {"party_id": "univ", "name": "重复", "kind": "university"})
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])
        status, _ = get(service, "/achievements/ach-404")
        self.assertEqual(status, 404)
        status, _ = post(service, "/members", {"member_id": "m-x", "party_id": "univ", "name": "", "clearance": 2})
        self.assertEqual(status, 400)
        status, _ = get(service, "/no-such-route")
        self.assertEqual(status, 404)
        status, _ = get(service, "/parties")
        self.assertEqual(status, 405)

    def test_access_history_endpoint(self) -> None:
        service = build_published_service()
        post(service, "/access/checks", {"member_id": "m-1", "achievement_id": "ach-1"})
        status, history = post(service, "/access/history", {"achievement_id": "ach-1"})
        self.assertEqual(status, 200)
        self.assertEqual(len(history["result"]["records"]), 1)


class HttpServerTests(unittest.TestCase):
    def test_http_roundtrip(self) -> None:
        service = CollaborationService(clock=FakeClock())
        server = create_server(service, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read().decode("utf-8"))["ok"])

            conn.request(
                "POST",
                "/parties",
                body=json.dumps({"party_id": "univ", "name": "高校", "kind": "university"}),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 201)
            json.loads(response.read().decode("utf-8"))
            conn.close()
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("univ", service.parties)


if __name__ == "__main__":
    unittest.main()
