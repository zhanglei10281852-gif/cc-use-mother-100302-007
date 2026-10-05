"""HTTP API 端到端测试：在随机端口上驱动完整协同流程。"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from joint_lab.api import create_server
from joint_lab.repository import MemoryEventStore


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def call(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def post(self, path: str, payload: dict) -> tuple[int, dict]:
        return self.call("POST", path, payload)

    def get(self, path: str) -> tuple[int, dict]:
        return self.call("GET", path)


class ApiEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = create_server(host="127.0.0.1", port=0, store=MemoryEventStore())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.api = ApiClient(f"http://127.0.0.1:{self.port}")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_full_flow_over_http(self) -> None:
        status, _ = self.api.post("/labs", {"lab_code": "LAB", "name": "联合实验室"})
        self.assertEqual(status, 200)
        for code, name, kind in [
            ("TJU", "天大", "school"),
            ("ROBOTCO", "整机厂", "manufacturer"),
            ("SCENECO", "应用单位", "applicant"),
        ]:
            self.assertEqual(self.api.post("/parties", {"code": code, "name": name, "kind": kind})[0], 200)
        self.assertEqual(
            self.api.post(
                "/programs",
                {
                    "program_code": "PRG",
                    "name": "协同计划",
                    "objectives": "目标",
                    "party_codes": ["TJU", "ROBOTCO", "SCENECO"],
                    "budget": 900,
                },
            )[0],
            200,
        )
        for code, party, name in [
            ("P1", "TJU", "张"), ("P2", "ROBOTCO", "李"), ("P3", "SCENECO", "王"),
        ]:
            self.assertEqual(
                self.api.post("/persons", {"person_code": code, "party_code": party, "name": name})[0],
                200,
            )
        self.assertEqual(
            self.api.post(
                "/work-packages",
                {
                    "package_code": "WP1",
                    "program_code": "PRG",
                    "name": "集成工作包",
                    "lead_party": "TJU",
                    "dependencies": [],
                    "budget": 500,
                    "responsibilities": {"TJU": "算法", "ROBOTCO": "模组"},
                    "deliverables": ["算法包"],
                },
            )[0],
            200,
        )
        status, body = self.api.post(
            "/achievements",
            {
                "code": "ACH1",
                "package_code": "WP1",
                "title": "控制算法",
                "contributions": [
                    {"party_code": "TJU", "person_code": "P1", "kind": "algorithm"},
                    {"party_code": "ROBOTCO", "person_code": "P2", "kind": "joint_module"},
                    {"party_code": "SCENECO", "person_code": "P3", "kind": "scene_data"},
                ],
                "confidentiality": "confidential",
                "ip_terms": "三方共有",
                "scope": {"scope_type": "all_participants"},
                "submitted_by": "P1",
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["version"], 1)

        # 未发布前访问被拒绝。
        status, denied = self.api.post("/access", {"person_code": "P1", "achievement_code": "ACH1"})
        self.assertEqual(status, 200)
        self.assertFalse(denied["allowed"])

        for party, person in [("TJU", "P1"), ("ROBOTCO", "P2"), ("SCENECO", "P3")]:
            self.assertEqual(
                self.api.post(
                    f"/achievements/ACH1/technical-reviews",
                    {"party_code": party, "person_code": person, "approved": True},
                )[0],
                200,
            )
        for party, person in [("TJU", "P1"), ("ROBOTCO", "P2"), ("SCENECO", "P3")]:
            self.assertEqual(
                self.api.post(
                    f"/achievements/ACH1/rights-votes",
                    {
                        "milestone_code": "MS1",
                        "party_code": party,
                        "person_code": person,
                        "approved": True,
                    },
                )[0],
                200,
            )
        self.assertEqual(self.api.post("/achievements/ACH1/publish", {})[0], 200)

        status, granted = self.api.post("/access", {"person_code": "P1", "achievement_code": "ACH1"})
        self.assertEqual(status, 200)
        self.assertTrue(granted["allowed"])
        self.assertIsNotNone(granted["grant_code"])

        # 里程碑唯一结论。
        status, conclusion = self.api.get("/achievements/ACH1/conclusion/MS1")
        self.assertEqual(status, 200)
        self.assertTrue(conclusion["approved"])
        self.assertEqual(len(conclusion["votes"]), 3)

        # 离组立即关闭后续访问。
        self.assertEqual(self.api.post("/persons/P1/leave", {"reason": "离组"})[0], 200)
        _, after = self.api.post("/access", {"person_code": "P1", "achievement_code": "ACH1"})
        self.assertFalse(after["allowed"])
        self.assertIn("离组", after["reason"])

        # 追踪接口覆盖完整阶段。
        status, trace = self.api.get("/achievements/ACH1/trace")
        self.assertEqual(status, 200)
        stages = {entry["stage"] for entry in trace["timeline"]}
        self.assertEqual(
            stages, {"立项", "提交", "技术验收", "权利确认", "发布", "授权使用"}
        )

        # 事件全历史可导出。
        status, history = self.api.get("/events")
        self.assertEqual(status, 200)
        self.assertGreater(len(history["events"]), 10)

        # 未知对象返回 404。
        self.assertEqual(self.api.get("/achievements/NOPE")[0], 404)
        # 重复投票返回 409。
        self.assertEqual(
            self.api.post(
                "/achievements/ACH1/technical-reviews",
                {"party_code": "TJU", "person_code": "P1", "approved": False},
            )[0],
            409,
        )


if __name__ == "__main__":
    unittest.main()
