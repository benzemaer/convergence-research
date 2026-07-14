# 测试执行 profiles

`scripts/run_unittest_profile.py` 是本仓库 unittest 分层执行入口。运行器始终输出 profile 总测试数、结果和总耗时，并默认列出最慢的 10 个测试文件。可用 `--slowest-files N` 调整数量，或设为 `0` 关闭文件耗时明细。耗时统计只观察测试执行，不改变发现范围、测试顺序、结果或退出码。

## Profile 适用范围

| Profile | 适用场景 | 包含范围 |
| --- | --- | --- |
| `unit-fast` | 小步开发和契约、governance 变更的快速反馈 | 纯单元、正式实验契约、阶段路由、任务索引、governance 契约与 validator 测试 |
| `stage-r1` | R1 开发中的阶段回归 | `tests/r1/test*.py` 的现有完整发现范围 |
| `stage-r2` | R2 开发中的阶段回归 | `tests/r2/test*.py` 的现有完整发现范围 |
| `pr-fast` | PR 提交前的快速跨阶段反馈 | 使用关键 smoke 覆盖核心 R0/R1 接口，并保留其他既有 validator、正式实验契约和 governance 选择 |
| `integration` | 数据与文件边界改动的集成回归 | provider、materializer、DuckDB、文件落盘、恢复账本及较重合成流程；包含完整 R0 full-grid materializer |
| `full` | 需要完整回归时的手工诊断 | `tests` 下全部 `test*.py`，是完整回归的唯一入口，但不是自动门禁 |

## 执行策略

所有 unittest profiles 都是可选的手工诊断工具，没有默认必跑 profile。它们不再是创建 PR、提交 PR、合并、Implementation 审阅、formal run 授权、结果接受、README 推进或 task completed 的前置条件。任务开发者根据变更范围自行选择 task-specific tests，并在 PR body 中列出实际运行的命令和结果。

`unit-fast`、`stage-r1`、`stage-r2`、`pr-fast`、`integration`、`regression-lite` 和 `full` 的测试资产与语义保留，但 profile 选择不代表任何科学或工程门禁结论。`full` 也不再自动运行于 PR 或 main push；需要完整回归时由开发者或用户手工执行。

GOV-T02 新任务只要求先完成 implementation 审阅，再由用户明确批准 `reviewed_implementation_sha` 和 `formal_run_allowed: true`，之后才可执行 formal run。profile 运行结果可以作为审阅材料，但不能替代用户批准或用户对 formal result 的直接决定。

当前不启用测试并行。先使用最慢文件统计识别瓶颈，并审查临时目录、环境变量、模块缓存、数据库连接、固定端口和正式 docs 写入等共享状态风险；并行化不得改变研究流程或掩盖测试污染。
