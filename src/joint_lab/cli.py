"""校企联合实验室成果协同命令行：管理方可以追踪成果从立项、评审到授权使用的全过程。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .api import serve as api_serve
from .errors import DomainError
from .model import PARTY_KINDS
from .service import CollaborationService

DEFAULT_STORE = os.environ.get("JOINT_LAB_STORE", "joint_lab_store.json")


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _load(args: argparse.Namespace) -> CollaborationService:
    path = Path(args.store)
    if path.exists():
        return CollaborationService.load(path)
    return CollaborationService()


def _mutate(args: argparse.Namespace, operation) -> int:
    service = _load(args)
    result = operation(service) or {}
    service.save(args.store)
    _print({"ok": True, **result})
    return 0


# ---------------------------------------------------------------------------
# 参数解析辅助
# ---------------------------------------------------------------------------


def _parse_plan_party(spec: str) -> dict:
    parts = spec.split(":")
    if len(parts) != 3:
        raise DomainError(f"参与方格式应为 机构标识:责任:预算份额，收到：{spec}")
    party_id, responsibility, share_text = parts
    try:
        share = float(share_text)
    except ValueError:
        raise DomainError(f"预算份额必须是数字：{spec}") from None
    return {"party_id": party_id, "responsibility": responsibility, "budget_share": share}


def _parse_responsibility(spec: str) -> tuple[str, str]:
    parts = spec.split(":", 1)
    if len(parts) != 2:
        raise DomainError(f"责任格式应为 机构标识:责任说明，收到：{spec}")
    return parts[0], parts[1]


def _parse_deliverable(spec: str) -> dict:
    parts = spec.split(":", 2)
    if len(parts) < 2:
        raise DomainError(f"交付物格式应为 标识:名称[:说明]，收到：{spec}")
    return {
        "deliverable_id": parts[0],
        "name": parts[1],
        "description": parts[2] if len(parts) > 2 else "",
    }


def _parse_contribution(spec: str) -> dict:
    parts = spec.split(":", 2)
    if len(parts) != 3:
        raise DomainError(f"贡献格式应为 机构标识:类型:说明，收到：{spec}")
    return {"party_id": parts[0], "kind": parts[1], "description": parts[2]}


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def cmd_add_party(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.register_party(party_id=args.party_id, name=args.name, kind=args.kind)
        return {"party_id": args.party_id}

    return _mutate(args, op)


def cmd_add_member(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.add_member(member_id=args.member_id, party_id=args.party_id, name=args.name, clearance=args.clearance)
        return {"member_id": args.member_id}

    return _mutate(args, op)


def cmd_withdraw_member(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.withdraw_member(member_id=args.member_id)
        return {"member_id": args.member_id}

    return _mutate(args, op)


def cmd_declare_coi(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.declare_conflict(
            coi_id=args.coi_id,
            member_id=args.member_id,
            achievement_id=args.achievement_id,
            party_id=args.party_id,
            reason=args.reason or "",
        )
        return {"coi_id": args.coi_id}

    return _mutate(args, op)


def cmd_lift_coi(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.lift_conflict(coi_id=args.coi_id)
        return {"coi_id": args.coi_id}

    return _mutate(args, op)


def cmd_create_plan(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.create_plan(
            plan_id=args.plan_id,
            title=args.title,
            goals=args.goal,
            total_budget=args.budget,
            parties=[_parse_plan_party(spec) for spec in args.party],
        )
        return {"plan_id": args.plan_id}

    return _mutate(args, op)


def cmd_add_work_package(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        responsibilities = dict(_parse_responsibility(spec) for spec in args.resp)
        service.add_work_package(
            plan_id=args.plan_id,
            wp_id=args.wp_id,
            title=args.title,
            objectives=args.objective,
            depends_on=args.depends_on,
            budget=args.budget,
            responsibilities=responsibilities,
            deliverables=[_parse_deliverable(spec) for spec in args.deliverable],
        )
        return {"wp_id": args.wp_id}

    return _mutate(args, op)


def cmd_add_milestone(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.add_milestone(
            wp_id=args.wp_id,
            milestone_id=args.milestone_id,
            name=args.name,
            required_parties=args.required or None,
        )
        return {"milestone_id": args.milestone_id}

    return _mutate(args, op)


def cmd_confirm_milestone(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        conclusion = service.confirm_milestone(
            milestone_id=args.milestone_id,
            party_id=args.party_id,
            approve=args.decision == "approve",
            note=args.note or "",
        )
        return {"milestone_id": args.milestone_id, "conclusion": conclusion}

    return _mutate(args, op)


def cmd_submit_achievement(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        if args.scope_parties:
            usage_scope = {"kind": "parties", "party_ids": args.scope_parties}
        else:
            usage_scope = {"kind": "plan", "party_ids": []}
        service.submit_achievement(
            achievement_id=args.achievement_id,
            wp_id=args.wp_id,
            title=args.title,
            summary=args.summary,
            contributions=[_parse_contribution(spec) for spec in args.contribution],
            confidentiality=args.confidentiality,
            ipr={
                "owner_party_ids": args.ipr_owners,
                "license": args.ipr_license,
                "notes": args.ipr_notes or "",
            },
            usage_scope=usage_scope,
            fulfills=args.fulfills,
        )
        return {"achievement_id": args.achievement_id}

    return _mutate(args, op)


def cmd_tech_acceptance(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.record_technical_acceptance(
            achievement_id=args.achievement_id, passed=args.passed, notes=args.notes or "", reviewer=args.reviewer or ""
        )
        return {"achievement_id": args.achievement_id, "state": service.achievement_view(args.achievement_id)["state"]}

    return _mutate(args, op)


def cmd_rights_confirmation(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.confirm_rights(
            achievement_id=args.achievement_id,
            confirmed=args.confirmed,
            notes=args.notes or "",
            confirmer=args.confirmer or "",
        )
        return {"achievement_id": args.achievement_id, "state": service.achievement_view(args.achievement_id)["state"]}

    return _mutate(args, op)


def cmd_publish(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.publish_achievement(achievement_id=args.achievement_id)
        return {"achievement_id": args.achievement_id}

    return _mutate(args, op)


def cmd_freeze(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.freeze_achievement(achievement_id=args.achievement_id, reason=args.reason, operator=args.operator or "")
        return {"achievement_id": args.achievement_id}

    return _mutate(args, op)


def cmd_resolve_dispute(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.resolve_dispute(achievement_id=args.achievement_id, resolution=args.resolution or "")
        return {"achievement_id": args.achievement_id}

    return _mutate(args, op)


def cmd_replace(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        service.replace_achievement(old_achievement_id=args.old_id, new_achievement_id=args.new_id)
        return {"achievement_id": args.old_id, "new_achievement_id": args.new_id}

    return _mutate(args, op)


def cmd_check_access(args: argparse.Namespace) -> int:
    def op(service: CollaborationService) -> dict:
        decision = service.check_access(
            member_id=args.member_id, achievement_id=args.achievement_id, purpose=args.purpose or ""
        )
        return {"decision": decision.to_dict()}

    return _mutate(args, op)


def cmd_trace(args: argparse.Namespace) -> int:
    service = _load(args)
    events = service.trace_achievement(args.achievement_id)
    if args.format == "text":
        for event in events:
            data = json.dumps(event["data"], ensure_ascii=False, sort_keys=True)
            print(f"#{event['seq']} [{event['at']}] {event['type']} {data}")
    else:
        _print({"ok": True, "achievement_id": args.achievement_id, "events": events})
    return 0


def cmd_access_history(args: argparse.Namespace) -> int:
    service = _load(args)
    records = service.access_history(member_id=args.member_id, achievement_id=args.achievement_id)
    _print({"ok": True, "records": records})
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    service = _load(args)
    _print({"ok": True, "achievement": service.achievement_view(args.achievement_id)})
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    service = _load(args)
    _print({"ok": True, "valid": service.verify(), "events": len(service.ledger)})
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    service = _load(args)
    api_serve(service, host=args.host, port=args.port, on_change=lambda: service.save(args.store))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    _print(run_demo())
    return 0


# ---------------------------------------------------------------------------
# 端到端示例：对应题目场景（算法、关节模组、场景数据三方共建）
# ---------------------------------------------------------------------------


def run_demo() -> dict:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ticks = {"n": 0}

    def clock() -> str:
        ticks["n"] += 1
        return (base + timedelta(seconds=ticks["n"])).isoformat()

    service = CollaborationService(clock=clock)
    service.register_party(party_id="univ", name="天津大学研究院", kind="university")
    service.register_party(party_id="oem", name="关节模组整机厂", kind="enterprise")
    service.register_party(party_id="app", name="场景应用单位", kind="application_unit")

    service.create_plan(
        plan_id="plan-demo",
        title="校企联合实验室共建计划",
        goals=["形成可复用的机器人控制成果"],
        total_budget=1200.0,
        parties=[
            {"party_id": "univ", "responsibility": "控制算法研发", "budget_share": 500.0},
            {"party_id": "oem", "responsibility": "关节模组研制", "budget_share": 400.0},
            {"party_id": "app", "responsibility": "场景数据与验证", "budget_share": 300.0},
        ],
    )
    service.add_work_package(
        plan_id="plan-demo",
        wp_id="wp-algo",
        title="感知与控制",
        objectives=["完成控制算法库"],
        budget=700.0,
        responsibilities={"univ": "算法设计", "oem": "模组接口"},
        deliverables=[{"deliverable_id": "d-algo", "name": "控制算法库"}],
    )
    service.add_work_package(
        plan_id="plan-demo",
        wp_id="wp-scene",
        title="场景验证",
        objectives=["完成场景数据集验证"],
        depends_on=["wp-algo"],
        budget=400.0,
        responsibilities={"app": "场景数据"},
    )
    service.add_milestone(wp_id="wp-algo", milestone_id="ms-mid", name="中期检查")
    service.confirm_milestone(milestone_id="ms-mid", party_id="univ", approve=True, note="算法达标")
    conclusion = service.confirm_milestone(milestone_id="ms-mid", party_id="oem", approve=True, note="接口联调通过")

    service.add_member(member_id="m-univ", party_id="univ", name="算法工程师", clearance=3)
    service.add_member(member_id="m-oem", party_id="oem", name="模组工程师", clearance=2)
    service.add_member(member_id="m-app", party_id="app", name="数据专员", clearance=1)

    service.submit_achievement(
        achievement_id="ach-demo",
        wp_id="wp-algo",
        title="机器人关节控制算法",
        summary="融合算法、关节模组与场景数据的控制成果",
        contributions=[
            {"party_id": "univ", "kind": "算法", "description": "控制律与实现"},
            {"party_id": "oem", "kind": "关节模组", "description": "硬件接口与标定"},
            {"party_id": "app", "kind": "场景数据", "description": "验证数据集"},
        ],
        confidentiality=2,
        ipr={"owner_party_ids": ["univ", "oem"], "license": "共建方共有，按计划范围授权使用"},
        usage_scope={"kind": "plan", "party_ids": []},
        fulfills=["d-algo"],
    )

    decisions = []
    # 里程碑已完成但成果尚未发布：访问仍被拒绝
    decisions.append(service.check_access(member_id="m-oem", achievement_id="ach-demo", purpose="中期查阅").to_dict())

    service.record_technical_acceptance(achievement_id="ach-demo", passed=True, reviewer="技术委员会")
    service.confirm_rights(achievement_id="ach-demo", confirmed=True, confirmer="知识产权专员")
    service.publish_achievement(achievement_id="ach-demo")

    decisions.append(service.check_access(member_id="m-oem", achievement_id="ach-demo", purpose="集成使用").to_dict())
    decisions.append(service.check_access(member_id="m-app", achievement_id="ach-demo", purpose="场景验证").to_dict())

    # 成员退出后：后续访问立即被拒绝，历史授权记录保留在账本中
    service.withdraw_member(member_id="m-oem")
    decisions.append(service.check_access(member_id="m-oem", achievement_id="ach-demo", purpose="退出后查阅").to_dict())

    return {
        "scenario": "校企联合实验室成果协同端到端示例",
        "milestone_conclusion": conclusion,
        "access_checks": decisions,
        "trace_length": len(service.trace_achievement("ach-demo")),
        "ledger_valid": service.verify(),
    }


# ---------------------------------------------------------------------------
# 参数解析器
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", default=DEFAULT_STORE, help="账本存储文件路径")

    parser = argparse.ArgumentParser(prog="joint-lab", description="校企联合实验室成果协同服务命令行")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", parents=[common], help="运行端到端示例（不写存储文件）")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("add-party", parents=[common], help="登记参与机构")
    p.add_argument("--party-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--kind", default="other", choices=list(PARTY_KINDS))
    p.set_defaults(func=cmd_add_party)

    p = sub.add_parser("add-member", parents=[common], help="登记机构成员")
    p.add_argument("--member-id", required=True)
    p.add_argument("--party-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--clearance", type=int, default=1, choices=[1, 2, 3])
    p.set_defaults(func=cmd_add_member)

    p = sub.add_parser("withdraw-member", parents=[common], help="成员退出，后续访问立即失效")
    p.add_argument("--member-id", required=True)
    p.set_defaults(func=cmd_withdraw_member)

    p = sub.add_parser("declare-coi", parents=[common], help="申报利益冲突")
    p.add_argument("--coi-id", required=True)
    p.add_argument("--member-id", required=True)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--achievement-id")
    target.add_argument("--party-id")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_declare_coi)

    p = sub.add_parser("lift-coi", parents=[common], help="解除利益冲突")
    p.add_argument("--coi-id", required=True)
    p.set_defaults(func=cmd_lift_coi)

    p = sub.add_parser("create-plan", parents=[common], help="创建合作计划")
    p.add_argument("--plan-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--goal", action="append", required=True, help="计划目标，可多次指定")
    p.add_argument("--budget", type=float, required=True, help="计划总预算")
    p.add_argument("--party", action="append", required=True, metavar="机构:责任:份额", help="参与方，可多次指定")
    p.set_defaults(func=cmd_create_plan)

    p = sub.add_parser("add-work-package", parents=[common], help="在计划下新增工作包")
    p.add_argument("--plan-id", required=True)
    p.add_argument("--wp-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--objective", action="append", required=True, help="工作包目标，可多次指定")
    p.add_argument("--depends-on", nargs="*", default=[], help="依赖的工作包标识")
    p.add_argument("--budget", type=float, required=True)
    p.add_argument("--resp", action="append", required=True, metavar="机构:责任", help="责任方，可多次指定")
    p.add_argument("--deliverable", action="append", default=[], metavar="标识:名称[:说明]")
    p.set_defaults(func=cmd_add_work_package)

    p = sub.add_parser("add-milestone", parents=[common], help="为工作包新增里程碑")
    p.add_argument("--wp-id", required=True)
    p.add_argument("--milestone-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--required", nargs="*", default=[], help="确认方机构标识，缺省为工作包责任方")
    p.set_defaults(func=cmd_add_milestone)

    p = sub.add_parser("confirm-milestone", parents=[common], help="机构确认里程碑")
    p.add_argument("--milestone-id", required=True)
    p.add_argument("--party-id", required=True)
    p.add_argument("--decision", choices=["approve", "reject"], required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_confirm_milestone)

    p = sub.add_parser("submit-achievement", parents=[common], help="提交成果")
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--wp-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--contribution", action="append", required=True, metavar="机构:类型:说明")
    p.add_argument("--confidentiality", type=int, choices=[1, 2, 3], required=True)
    p.add_argument("--ipr-owners", nargs="+", required=True, help="知识产权归属机构")
    p.add_argument("--ipr-license", required=True, help="知识产权许可方式")
    p.add_argument("--ipr-notes", default="")
    p.add_argument("--scope-parties", nargs="*", default=[], help="可使用范围机构，缺省为计划内全部机构")
    p.add_argument("--fulfills", nargs="*", default=[], help="兑现的交付物标识")
    p.set_defaults(func=cmd_submit_achievement)

    p = sub.add_parser("tech-acceptance", parents=[common], help="技术验收")
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--passed", action="store_true", help="验收通过")
    p.add_argument("--failed", action="store_true", help="验收不通过")
    p.add_argument("--notes", default="")
    p.add_argument("--reviewer", default="")
    p.set_defaults(func=cmd_tech_acceptance)

    p = sub.add_parser("rights-confirmation", parents=[common], help="权利确认")
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--confirmed", action="store_true", help="确认通过")
    p.add_argument("--rejected", action="store_true", help="确认不通过")
    p.add_argument("--notes", default="")
    p.add_argument("--confirmer", default="")
    p.set_defaults(func=cmd_rights_confirmation)

    p = sub.add_parser("publish", parents=[common], help="发布成果")
    p.add_argument("--achievement-id", required=True)
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("freeze", parents=[common], help="争议冻结成果")
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--operator", default="")
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("resolve-dispute", parents=[common], help="解除争议冻结")
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--resolution", default="")
    p.set_defaults(func=cmd_resolve_dispute)

    p = sub.add_parser("replace", parents=[common], help="以新成果替换旧成果")
    p.add_argument("--old-id", required=True)
    p.add_argument("--new-id", required=True)
    p.set_defaults(func=cmd_replace)

    p = sub.add_parser("check-access", parents=[common], help="评估成员对成果的访问")
    p.add_argument("--member-id", required=True)
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--purpose", default="")
    p.set_defaults(func=cmd_check_access)

    p = sub.add_parser("trace", parents=[common], help="追踪成果从立项到授权使用的全过程")
    p.add_argument("--achievement-id", required=True)
    p.add_argument("--format", choices=["json", "text"], default="text")
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("access-history", parents=[common], help="查询访问评估留痕")
    p.add_argument("--member-id")
    p.add_argument("--achievement-id")
    p.set_defaults(func=cmd_access_history)

    p = sub.add_parser("show", parents=[common], help="查看成果当前状态")
    p.add_argument("--achievement-id", required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("verify", parents=[common], help="校验账本哈希链完整性")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("serve", parents=[common], help="启动 JSON API 服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        args_list = ["demo"]
    args = build_parser().parse_args(args_list)
    if getattr(args, "command", None) in ("tech-acceptance",):
        if args.passed == args.failed:
            print("必须且只能指定 --passed 或 --failed", file=sys.stderr)
            return 2
    if getattr(args, "command", None) in ("rights-confirmation",):
        if args.confirmed == args.rejected:
            print("必须且只能指定 --confirmed 或 --rejected", file=sys.stderr)
            return 2
    try:
        return args.func(args)
    except (DomainError, ValueError, OSError) as exc:
        payload = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 1
