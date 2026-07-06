# D3-T09 R阶段工程分层与 Task-as-Step 规范收敛

## 状态

in_progress。本任务是治理规则收敛 PR，用于在 D0–D3 数据产品层基本完成后，固定 R0–R6 研究实现层的工程分层规则，并将本仓库的 Step 治理口径收敛为 Task-as-Step。

## 目标

本任务更新阶段门禁和任务索引文档，明确 Task 是本仓库中 Step 的实现载体。D0–D3 作为 legacy data-product implementation layer，历史平铺式 `scripts/`、`tests/`、`schemas/`、`configs/` 与 `docs/tasks/` 结构暂时保留；从 R0 开始，R0–R6 作为 research implementation layer，新增实现必须按阶段分层。

## 非目标

本任务不移动、重命名或删除任何 D0–D3 历史 scripts、tests、schemas、configs 或 task 文件，不修改任何 D2/D3 数据契约语义，不修改 Python 运行逻辑，不修改 JSON Schema 内容，不生成或提交 `data/generated/`、DuckDB、parquet、manifest 或 research artifact，不开始 R0 指标实现，不创建 PCVT 指标、状态、标签、收益、回测或组合输出，不清理本地分支或本地数据目录。

## 修改范围

本任务修改 `docs/04_阶段与门禁框架.md`、`docs/03_可复现研究工程标准.md`、`docs/tasks/README.md`，新增本 task 文档，并通过 `python scripts/build_compendium.py` 重新生成根目录合订本。除合订本派生更新外，本 PR 仅修改文档。

## R 阶段目录规则

从 R0 起，R 阶段核心研究逻辑不得新增到根级 `scripts/*.py`。R 阶段代码应以 `src/r0`、`src/r1`、`src/r2`、`src/r3`、`src/r4`、`src/r5`、`src/r6` 等阶段目录为实现入口。R 阶段测试、schema 和 config 应与阶段分层保持一致，使用 `tests/r0`、`schemas/r0`、`configs/r0` 等对应目录。若某阶段尚无文件，可以不创建空目录；一旦新增 R 阶段实现文件，必须放入对应阶段目录。

如 R 阶段将来必须增加 CLI 或脚本入口，该入口只能是薄 wrapper，不得承载核心研究逻辑，也不得与 D 阶段既有 `scripts/*.py` 平铺入口混用。D0–D3 历史文件不因本规则失效，也不在本 PR 迁移。后续若要迁移 D 阶段历史文件，必须另开专门 refactor PR，且不得混入研究逻辑变化。

## task 命名规则

从 D3-T09 / R0 开始，branch 使用英文 slug；task 文件路径使用中文任务标题，可保留必要英文术语，例如 `Task-as-Step`、`PCVT`、`registry`；task H1 使用中文标题；PR 标题使用 `[codex] 阶段-任务号 中文标题`。

本任务固定以下示例：

```text
branch: codex/d3-t09-r-stage-engineering-layout-task-as-step-governance
task file path: docs/tasks/D3-T09_R阶段工程分层与Task-as-Step规范收敛.md
task H1: # D3-T09 R阶段工程分层与 Task-as-Step 规范收敛
PR title: [codex] D3-T09 R阶段工程分层与 Task-as-Step 规范收敛
```

`docs/tasks/` 继续平铺管理，不拆成阶段子目录。不批量重命名历史 task 文件；历史英文或中英混排 task 文件继续保留，除非未来单独开 rename-only PR。

## Gate 规则

一个 PR 只能实现一个 task。task 文档是 step 的最小可审核载体，但不得替代 run manifest、dataset manifest、artifact manifest、decision record 或 G0–G7 门禁证据。task 编号只表示阶段内执行顺序，不表示证据等级、冻结状态或研究结论强度。未通过门禁时 task 必须保持 `blocked`、`candidate`、`in_progress` 等对应状态，不得用后续成功追认前序失败。

## 验收标准

验收时必须确认 `docs/04_阶段与门禁框架.md` 第 6 节已改为 Task-as-Step 规则；文档明确 D0–D3 历史结构保留、R0–R6 从 R0 起严格阶段分层；`docs/tasks/README.md` 明确 branch、task path、task H1、PR title 命名规则；README 明确不批量重命名历史 task 文件；本 task 文档已新增；未移动、重命名或删除 D 阶段历史文件；未改动任何研究计算逻辑；未提交任何 generated data、DuckDB、parquet、manifest 或 R0 输出；合订本由脚本重新生成。

## 失败状态

若 PR 移动、重命名或删除 D0–D3 历史文件，修改 D2/D3 数据契约语义，改动 Python 运行逻辑，生成数据产物或启动 R0 指标实现，则本任务失败并应回退。若 validation 命令失败且不能证明与本 PR 文档改动无关，本任务不得合并。

## 回退方式

回退本 PR 对 `docs/04_阶段与门禁框架.md`、`docs/03_可复现研究工程标准.md`、`docs/tasks/README.md`、本 task 文档和根目录合订本的修改即可。本 PR 不迁移文件、不改代码、不产出数据，因此无需数据回滚。

## Validation

合并前必须通过：

```bash
python scripts/build_compendium.py --check
python scripts/validate_configs.py
python scripts/validate_manifests.py
ruff format --check scripts tests
ruff check scripts tests
python -m unittest discover -s tests -v
git diff --check
```
