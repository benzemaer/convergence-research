# 测试执行 profiles

`scripts/run_unittest_profile.py` 是本仓库 unittest 分层执行入口。运行器始终输出 profile 总测试数、结果和总耗时，并默认列出最慢的 10 个测试文件。可用 `--slowest-files N` 调整数量，或设为 `0` 关闭文件耗时明细。耗时统计只观察测试执行，不改变发现范围、测试顺序、结果或退出码。

## Profile 适用范围

| Profile | 适用场景 | 包含范围 |
| --- | --- | --- |
| `unit-fast` | 小步开发和契约、governance 变更的快速反馈 | 纯单元、正式实验契约、阶段路由、任务索引、governance 契约与 validator 测试 |
| `stage-r1` | R1 开发中的阶段回归 | `tests/r1/test*.py` 的现有完整发现范围 |
| `stage-r2` | R2 开发中的阶段回归 | `tests/r2/test*.py` 的现有完整发现范围 |
| `pr-fast` | PR 提交前的代表性跨阶段回归 | 保留既有显式清单语义，覆盖核心 R0/R1 计算、validator、正式实验契约和 governance |
| `integration` | 数据与文件边界改动的集成回归 | provider、materializer、DuckDB、文件落盘、恢复账本及较重合成流程 |
| `full` | final gate、合并前或 main push | `tests` 下全部 `test*.py`，是完整回归的唯一权威入口 |

## 执行策略

开发中优先运行受影响阶段的 profile；纯单元、契约或 governance 改动可先运行 `unit-fast`，数据边界改动同时运行 `integration`。PR 提交前运行 `pr-fast`。final gate、合并前或 main push 运行 `full`。同一轮若已经运行 `full`，不要求先重复运行其覆盖范围内的 `pr-fast`。

当前不启用测试并行。先使用最慢文件统计识别瓶颈，并审查临时目录、环境变量、模块缓存、数据库连接、固定端口和正式 docs 写入等共享状态风险。只有污染和顺序依赖得到消除后，才评估按测试文件并行；并行化不得改变 fail-closed gate 或掩盖非隔离测试。
