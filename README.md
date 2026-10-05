# 校企联合实验室成果协同

本项目实现校企联合实验室的成果协同服务：以合作计划和工作包组织目标、依赖、预算、参与方责任及交付物；成果提交时记录贡献来源、保密级别、知识产权约定和可使用范围；经过技术验收与权利确认后才发布给符合条件的成员。成员加入、退出、利益冲突、成果替换和争议冻结会即时改变后续访问结论，而历史使用依据保存在追加式事件账本（哈希链）中不被改写。跨机构里程碑确认只能形成一个结论。管理方可以通过测试、API 或命令行追踪一项成果从立项、评审到授权使用的完整过程。

纯 Python 标准库实现，不依赖浏览器、外部数据库或其他运行服务。

## 运行环境

- Python 3.11 或更高版本
- Linux、macOS 或 Windows

## 运行测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 编译检查

```bash
python3 -m compileall -q src tests run_cli.py
```

## 命令行

不带参数运行端到端示例（不写存储文件）：

```bash
python3 run_cli.py
```

完整用法见 `python3 run_cli.py --help`。所有写命令通过 `--store` 指定账本文件（默认 `joint_lab_store.json`），状态在多次调用间持久化。典型流程：

```bash
S=--store\ joint_lab_store.json
python3 run_cli.py add-party --party-id univ --name 天津大学研究院 --kind university $S
python3 run_cli.py add-party --party-id oem  --name 关节模组整机厂 --kind enterprise $S
python3 run_cli.py create-plan --plan-id p1 --title 共建计划 --goal 形成可复用成果 \
    --budget 1000 --party univ:算法研发:500 --party oem:模组研制:400 $S
python3 run_cli.py add-work-package --plan-id p1 --wp-id w1 --title 感知控制 \
    --objective 完成算法库 --budget 700 --resp univ:算法 --resp oem:模组 --deliverable d1:算法库 $S
python3 run_cli.py add-milestone --wp-id w1 --milestone-id m1 --name 中期检查 $S
python3 run_cli.py confirm-milestone --milestone-id m1 --party-id univ --decision approve $S
python3 run_cli.py confirm-milestone --milestone-id m1 --party-id oem  --decision approve $S
python3 run_cli.py add-member --member-id u1 --party-id oem --name 模组工程师 --clearance 2 $S
python3 run_cli.py submit-achievement --achievement-id a1 --wp-id w1 --title 控制算法 --summary 摘要 \
    --contribution univ:算法:控制律 --contribution oem:关节模组:硬件接口 \
    --confidentiality 2 --ipr-owners univ oem --ipr-license 共建方共有 --fulfills d1 $S
python3 run_cli.py tech-acceptance      --achievement-id a1 --passed $S
python3 run_cli.py rights-confirmation  --achievement-id a1 --confirmed $S
python3 run_cli.py publish              --achievement-id a1 $S
python3 run_cli.py check-access --member-id u1 --achievement-id a1 --purpose 集成使用 $S
python3 run_cli.py trace --achievement-id a1 $S   # 追踪立项→评审→授权使用全过程
python3 run_cli.py verify $S                      # 校验账本哈希链
```

其他命令：`withdraw-member`、`declare-coi` / `lift-coi`、`freeze` / `resolve-dispute`、`replace`、`access-history`、`show`、`serve`。

## JSON API

```bash
python3 run_cli.py serve --host 127.0.0.1 --port 8080 --store joint_lab_store.json
```

主要端点（POST 除标注外均为写操作，成功写操作后自动落盘）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/parties`、`/members`、`/plans` | 登记机构、成员、合作计划 |
| POST | `/plans/{id}/work-packages`、`/work-packages/{id}/milestones` | 工作包与里程碑 |
| POST | `/milestones/{id}/confirmations` | 机构确认里程碑（结论唯一） |
| POST | `/achievements` | 提交成果（贡献来源、保密级别、知识产权、可使用范围） |
| POST | `/achievements/{id}/tech-acceptance`、`/rights-confirmation`、`/publish` | 技术验收、权利确认、发布 |
| POST | `/achievements/{id}/freeze`、`/resolve`、`/replace` | 争议冻结、解除、成果替换 |
| POST | `/members/{id}/withdraw`、`/conflicts`、`/conflicts/{id}/lift` | 成员退出、利益冲突申报与解除 |
| POST | `/access/checks`、`/access/history` | 访问评估与留痕查询 |
| GET  | `/achievements/{id}`、`/achievements/{id}/trace`、`/milestones/{id}`、`/ledger/verify`、`/health` | 状态与追溯查询 |

## 领域规则要点

- **发布门禁**：成果状态机为 `submitted → tech_accepted → rights_confirmed → published`，验收或确认不通过进入 `rejected`；只有 `published` 且未冻结、未被替换的成果才可访问。里程碑完成不等于成果开放。
- **访问评估**：每次访问实时评估——成员在职、成员密级不低于成果保密级别（1 内部 / 2 机密 / 3 秘密）、所在机构在可使用范围内、无未解除的利益冲突；结论（含拒绝原因）写入账本，成为不可改写的历史使用依据。
- **动态生效**：成员退出、利益冲突申报、成果替换、争议冻结立即改变后续访问；历史授权记录保留在账本中，可通过 `access-history` 与 `trace` 复查。
- **里程碑唯一结论**：全部确认方投票后形成 `achieved` / `not_achieved`（任一否决即未通过），结论形成后拒绝任何追加确认，账本中只存在一条结论事件。
- **预算约束**：参与方预算份额之和不超过计划总预算；工作包预算累计不超过计划剩余预算；依赖仅限同一计划内的工作包且不能依赖自身。

## 目录结构

```
src/joint_lab/
  contracts.py   # 基础领域契约（既有起点）
  errors.py      # 领域错误类型
  model.py       # 实体、状态机与保密级别
  events.py      # 追加式事件账本（哈希链）
  service.py     # 命令、状态流转、访问评估与追溯
  api.py         # 标准库 JSON API
  cli.py         # 命令行入口
tests/           # 服务、账本、API、CLI 与基础契约测试
run_cli.py       # 命令行启动脚本
```
