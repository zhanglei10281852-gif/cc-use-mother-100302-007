"""校企联合实验室成果协同命令行工具。

用法示例见模块底部 `demo` 子命令：它会在内存事件存储上完整演示
"立项 → 提交（贡献来源/保密/知识产权/使用范围）→ 技术验收 →
权利确认 → 发布 → 授权使用 → 离组/退出/冲突/替换/争议冻结 → 追踪"。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .errors import DomainError
from .models import Confidentiality, ContributionKind, PartyKind, ScopeType
from .repository import JsonlEventStore, MemoryEventStore
from .serializers import to_jsonable
from .service import JointLabService

DEFAULT_DB = os.environ.get("JOINT_LAB_DB", "joint_lab_events.jsonl")


def _load_service(path: str, memory: bool = False) -> JointLabService:
    store = MemoryEventStore() if memory else JsonlEventStore(path)
    return JointLabService(store)


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _event_info(event: Any) -> dict[str, Any]:
    return {"event": type(event).__name__, "seq": event.seq}


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
        "scope": to_jsonable(achievement.scope),
        "contributions": [to_jsonable(c) for c in achievement.contributions],
        "submitted_by": achievement.submitted_by,
        "supersedes": achievement.supersedes,
    }


def _parse_contribution(raw: str) -> dict[str, Any]:
    """格式：机构代码:人员代码:类型[:说明]，人员代码或说明可留空。"""
    parts = raw.split(":", 3)
    if len(parts) < 3:
        raise DomainError(f"贡献来源格式应为 机构:人员:类型[:说明]，收到：{raw}")
    party_code, person_code, kind = parts[0], parts[1], parts[2]
    description = parts[3] if len(parts) == 4 else ""
    ContributionKind(kind)  # 提前校验枚举
    return {
        "party_code": party_code,
        "person_code": person_code or None,
        "kind": kind,
        "description": description,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="joint-lab", description="校企联合实验室成果协同服务")
    parser.add_argument("--db", default=DEFAULT_DB, help="事件日志 JSONL 路径")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-lab", help="建立联合实验室")
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)

    p = sub.add_parser("add-party", help="登记参与机构")
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--kind", required=True, choices=[k.value for k in PartyKind])

    p = sub.add_parser("add-program", help="创建合作计划")
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--objectives", default="")
    p.add_argument("--parties", required=True, help="逗号分隔的参与机构代码")
    p.add_argument("--budget", type=float, default=0.0)

    p = sub.add_parser("program-join", help="机构加入合作计划")
    p.add_argument("--program", required=True)
    p.add_argument("--party", required=True)
    p.add_argument("--responsibility", default="")

    p = sub.add_parser("program-withdraw", help="机构退出合作计划")
    p.add_argument("--program", required=True)
    p.add_argument("--party", required=True)
    p.add_argument("--reason", default="")

    p = sub.add_parser("add-person", help="人员加入")
    p.add_argument("--code", required=True)
    p.add_argument("--party", required=True)
    p.add_argument("--name", required=True)

    p = sub.add_parser("person-leave", help="人员离组")
    p.add_argument("--code", required=True)
    p.add_argument("--reason", default="")

    p = sub.add_parser("declare-conflict", help="申报利益冲突")
    p.add_argument("--code", required=True, help="人员代码")
    p.add_argument("--program", required=True)
    p.add_argument("--description", required=True)

    p = sub.add_parser("clear-conflict", help="解除利益冲突")
    p.add_argument("--code", required=True)
    p.add_argument("--program", required=True)

    p = sub.add_parser("add-package", help="创建工作包")
    p.add_argument("--code", required=True)
    p.add_argument("--program", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--lead", required=True)
    p.add_argument("--depends", default="", help="逗号分隔的前置工作包")
    p.add_argument("--budget", type=float, default=0.0)
    p.add_argument("--responsibility", action="append", default=[], help="机构:责任，可重复")
    p.add_argument("--deliverable", action="append", default=[], help="交付物，可重复")

    p = sub.add_parser("submit", help="提交成果")
    p.add_argument("--code", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--by", required=True, help="提交人代码")
    p.add_argument("--confidentiality", required=True, choices=[c.value for c in Confidentiality])
    p.add_argument("--ip", required=True, help="知识产权约定")
    p.add_argument("--scope", required=True, choices=[s.value for s in ScopeType])
    p.add_argument("--allowed", default="", help="scope=named_parties 时逗号分隔的机构代码")
    p.add_argument("--contribution", action="append", required=True, help="机构:人员:类型[:说明]，可重复")
    p.add_argument("--supersedes", type=int, default=None)

    p = sub.add_parser("tech-vote", help="技术验收投票")
    p.add_argument("--achievement", required=True)
    p.add_argument("--party", required=True)
    p.add_argument("--person", required=True)
    p.add_argument("--approve", action="store_true")
    p.add_argument("--reject", action="store_true")
    p.add_argument("--comment", default="")

    p = sub.add_parser("rights-vote", help="跨机构里程碑权利确认投票")
    p.add_argument("--milestone", required=True)
    p.add_argument("--achievement", required=True)
    p.add_argument("--party", required=True)
    p.add_argument("--person", required=True)
    p.add_argument("--approve", action="store_true")
    p.add_argument("--reject", action="store_true")
    p.add_argument("--comment", default="")

    p = sub.add_parser("publish", help="发布成果")
    p.add_argument("--achievement", required=True)

    p = sub.add_parser("access", help="请求使用成果")
    p.add_argument("--person", required=True)
    p.add_argument("--achievement", required=True)
    p.add_argument("--version", type=int, default=None)

    p = sub.add_parser("freeze", help="争议冻结")
    p.add_argument("--target", required=True)
    p.add_argument("--reason", required=True)

    p = sub.add_parser("resolve", help="争议解决并解除冻结")
    p.add_argument("--target", required=True)
    p.add_argument("--resolution", required=True)

    p = sub.add_parser("show", help="查看成果当前版本")
    p.add_argument("--achievement", required=True)
    p.add_argument("--version", type=int, default=None)

    p = sub.add_parser("grants", help="查看历史授权使用依据")
    p.add_argument("--achievement", default=None)

    p = sub.add_parser("conclusion", help="查看跨机构里程碑唯一结论")
    p.add_argument("--milestone", required=True)

    p = sub.add_parser("trace", help="追踪成果从立项到授权使用的完整过程")
    p.add_argument("--achievement", required=True)

    sub.add_parser("events", help="导出全部不可变事件")
    sub.add_parser("demo", help="在内存中运行端到端演示场景")

    p = sub.add_parser("serve", help="启动 HTTP API 服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    return parser


def _vote_choice(args: argparse.Namespace) -> bool:
    if args.approve == args.reject:
        raise DomainError("必须且只能给出 --approve 或 --reject")
    return args.approve


def run_demo() -> dict[str, Any]:
    """完整业务场景，返回可打印的演示结果。"""
    service = JointLabService(MemoryEventStore())
    output: dict[str, Any] = {"steps": []}

    def step(title: str, payload: Any) -> None:
        output["steps"].append({"step": title, "result": payload})

    service.create_lab("LAB-01", "天津大学智能机器人联合实验室")
    service.register_party("TJU", "天津大学研究院", "school")
    service.register_party("ROBOTCO", "整机厂", "manufacturer")
    service.register_party("SCENECO", "应用单位", "applicant")
    service.create_program(
        "PRG-ROBOT",
        "具身智能关节与算法协同计划",
        "联合研发机器人关节模组、控制算法与场景数据闭环",
        ["TJU", "ROBOTCO", "SCENECO"],
        budget=1_200_000.0,
    )
    for code, party, name in [
        ("P-TJU", "TJU", "张老师"),
        ("P-ROBOT", "ROBOTCO", "李工"),
        ("P-SCENE", "SCENECO", "王经理"),
        ("P-INTERN", "TJU", "实习生小陈"),
    ]:
        service.add_person(code, party, name)

    service.create_work_package(
        "WP1",
        "PRG-ROBOT",
        "运动控制算法与关节模组集成",
        "TJU",
        dependencies=frozenset(),
        budget=800_000.0,
        responsibilities=(
            ("TJU", "提供控制算法与评测"),
            ("ROBOTCO", "提供关节模组与整机集成"),
            ("SCENECO", "提供场景数据与试验环境"),
        ),
        deliverables=("算法软件包", "模组接口规范", "场景数据集说明"),
    )
    step("立项：合作计划与工作包（目标/依赖/预算/责任/交付物）", {"package": "WP1"})

    submit = service.submit_achievement(
        "ACH-CTRL",
        "WP1",
        "力位混合控制算法 v1",
        [
            {"party_code": "TJU", "person_code": "P-TJU", "kind": "algorithm", "description": "控制算法"},
            {"party_code": "ROBOTCO", "person_code": "P-ROBOT", "kind": "joint_module", "description": "关节模组参数"},
            {"party_code": "SCENECO", "person_code": "P-SCENE", "kind": "scene_data", "description": "产线场景数据"},
        ],
        "confidential",
        "联合发明，三方共有；对外许可需一致同意",
        {"scope_type": "named_parties", "allowed_parties": ["TJU", "ROBOTCO", "SCENECO"]},
        submitted_by="P-TJU",
    )
    step("提交成果：贡献来源/保密级别/知识产权约定/使用范围", {"version": submit.version})

    for party, person in [("TJU", "P-TJU"), ("ROBOTCO", "P-ROBOT"), ("SCENECO", "P-SCENE")]:
        service.technical_review("ACH-CTRL", party, person, True, "技术指标达标")
    step("技术验收：三家机构一致通过", {"state": service.get_achievement("ACH-CTRL").state.value})

    for party, person in [("TJU", "P-TJU"), ("ROBOTCO", "P-ROBOT"), ("SCENECO", "P-SCENE")]:
        service.rights_vote("MS-2026-01", "ACH-CTRL", party, person, True, "同意权利约定")
    conclusion = service.get_conclusion("MS-2026-01")
    step("跨机构里程碑权利确认：只能形成一个结论", {"approved": conclusion.approved, "votes": len(conclusion.votes)})

    service.publish("ACH-CTRL")
    decision = service.request_access("P-TJU", "ACH-CTRL")
    step("发布后授权符合条件的成员使用", decision.to_dict())

    before = service.request_access("P-INTERN", "ACH-CTRL")
    service.person_left("P-INTERN", "实习期满离组")
    after = service.request_access("P-INTERN", "ACH-CTRL")
    step("人员离组：后续访问立即关闭，历史授权仍保留", {"before_leave": before.to_dict(), "after_leave": after.to_dict()})

    service.withdraw_program("PRG-ROBOT", "SCENECO", "业务调整退出")
    after_withdraw = service.request_access("P-SCENE", "ACH-CTRL")
    step("机构退出：其成员后续访问立即关闭", {"after_withdraw": after_withdraw.to_dict()})

    service.join_program("PRG-ROBOT", "SCENECO", "重新提供场景数据与试验环境")
    service.declare_conflict("P-SCENE", "PRG-ROBOT", "配偶任职于竞争企业")
    during_conflict = service.request_access("P-SCENE", "ACH-CTRL")
    service.clear_conflict("P-SCENE", "PRG-ROBOT")
    after_clear = service.request_access("P-SCENE", "ACH-CTRL")
    step("利益冲突：申报即阻断，解除后恢复", {"during": during_conflict.to_dict(), "after": after_clear.to_dict()})

    service.submit_achievement(
        "ACH-CTRL",
        "WP1",
        "力位混合控制算法 v2",
        [
            {"party_code": "TJU", "person_code": "P-TJU", "kind": "algorithm", "description": "改进控制算法"},
            {"party_code": "SCENECO", "person_code": "P-SCENE", "kind": "scene_data", "description": "新增场景数据"},
        ],
        "confidential",
        "联合发明，三方共有；对外许可需一致同意",
        {"scope_type": "all_participants", "allowed_parties": []},
        submitted_by="P-TJU",
        supersedes=1,
    )
    for party, person in [("TJU", "P-TJU"), ("ROBOTCO", "P-ROBOT"), ("SCENECO", "P-SCENE")]:
        service.technical_review("ACH-CTRL", party, person, True, "v2 技术指标达标")
    for party, person in [("TJU", "P-TJU"), ("ROBOTCO", "P-ROBOT"), ("SCENECO", "P-SCENE")]:
        service.rights_vote("MS-2026-02", "ACH-CTRL", party, person, True, "同意 v2 权利约定")
    service.publish("ACH-CTRL")
    old_access = service.request_access("P-TJU", "ACH-CTRL", version=1)
    step("成果替换：v1 不再放行新访问，但授权历史仍在", {"v1_access": old_access.to_dict(), "grants_kept": len(service.get_grants("ACH-CTRL"))})

    service.freeze("ACH-CTRL", "模组供应权属存在争议")
    frozen_access = service.request_access("P-ROBOT", "ACH-CTRL", version=2)
    service.resolve_dispute("ACH-CTRL", "经协商确认模组供应权属归整机厂")
    resolved_access = service.request_access("P-ROBOT", "ACH-CTRL", version=2)
    step("争议冻结：冻结期间阻断一切后续访问，解决后恢复", {"frozen": frozen_access.to_dict(), "resolved": resolved_access.to_dict()})

    output["trace"] = service.trace("ACH-CTRL")
    output["grant_history_count"] = len(service.get_grants())
    output["event_count"] = len(service.event_history())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            _print(run_demo())
            return 0

        if args.command == "serve":
            from .api import serve

            serve(host=args.host, port=args.port, event_path=args.db)
            return 0

        service = _load_service(args.db)
        cmd = args.command

        if cmd == "init-lab":
            _print(_event_info(service.create_lab(args.code, args.name)))
        elif cmd == "add-party":
            _print(_event_info(service.register_party(args.code, args.name, args.kind)))
        elif cmd == "add-program":
            event = service.create_program(
                args.code, args.name, args.objectives, [p for p in args.parties.split(",") if p], args.budget
            )
            _print(_event_info(event))
        elif cmd == "program-join":
            _print(_event_info(service.join_program(args.program, args.party, args.responsibility)))
        elif cmd == "program-withdraw":
            _print(_event_info(service.withdraw_program(args.program, args.party, args.reason)))
        elif cmd == "add-person":
            _print(_event_info(service.add_person(args.code, args.party, args.name)))
        elif cmd == "person-leave":
            _print(_event_info(service.person_left(args.code, args.reason)))
        elif cmd == "declare-conflict":
            _print(_event_info(service.declare_conflict(args.code, args.program, args.description)))
        elif cmd == "clear-conflict":
            _print(_event_info(service.clear_conflict(args.code, args.program)))
        elif cmd == "add-package":
            responsibilities = tuple(
                tuple(item.split(":", 1)) for item in args.responsibility  # type: ignore[arg-type]
            )
            event = service.create_work_package(
                args.code,
                args.program,
                args.name,
                args.lead,
                dependencies=[d for d in args.depends.split(",") if d],
                budget=args.budget,
                responsibilities=responsibilities,
                deliverables=args.deliverable,
            )
            _print(_event_info(event))
        elif cmd == "submit":
            scope = {"scope_type": args.scope}
            if args.scope == "named_parties":
                scope["allowed_parties"] = [p for p in args.allowed.split(",") if p]
            event = service.submit_achievement(
                args.code,
                args.package,
                args.title,
                [_parse_contribution(raw) for raw in args.contribution],
                args.confidentiality,
                args.ip,
                scope,
                args.by,
                args.supersedes,
            )
            _print({**_event_info(event), "version": event.version})
        elif cmd == "tech-vote":
            event = service.technical_review(
                args.achievement, args.party, args.person, _vote_choice(args), args.comment
            )
            _print(_event_info(event))
        elif cmd == "rights-vote":
            event = service.rights_vote(
                args.milestone, args.achievement, args.party, args.person, _vote_choice(args), args.comment
            )
            _print(_event_info(event))
        elif cmd == "publish":
            _print(_event_info(service.publish(args.achievement)))
        elif cmd == "access":
            _print(service.request_access(args.person, args.achievement, args.version).to_dict())
        elif cmd == "freeze":
            _print(_event_info(service.freeze(args.target, args.reason)))
        elif cmd == "resolve":
            _print(_event_info(service.resolve_dispute(args.target, args.resolution)))
        elif cmd == "show":
            _print(_achievement_dict(service.get_achievement(args.achievement, args.version)))
        elif cmd == "grants":
            _print({"grants": [to_jsonable(g) for g in service.get_grants(args.achievement)]})
        elif cmd == "conclusion":
            _print(to_jsonable(service.get_conclusion(args.milestone)))
        elif cmd == "trace":
            _print({"achievement_code": args.achievement, "timeline": service.trace(args.achievement)})
        elif cmd == "events":
            from .service import _event_detail

            _print(
                {
                    "events": [
                        {"seq": e.seq, "type": type(e).__name__, "data": _event_detail(e)}
                        for e in service.event_history()
                    ]
                }
            )
        else:  # pragma: no cover
            parser.error(f"未知命令：{cmd}")
        return 0
    except DomainError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
