"""校企联合实验室成果协同 HTTP API（仅依赖 Python 标准库）。

启动后管理方可以通过 REST 接口操作合作计划、工作包、成果评审、
授权访问与争议冻结，并通过 /achievements/{code}/trace 追踪完整过程。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .errors import DomainError, NotFound
from .repository import EventStore, JsonlEventStore
from .serializers import to_jsonable
from .service import JointLabService


def _achievement_dict(achievement: Any) -> dict[str, Any]:
    return {
        "code": achievement.code,
        "version": achievement.version,
        "package_code": achievement.package_code,
        "program_code": achievement.program_code,
        "title": achievement.title,
        "state": achievement.state.value,
        "confidentiality": achievement.confidentiality.value,
        "ip_terms": achievement.ip_terms,
        "submitted_by": achievement.submitted_by,
        "supersedes": achievement.supersedes,
        "scope": to_jsonable(achievement.scope),
        "contributions": [to_jsonable(c) for c in achievement.contributions],
    }


def _grant_dict(grant: Any) -> dict[str, Any]:
    return {
        "grant_code": grant.grant_code,
        "achievement_code": grant.achievement_code,
        "version": grant.version,
        "person_code": grant.person_code,
        "party_code": grant.party_code,
        "confidentiality": grant.confidentiality.value,
        "scope_type": grant.scope_type.value,
        "reason": grant.reason,
        "at_seq": grant.at_seq,
    }


def _conclusion_dict(conclusion: Any) -> dict[str, Any]:
    return {
        "milestone_code": conclusion.milestone_code,
        "achievement_code": conclusion.achievement_code,
        "version": conclusion.version,
        "approved": conclusion.approved,
        "at_seq": conclusion.at_seq,
        "votes": [
            {"party_code": v[0], "person_code": v[1], "approved": v[2], "comment": v[3]}
            for v in conclusion.votes
        ],
    }


def _package_dict(package: Any) -> dict[str, Any]:
    return {
        "package_code": package.package_code,
        "program_code": package.program_code,
        "name": package.name,
        "lead_party": package.lead_party,
        "dependencies": sorted(package.dependencies),
        "budget": package.budget,
        "responsibilities": [list(item) for item in package.responsibilities],
        "deliverables": list(package.deliverables),
    }


class _Handler(BaseHTTPRequestHandler):
    service: JointLabService  # 由 create_server 注入到类上

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # 静默访问日志，测试输出更干净

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DomainError(f"请求体不是合法 JSON：{exc}") from exc
        if not isinstance(data, dict):
            raise DomainError("请求体必须是 JSON 对象")
        return data

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.strip("/")
        parts = path.split("/") if path else []
        try:
            body = self._read_body() if method == "POST" else {}
            handler = self._route(method, parts)
            if handler is None:
                self._send(404, {"error": f"未找到路径：{self.path}"})
                return
            self._send(200, handler(body, parts))
        except NotFound as exc:
            self._send(404, {"error": str(exc)})
        except DomainError as exc:
            self._send(409, {"error": str(exc)})
        except (KeyError, TypeError) as exc:
            self._send(400, {"error": f"请求参数有误：{exc}"})

    def _route(self, method: str, parts: list[str]) -> Callable[[dict[str, Any], list[str]], Any] | None:
        table = self.server.routes  # type: ignore[attr-defined]
        for candidate_methods, candidate_parts, handler in table:
            if method not in candidate_methods:
                continue
            if len(candidate_parts) != len(parts):
                continue
            if all(static == part or static.startswith("{") for static, part in zip(candidate_parts, parts)):
                return handler
        return None


def create_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    store: EventStore | None = None,
    event_path: str | None = None,
) -> ThreadingHTTPServer:
    """创建 API 服务器；默认使用 JSONL 事件文件持久化。"""
    if store is None:
        store = JsonlEventStore(event_path or "joint_lab_events.jsonl")
    service = JointLabService(store)

    def ok(event: Any = None, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": True}
        if event is not None:
            payload["event"] = {"type": type(event).__name__, "seq": event.seq}
        payload.update(extra)
        return payload

    def create_lab(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.create_lab(body["lab_code"], body["name"])
        return ok(event)

    def register_party(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.register_party(body["code"], body["name"], body["kind"])
        return ok(event)

    def create_program(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.create_program(
            body["program_code"],
            body["name"],
            body.get("objectives", ""),
            body["party_codes"],
            body.get("budget", 0.0),
        )
        return ok(event)

    def join_program(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.join_program(parts[1], body["party_code"], body.get("responsibility", ""))
        return ok(event)

    def withdraw_program(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.withdraw_program(parts[1], body["party_code"], body.get("reason", ""))
        return ok(event)

    def add_person(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.add_person(body["person_code"], body["party_code"], body["name"])
        return ok(event)

    def person_left(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.person_left(parts[1], body.get("reason", ""))
        return ok(event)

    def declare_conflict(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.declare_conflict(parts[1], body["program_code"], body["description"])
        return ok(event)

    def clear_conflict(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.clear_conflict(parts[1], body["program_code"])
        return ok(event)

    def create_work_package(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.create_work_package(
            body["package_code"],
            body["program_code"],
            body["name"],
            body["lead_party"],
            body.get("dependencies", ()),
            body.get("budget", 0.0),
            body.get("responsibilities", ()),
            body.get("deliverables", ()),
        )
        return ok(event)

    def submit_achievement(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.submit_achievement(
            body["code"],
            body["package_code"],
            body["title"],
            body["contributions"],
            body["confidentiality"],
            body["ip_terms"],
            body["scope"],
            body["submitted_by"],
            body.get("supersedes"),
        )
        return ok(event, version=event.version)

    def technical_review(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.technical_review(
            parts[1],
            body["party_code"],
            body["person_code"],
            bool(body["approved"]),
            body.get("comment", ""),
        )
        return ok(event)

    def rights_vote(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.rights_vote(
            body["milestone_code"],
            parts[1],
            body["party_code"],
            body["person_code"],
            bool(body["approved"]),
            body.get("comment", ""),
        )
        return ok(event)

    def publish(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.publish(parts[1])
        return ok(event)

    def request_access(body: dict[str, Any], parts: list[str]) -> Any:
        decision = service.request_access(
            body["person_code"], body["achievement_code"], body.get("version")
        )
        return decision.to_dict()

    def freeze(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.freeze(body["target_code"], body["reason"])
        return ok(event)

    def resolve_dispute(body: dict[str, Any], parts: list[str]) -> Any:
        event = service.resolve_dispute(parts[1], body["resolution"])
        return ok(event)

    def get_achievement(body: dict[str, Any], parts: list[str]) -> Any:
        return _achievement_dict(service.get_achievement(parts[1]))

    def get_packages(body: dict[str, Any], parts: list[str]) -> Any:
        return {"packages": [_package_dict(p) for p in service.get_program_packages(parts[1])]}

    def get_conclusion(body: dict[str, Any], parts: list[str]) -> Any:
        return _conclusion_dict(service.get_conclusion(parts[3]))

    def get_grants(body: dict[str, Any], parts: list[str]) -> Any:
        code = parts[1] if len(parts) == 2 else None
        return {"grants": [_grant_dict(g) for g in service.get_grants(code)]}

    def trace(body: dict[str, Any], parts: list[str]) -> Any:
        return {"achievement_code": parts[1], "timeline": service.trace(parts[1])}

    def history(body: dict[str, Any], parts: list[str]) -> Any:
        return {
            "events": [
                {"seq": event.seq, "type": type(event).__name__, "data": _event_payload(event)}
                for event in service.event_history()
            ]
        }

    def list_grants(body: dict[str, Any], parts: list[str]) -> Any:
        return {"grants": [_grant_dict(grant) for grant in service.get_grants()]}

    routes = [
        (("POST",), ["labs"], create_lab),
        (("POST",), ["parties"], register_party),
        (("POST",), ["programs"], create_program),
        (("POST",), ["programs", "{code}", "join"], join_program),
        (("POST",), ["programs", "{code}", "withdraw"], withdraw_program),
        (("GET",), ["programs", "{code}", "packages"], get_packages),
        (("POST",), ["persons"], add_person),
        (("POST",), ["persons", "{code}", "leave"], person_left),
        (("POST",), ["persons", "{code}", "conflicts"], declare_conflict),
        (("POST",), ["persons", "{code}", "conflicts-clear"], clear_conflict),
        (("POST",), ["work-packages"], create_work_package),
        (("POST",), ["achievements"], submit_achievement),
        (("GET",), ["achievements", "{code}"], get_achievement),
        (("POST",), ["achievements", "{code}", "technical-reviews"], technical_review),
        (("POST",), ["achievements", "{code}", "rights-votes"], rights_vote),
        (("POST",), ["achievements", "{code}", "publish"], publish),
        (("GET",), ["achievements", "{code}", "trace"], trace),
        (("GET",), ["achievements", "{code}", "conclusion", "{milestone}"], get_conclusion),
        (("POST",), ["access"], request_access),
        (("GET",), ["grants"], list_grants),
        (("GET",), ["grants", "{code}"], get_grants),
        (("POST",), ["freezes"], freeze),
        (("POST",), ["freezes", "{code}", "resolve"], resolve_dispute),
        (("GET",), ["events"], history),
    ]

    handler = type("_BoundHandler", (_Handler,), {"service": service})
    server = ThreadingHTTPServer((host, port), handler)
    server.routes = routes  # type: ignore[attr-defined]
    server.service = service  # type: ignore[attr-defined]
    return server


def _event_payload(event: Any) -> Any:
    from .service import _event_detail  # 复用详情转换

    return _event_detail(event)


def serve(host: str = "127.0.0.1", port: int = 8080, event_path: str | None = None) -> None:
    server = create_server(host=host, port=port, event_path=event_path)
    print(f"校企联合实验室成果协同服务已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
