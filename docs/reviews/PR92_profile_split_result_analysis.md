# PR #92 测试 profile 拆分结果分析

## 结果摘要

本轮把 `pr-fast` 中 R0 full-grid materializer 与 R1-T03 27-grid 合成契约替换为独立 smoke，完整测试文件未删除。全部运行保持串行，未启用 unittest 并行。

| Profile | 修改前测试数 | 修改前耗时 | 修改后测试数 | 修改后耗时 |
| --- | ---: | ---: | ---: | ---: |
| `pr-fast` | 276 | 152.410s | 259 | 29.931s |
| `integration` | 216 | 155.835s | 216 | 193.760s |
| `stage-r1` | 未记录 | 未记录 | 230 | 68.674s |
| `full` | 1193 | 183.269s | 1196 | 197.105s |

`pr-fast` 最终验收的单次墙钟耗时减少 122.479 秒，降幅约 80.4%。拆分后的首次运行为 42.285 秒，也已达到目标区间；不同轮次存在缓存和机器负载波动，因此差值只描述本次实测，文件级 timing 用于确认拆分是否生效，不作为稳定性能承诺。

## 覆盖证据

R0 smoke 真实物化 baseline `R0_W250_Q20_K3_WEAK_D010` 与非 baseline `R0_W120_Q10_K2_WEAK_D010` 两个单配置最小 DuckDB/Parquet 产物，检查 config ID、config hash、最小输出 schema、禁止 future/return/backtest/portfolio/signal 字段，并验证短 commit fail-closed。smoke 不运行 27-config 调度、完整 marker/resume、全文件 hash 复核或完整 validator；本轮单独耗时 0.689 秒，最终 `pr-fast` timing 为 0.428 秒。

完整 R0 文件仍在 `integration` 与 `full`。`integration` timing 明确记录 `tests/r0/test_r0_t10_full_grid_materializer.py` 6 tests、41.656 秒；`full` 再次记录同一完整文件 6 tests、17.056 秒。完整测试继续覆盖 27-config full-grid、DuckDB/Parquet、manifest、DONE/FAILED、resume、output hash、coverage guard 和完整 fail-closed 语义。

R1 smoke 检查 baseline、一个边界配置、27 个候选的稳定笛卡尔数量、配置 schema 与 required fields、非法 K grid fail-closed，以及未来收益和下游越权 token 禁止规则；它不生成或遍历完整 27-grid 合成产物。完整 `tests/r1/test_r1_t03_27_grid_light_profile_contract.py` 仍由 `stage-r1` discover 执行，本轮为 17 tests、52.837 秒；`full` 继续使用 `tests/test*.py` 全目录 discover，因此同时包含完整文件与 smoke。

## 异常扫描

所有最终记录的 profile 均选择非零测试，未出现重复 test id。`pr-fast` 不再加载两个完整慢文件；`integration` 保留完整 R0 文件；`stage-r1` 保留完整 R1-T03 文件；`full` 测试数由 1193 增至 1196，没有下降。开发过程中发现旧 R1-T03 契约硬编码完整文件必须位于 `pr-fast`，已按新分层规则更新为 smoke 断言；还发现 smoke 引用完整 test module 会污染 unittest discovery，已移除 test-to-test import 并改用独立最小 fixture。最终运行 failures=0、errors=0、exit code=0。

## 后续建议

当前仍不建议直接启用文件级多 worker。`full` 和 `integration` 的主要耗时已转移到 R0 score materializer/validator、完整 full-grid、D2 provider repair 和 D3 生成流程。下一步应先检查这些文件的临时数据库、进程启动、模块缓存和环境变量隔离，并保留串行 `full` 作为顺序依赖对照；只有共享状态风险被证明受控后，再评估有限的文件级 worker。
