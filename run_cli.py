"""校企联合实验室成果协同命令行入口。

不带参数运行时执行端到端示例；完整用法见 `python run_cli.py --help`。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from joint_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
