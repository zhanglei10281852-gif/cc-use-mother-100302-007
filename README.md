# 校企联合实验室成果协同

面向校企联合实验室的成果协同服务：以**合作计划 / 工作包**组织目标、依赖、预算、参与方责任与交付物；成果提交时记录**贡献来源、保密级别、知识产权约定与可使用范围**；只有通过**技术验收**与跨机构**权利确认**两道闸门后才能发布；发布后系统在每次访问时按成员关系、利益冲突、成果替换与争议冻结等**当前状态**重新判定授权。

服务采用**事件溯源**：所有状态变化都是不可变事件，完整追加到事件历史。授权记录一旦生成便永久保存（历史使用依据不被破坏），而人员离组、机构退出、利益冲突、成果替换、争议冻结只改变"此后"的访问判定。

## 领域规则

- **计划与工作包**：工作包声明目标、前置依赖（必须存在且同属一个计划、不能自依赖）、预算（非负）、各机构责任分工与交付物清单。
- **成果提交**：必须至少记录一项贡献来源（算法 / 关节模组 / 场景数据 / 其他）、保密级别（public/internal/confidential）、知识产权约定与使用范围（全体参与方或指定机构）；提交人须为在组、未退出该计划且无未解除利益冲突的成员。
- **双闸门发布**：技术验收由各参与机构各投一票、一致同意才通过；权利确认以跨机构里程碑形式表决，同样一致同意才通过；两道闸门都通过才允许发布。
- **里程碑唯一结论**：同一里程碑只能绑定同一成果版本、每机构一票，投票齐了只形成一个结论，结论形成后不得再投或更改；权利确认被否后，只能另立新里程碑重新确认。
- **动态访问控制**：发布后每次访问都重新判定——人员离组 / 机构退出 / 利益冲突未解除 / 机构不在使用范围内 / 版本已被替换 / 成果或其工作包、计划处于争议冻结中，任一条件不满足即拒绝；同时留下 `AccessChecked` 审计事件。
- **历史不被破坏**：`GrantIssued` 授权记录只追加不删除；成果替换采用新版本（只能替换最新版本、必须声明 `supersedes`），旧版本标记为 `superseded` 但历史授权仍可查询。
- **争议冻结**：可冻结计划、工作包或成果；冻结期间阻断提交、评审与访问，解除后恢复，全过程进审计。
- **全链路追踪**：`trace` 按事件顺序给出某成果"立项 → 提交 → 技术验收 → 权利确认 → 发布 → 授权使用 → 争议"的完整过程。

## 运行环境

- Python 3.11 或更高版本，无第三方依赖（HTTP API 仅用标准库）
- Linux、macOS 或 Windows

## 运行测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

包含 28 个测试：领域规则、访问控制动态变化、里程碑唯一结论、JSONL 持久化重放、HTTP API 端到端流程。

## 编译检查

```bash
python3 -m compileall -q src tests run_cli.py
```

## 命令行

一键端到端演示（内存事件库，覆盖离组、退出、冲突、替换、冻结各场景）：

```bash
python3 run_cli.py                         # 输出演示摘要
PYTHONPATH=src python3 -m joint_lab.cli demo   # 输出完整演示明细
```

使用持久化事件文件操作（进程重启后状态完整恢复）：

