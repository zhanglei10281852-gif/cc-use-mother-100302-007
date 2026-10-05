"""基于标准库的 JSON API 层：管理方可以通过 HTTP 追踪成果全过程。"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from .errors import ConflictError, DomainError, NotFoundError, StateError, ValidationError
from .service import CollaborationService

Handler = Callable[..., dict]


def _pattern(template: str) -> re.Pattern:
    return re.compile(re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", template))


# ---------------------------------------------------------------------------
# 路由处理函数
# ---------------------------------------------------------------------------


def _health(service: CollaborationService, body: dict) -> dict:
    return {"status": "ok", "events": len(service.ledger)}


def _create_party(service: CollaborationService, body: dict) -> dict:
    service.register_party(party_id=body.get("party_id"), name=body.get("name"), kind=body.get("kind"))
    return {"party_id": body.get("party_id")}


def _create_member(service: CollaborationService, body: dict) -> dict:
    service.add_member(
        member_id=body.get("member_id"),
        party_id=body.get("party_id"),
        name=body.get("name"),
        clearance=body.get("clearance", 1),
    )
    return {"member_id": body.get("member_id")}


def _withdraw_member(service: CollaborationService, body: dict, member_id: str) -> dict:
    service.withdraw_member(member_id=member_id)
    return {"member_id": member_id}


def _declare_conflict(service: CollaborationService, body: dict) -> dict:
    service.declare_conflict(
        coi_id=body.get("coi_id"),
        member_id=body.get("member_id"),
        achievement_id=body.get("achievement_id"),
        party_id=body.get("party_id"),
        reason=body.get("reason", ""),
    )
    return {"coi_id": body.get("coi_id")}


def _lift_conflict(service: CollaborationService, body: dict, coi_id: str) -> dict:
    service.lift_conflict(coi_id=coi_id)
    return {"coi_id": coi_id}


def _create_plan(service: CollaborationService, body: dict) -> dict:
    service.create_plan(
        plan_id=body.get("plan_id"),
        title=body.get("title"),
        goals=body.get("goals"),
        total_budget=body.get("total_budget"),
        parties=body.get("parties"),
    )
    return {"plan_id": body.get("plan_id")}


def _create_work_package(service: CollaborationService, body: dict, plan_id: str) -> dict:
    service.add_work_package(
        plan_id=plan_id,
        wp_id=body.get("wp_id"),
        title=body.get("title"),
        objectives=body.get("objectives"),
        depends_on=body.get("depends_on"),
        budget=body.get("budget", 0),
        responsibilities=body.get("responsibilities"),
        deliverables=body.get("deliverables"),
    )
    return {"wp_id": body.get("wp_id")}


def _create_milestone(service: CollaborationService, body: dict, wp_id: str) -> dict:
    service.add_milestone(
        wp_id=wp_id,
        milestone_id=body.get("milestone_id"),
        name=body.get("name"),
        required_parties=body.get("required_parties"),
    )
    return {"milestone_id": body.get("milestone_id")}


def _confirm_milestone(service: CollaborationService, body: dict, milestone_id: str) -> dict:
    conclusion = service.confirm_milestone(
        milestone_id=milestone_id,
        party_id=body.get("party_id"),
        approve=body.get("approve"),
        note=body.get("note", ""),
    )
    return {"milestone_id": milestone_id, "conclusion": conclusion}


def _get_milestone(service: CollaborationService, body: dict, milestone_id: str) -> dict:
    return service.milestone_view(milestone_id)


def _create_achievement(service: CollaborationService, body: dict) -> dict:
    service.submit_achievement(
        achievement_id=body.get("achievement_id"),
        wp_id=body.get("wp_id"),
        title=body.get("title"),
        summary=body.get("summary"),
        contributions=body.get("contributions"),
        confidentiality=body.get("confidentiality"),
        ipr=body.get("ipr"),
        usage_scope=body.get("usage_scope"),
        fulfills=body.get("fulfills"),
    )
    return {"achievement_id": body.get("achievement_id")}


def _get_achievement(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    return service.achievement_view(achievement_id)


def _tech_acceptance(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    service.record_technical_acceptance(
        achievement_id=achievement_id,
        passed=body.get("passed"),
        notes=body.get("notes", ""),
        reviewer=body.get("reviewer", ""),
    )
    return {"achievement_id": achievement_id}


def _rights_confirmation(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    service.confirm_rights(
        achievement_id=achievement_id,
        confirmed=body.get("confirmed"),
        notes=body.get("notes", ""),
        confirmer=body.get("confirmer", ""),
    )
    return {"achievement_id": achievement_id}


def _publish(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    service.publish_achievement(achievement_id=achievement_id)
    return {"achievement_id": achievement_id}


def _freeze(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    service.freeze_achievement(
        achievement_id=achievement_id, reason=body.get("reason"), operator=body.get("operator", "")
    )
    return {"achievement_id": achievement_id}


def _resolve(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    service.resolve_dispute(achievement_id=achievement_id, resolution=body.get("resolution", ""))
    return {"achievement_id": achievement_id}


def _replace(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    service.replace_achievement(old_achievement_id=achievement_id, new_achievement_id=body.get("new_achievement_id"))
    return {"achievement_id": achievement_id, "new_achievement_id": body.get("new_achievement_id")}


def _check_access(service: CollaborationService, body: dict) -> dict:
    decision = service.check_access(
        member_id=body.get("member_id"),
        achievement_id=body.get("achievement_id"),
        purpose=body.get("purpose", ""),
    )
    return decision.to_dict()


def _trace(service: CollaborationService, body: dict, achievement_id: str) -> dict:
    return {"achievement_id": achievement_id, "events": service.trace_achievement(achievement_id)}


def _access_history(service: CollaborationService, body: dict) -> dict:
    return {"records": service.access_history(member_id=body.get("member_id"), achievement_id=body.get("achievement_id"))}


def _verify(service: CollaborationService, body: dict) -> dict:
    return {"valid": service.verify(), "events": len(service.ledger)}


ROUTES: list[tuple[str, re.Pattern, int, Handler]] = [
    ("GET", _pattern("/health"), 200, _health),
    ("POST", _pattern("/parties"), 201, _create_party),
    ("POST", _pattern("/members"), 201, _create_member),
    ("POST", _pattern("/members/{member_id}/withdraw"), 200, _withdraw_member),
    ("POST", _pattern("/conflicts"), 201, _declare_conflict),
    ("POST", _pattern("/conflicts/{coi_id}/lift"), 200, _lift_conflict),
    ("POST", _pattern("/plans"), 201, _create_plan),
    ("POST", _pattern("/plans/{plan_id}/work-packages"), 201, _create_work_package),
    ("POST", _pattern("/work-packages/{wp_id}/milestones"), 201, _create_milestone),
    ("POST", _pattern("/milestones/{milestone_id}/confirmations"), 200, _confirm_milestone),
    ("GET", _pattern("/milestones/{milestone_id}"), 200, _get_milestone),
    ("POST", _pattern("/achievements"), 201, _create_achievement),
    ("GET", _pattern("/achievements/{achievement_id}"), 200, _get_achievement),
    ("POST", _pattern("/achievements/{achievement_id}/tech-acceptance"), 200, _tech_acceptance),
    ("POST", _pattern("/achievements/{achievement_id}/rights-confirmation"), 200, _rights_confirmation),
    ("POST", _pattern("/achievements/{achievement_id}/publish"), 200, _publish),
    ("POST", _pattern("/achievements/{achievement_id}/freeze"), 200, _freeze),
    ("POST", _pattern("/achievements/{achievement_id}/resolve"), 200, _resolve),
    ("POST", _pattern("/achievements/{achievement_id}/replace"), 200, _replace),
    ("GET", _pattern("/achievements/{achievement_id}/trace"), 200, _trace),
    ("POST", _pattern("/access/checks"), 200, _check_access),
    ("POST", _pattern("/access/history"), 200, _access_history),
    ("GET", _pattern("/ledger/verify"), 200, _verify),
]


def _error_status(exc: DomainError) -> int:
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, (StateError, ConflictError)):
        return 409
    if isinstance(exc, ValidationError):
        return 400
    return 400


def handle_request(
    service: CollaborationService, method: str, path: str, body: dict | None = None
) -> tuple[int, dict]:
    """分发一次 API 请求，返回 (状态码, 响应体)。"""
    body = body or {}
    path_matched = False
    for route_method, pattern, status, handler in ROUTES:
        match = pattern.fullmatch(path)
        if not match:
            continue
        if route_method != method:
            path_matched = True
            continue
        try:
            payload = handler(service, body, **match.groupdict())
        except DomainError as exc:
            return _error_status(exc), {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        return status, {"ok": True, "result": payload}
    if path_matched:
        return 405, {"ok": False, "error": "方法不允许"}
    return 404, {"ok": False, "error": "路径不存在"}


def create_server(
    service: CollaborationService,
    host: str = "127.0.0.1",
    port: int = 8080,
    on_change: Callable[[], None] | None = None,
) -> ThreadingHTTPServer:
    """构建 HTTP 服务；on_change 在每次成功写操作后触发（可用于落盘）。"""
    lock = threading.Lock()

    class RequestHandler(BaseHTTPRequestHandler):
        server_version = "JointLab/0.2"

        def _dispatch(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body: dict = {}
            if raw:
                try:
                    parsed: Any = json.loads(raw.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError
                    body = parsed
                except (UnicodeDecodeError, ValueError):
                    self._respond(400, {"ok": False, "error": "请求体不是合法 JSON 对象"})
                    return
            path = unquote(urlparse(self.path).path)
            with lock:
                status, payload = handle_request(service, self.command, path, body)
                if on_change is not None and self.command == "POST" and status < 300:
                    on_change()
            self._respond(status, payload)

        do_GET = _dispatch
        do_POST = _dispatch

        def _respond(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:  # 静默访问日志
            pass

    return ThreadingHTTPServer((host, port), RequestHandler)


def serve(
    service: CollaborationService,
    host: str = "127.0.0.1",
    port: int = 8080,
    on_change: Callable[[], None] | None = None,
) -> None:
    server = create_server(service, host=host, port=port, on_change=on_change)
    actual_port = server.server_address[1]
    print(f"API 服务已启动：http://{host}:{actual_port}（Ctrl+C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
