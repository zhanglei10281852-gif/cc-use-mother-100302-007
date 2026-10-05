"""校企联合实验室成果协同命令行冒烟入口。

运行端到端演示场景，确认领域服务、事件历史与追踪链路可以正常加载执行。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from joint_lab.cli import run_demo


def main() -> None:
    result = run_demo()
    summary = {
        "steps": len(result["steps"]),
        "events": result["event_count"],
        "grants": result["grant_history_count"],
        "trace_entries": len(result["trace"]),
        "first_trace_stage": result["trace"][0]["stage"],
        "last_trace_stage": result["trace"][-1]["stage"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