```bash
export PYTHONPATH=src
DB="--db /path/to/events.jsonl"
python3 -m joint_lab.cli $DB init-lab --code LAB --name 联合实验室
python3 -m joint_lab.cli $DB add-party --code TJU --name 天津大学 --kind school
python3 -m joint_lab.cli $DB add-program --code P1 --name 协同计划 --parties TJU,CO --budget 1000000
python3 -m joint_lab.cli $DB add-person --code U1 --party TJU --name 张老师
python3 -m joint_lab.cli $DB add-package --code WP1 --program P1 --name 控制算法 --lead TJU \
    --depends "" --budget 800000 --responsibility TJU:算法 --responsibility CO:模组 --deliverable 算法包
python3 -m joint_lab.cli $DB submit --code A1 --package WP1 --title 力位混合控制 --by U1 \
    --confidentiality confidential --ip "联合发明，双方共有" --scope all_participants \
    --contribution TJU:U1:algorithm --contribution CO:U2:joint_module
python3 -m joint_lab.cli $DB tech-vote   --achievement A1 --party TJU --person U1 --approve
python3 -m joint_lab.cli $DB rights-vote --milestone M1 --achievement A1 --party TJU --person U1 --approve
python3 -m joint_lab.cli $DB publish --achievement A1
python3 -m joint_lab.cli $DB access --person U1 --achievement A1
python3 -m joint_lab.cli $DB person-leave --code U1 --reason 毕业离组
python3 -m joint_lab.cli $DB declare-conflict --code U2 --program P1 --description 亲属任职竞争企业
python3 -m joint_lab.cli $DB freeze --target A1 --reason 知识产权归属争议
python3 -m joint_lab.cli $DB trace --achievement A1      # 全链路追踪
python3 -m joint_lab.cli $DB events                      # 导出全部不可变事件
```

`python3 -m joint_lab.cli --help` 可查看全部命令（机构加入/退出计划、冲突解除、成果版本替换、争议解决、历史授权查询、里程碑结论查询等）。

## HTTP API

```bash
PYTHONPATH=src python3 -m joint_lab.cli --db events.jsonl serve --host 127.0.0.1 --port 8080
```

主要端点（均为 JSON）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/labs` `/parties` `/programs` `/persons` `/work-packages` | 建立实验室、登记机构、创建计划、人员入组、创建工作包 |
| POST | `/programs/{code}/join`、`/programs/{code}/withdraw` | 机构加入 / 退出计划 |
| POST | `/persons/{code}/leave` | 人员离组 |
| POST | `/persons/{code}/conflicts`、`/persons/{code}/conflicts-clear` | 申报 / 解除利益冲突 |
| POST | `/achievements` | 提交成果（含贡献、保密、知识产权、使用范围） |
| POST | `/achievements/{code}/technical-reviews` | 技术验收投票 |
| POST | `/achievements/{code}/rights-votes` | 跨机构里程碑权利确认投票 |
| POST | `/achievements/{code}/publish` | 双闸门通过后发布 |
| POST | `/access` | 按当前状态判定并记录授权 |
| POST | `/freezes`、`/freezes/{code}/resolve` | 争议冻结 / 解决 |
| GET | `/achievements/{code}` | 成果当前版本 |
| GET | `/achievements/{code}/conclusion/{milestone}` | 里程碑唯一结论 |
| GET | `/achievements/{code}/trace` | 立项→评审→授权使用完整追踪 |
| GET | `/grants`、`/grants/{code}` | 历史授权使用依据 |
| GET | `/events` | 不可变事件全历史 |

业务规则冲突返回 `409`，对象不存在返回 `404`。

## Python API

```python
from joint_lab import JointLabService, MemoryEventStore  # 或 JsonlEventStore

svc = JointLabService(MemoryEventStore())
svc.create_lab("LAB", "联合实验室")
# ... 登记机构、计划、人员、工作包、提交成果、验收、权利确认、发布 ...
decision = svc.request_access("U1", "A1")      # 每次访问按当前状态判定
timeline = svc.trace("A1")                      # 完整过程追踪
grants   = svc.get_grants("A1")                 # 历史使用依据永不删除
```

## 代码结构

```
src/joint_lab/
  contracts.py   # 稳定标识 / 指纹 / 冲突检测基础契约
  models.py      # 领域模型（计划、工作包、成果、使用范围、结论、授权、冻结等）
  events.py      # 不可变领域事件
  repository.py  # 事件存储（内存 / JSONL 持久化与重放）
  serializers.py # 枚举、值对象的 JSON 序列化
  service.py     # 核心领域服务：业务规则、状态重放、访问判定、全链路追踪
  api.py         # 标准库 HTTP API
  cli.py         # 命令行工具与端到端演示
```
