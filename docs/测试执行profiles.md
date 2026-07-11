# 测试执行 profiles

`scripts/run_unittest_profile.py` 是本仓库 unittest 分层执行入口。运行器始终输出 profile 总测试数、结果和总耗时，并默认列出最慢的 10 个测试文件。可用 `--slowest-files N` 调整数量，或设为 `0` 关闭文件耗时明细。耗时统计只观察测试执行，不改变发现范围、测试顺序、结果或退出码。

## Profile 适用范围

| Profile | 适用场景 | 包含范围 |
| --- | --- | --- |
| `unit-fast` | 小步开发和契约、governance 变更的快速反馈 | 纯单元、正式实验契约、阶段路由、任务索引、governance 契约与 validator 测试 |
| `stage-r1` | R1 开发中的阶段回归 | `tests/r1/test*.py` 的现有完整发现范围 |
| `stage-r2` | R2 开发中的阶段回归 | `tests/r2/test*.py` 的现有完整发现范围 |
| `pr-fast` | PR 提交前的快速跨阶段反馈 | 使用关键 smoke 覆盖核心 R0/R1 接口，并保留其他既有 validator、正式实验契约和 governance 选择 |
| `regression-lite` | Draft PR 与日常迭代的完整轻量回归 | 发现 `full` 的全部测试，并按 canonical repository-relative path 精确排除三项 R0-T10 重测试 |
| `r0-heavy-premerge` | 三项 R0-T10 重测试的定向诊断 | 仅包含 score materializer、score validator 和 full-grid materializer；不能替代 `full` |
| `integration` | 数据与文件边界改动的集成回归 | provider、materializer、DuckDB、文件落盘、恢复账本及较重合成流程；包含完整 R0 full-grid materializer |
| `full` | final gate、合并前或 main push | `tests` 下全部 `test*.py`，是完整回归的唯一权威入口 |

## 执行策略

开发中优先运行受影响阶段的 profile；纯单元、契约或 governance 改动可先运行 `unit-fast`，数据边界改动同时运行 `integration`。Draft PR 运行 `unit-fast`、受影响 stage、`pr-fast` 与 `regression-lite`。`pr-fast` 中 R0 full-grid 与 R1-T03 只运行最小 smoke；完整 R1-T03 27-grid 由 `stage-r1` 和 `full` 承载。三项 R0-T10 重测试只进入 `r0-heavy-premerge`、`integration` 和 `full`，其中 `r0-heavy-premerge` 仅用于定向诊断。`full` 保持全发现语义，只在 ready-for-review、手动 premerge trigger 或 repository final gate 前运行，并必须绑定当时 reviewed HEAD。

当前不启用测试并行。先使用最慢文件统计识别瓶颈，并审查临时目录、环境变量、模块缓存、数据库连接、固定端口和正式 docs 写入等共享状态风险。只有污染和顺序依赖得到消除后，才评估按测试文件并行；并行化不得改变 fail-closed gate 或掩盖非隔离测试。
