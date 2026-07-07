# R0-T09 主网格全量参数扫描与 candidate artifact 物化

状态：runner/contract/smoke completed via PR #67；formal input manifest blocked pending real R0-T04 -> R0-T07 upstream artifacts；production full-grid materialization pending。

## 目标

R0-T09 负责把 R0-T08 已定义的 27 组 weak baseline 主网格 candidate 配置物化为可审计 artifact。主网格固定为 `W=[120,250,500]`、`q=[0.10,0.20,0.30]`、`K=[2,3,5]`、`weak_delta=0.10`、`dimension_rule=weak`，baseline 配置固定为 `R0_W250_Q20_K3_WEAK_D010`。本 task 只做 materialization runner、resume 语义、每配置隔离输出和 manifest 记录，不改变 R0-T04 至 R0-T08 的指标、分位、状态或确认定义。

## 非目标

本 task 不生成 R0 审计报告，不生成 R1 handoff，不做 R1 分析，不生成 future label、future return、breakout direction、release event、backtest、portfolio、trade signal、gap merge 或 cooldown。R0-T09 不调用 provider，不直接绕过授权 manifest 读取 `data/raw/`、`data/external/`、`MarketDB` 或 `.day` 文件；测试只使用合成输入和临时目录，不提交 generated artifact。

## 输入

Runner 入口为：

```bash
python scripts/r0/run_r0_t09_main_grid.py --input-manifest <authorized_input_manifest.json> --output-dir data/generated/r0/r0_t09/<run_id> --max-workers 2 --resume
```

输入 manifest 必须至少包含 `input_data_version`、`input_schema_version`、`input_content_hash`、`input_row_counts`、`source_lineage`、`authorized_r0_input=true`、`code_commit_or_data_build_id` 和 `input_payload_path`。`input_payload_path` 指向已授权上游 payload；payload 必须来自真实 R0-T04 至 R0-T07 授权链路，不得由 contract-grid synthetic rows 冒充，不得含 legacy V1 字段、future/return/backtest/portfolio/signal 字段或未授权真实数据直连来源。

payload 必须通过 R0-T09 coverage guard。全量运行要求 `nested_daily_state_results` 覆盖 9 个 `(W,q)`，`daily_confirmation_results` 覆盖 27 组 `(W,q,K)` 的四个 `state_name`，且 `confirmed_interval_results` 中出现的行都能合法映射到主网格；没有 confirmed interval 是合法情形。只包含单个 config 的 payload 只能配合 `--only-config <candidate_config_id>` 使用，不能被标记为 27 组全量完成。

## 输出

每个 `candidate_config_id` 独立输出配置快照、daily state DuckDB、daily state CSV gzip、confirmed interval DuckDB、confirmed interval CSV gzip、`DONE.json` 或 `FAILED.json` marker 以及日志。全局 `manifest.json` 记录 27 个配置、baseline 配置、`run_scope`、`selected_config_count`、`selected_config_ids`、每配置状态、输入 manifest hash、行数、DuckDB/CSV 内容 hash、全局 hash、engine version、contract/schema id、lineage guard、input payload coverage guard 和 forbidden output guard。

写入必须使用 partial 文件和 atomic rename。`--resume` 仅在 `DONE.json` 存在、全部 artifact 存在、`config_hash` 与 `input_manifest_hash` 匹配且 daily DuckDB、daily CSV gzip、interval DuckDB、interval CSV gzip 四个内容 hash 都可复算一致时跳过；存在 partial、FAILED 未关闭、缺失文件、缺失 hash 或任一 hash 不一致时必须重新物化该配置。

## 契约与门禁语义

R0-T09 contract 固化在 `configs/r0/r0_t09_main_grid_materialization_contract.v1.json`，schema 固化在 `schemas/r0/r0_t09_main_grid_materialization_contract.schema.json`。`max_workers` 默认和上限均为 2，超过 2 必须拒绝。K=1 不属于 R0-T09 confirmation grid；K=1 是 R0-T06 raw daily state reference，不作为 confirmed state materialization config。

V1 baseline 必须保持为 `V1_TurnoverShrink20_60` / `TurnoverShrink20_60_raw`。`VolShrink20_60_raw`、`V1_VolShrink20_60`、`VolShrink20_60`、`volume_shrink_20_60` 在输入、输出、fixtures、schema-like list 和 manifest-like list 中均视为 forbidden legacy V1 字段，发现后应返回 blocked 或使 runner 失败。

Formal input manifest builder 在未显式传入 R0-T04/R0-T05/R0-T06/R0-T07 上游输入时，必须写出 `status=blocked`、`reason_codes=["formal_upstream_inputs_missing"]`、`authorized_input_manifest_written=false` 的 `generation_summary.json`，不得写出 `authorized_r0_input=true` 的 manifest。Synthetic contract-grid payload 只能通过显式 smoke mode 或测试 helper 使用；它不得写入 `data/generated/r0/r0_t09_inputs/`，也不得用于 production full-grid materialization。

## 验收标准

合成测试必须证明 runner 能展开 27 组配置、baseline 配置存在、K=1 缺席、单配置物化生成 DuckDB/CSV gzip/DONE/manifest、resume 可跳过完整 artifact、partial 或 hash 不一致不会被跳过、失败配置写入 FAILED marker 且不写 DONE。测试还必须覆盖 worker 上限、CLI dry-run、input manifest hash mismatch、forbidden lineage 和 legacy V1 guard。

R0-T09 runner/contract/smoke 可通过 PR #67 完成，但正式 input manifest 与 production full-grid materialization 仍需真实 R0-T04 至 R0-T07 上游 artifact。任务索引不得在 production full-grid materialization 完成前推进到 R0-T10。R0-T10 才负责审计报告和 R1 交接。

## 失败状态

输入 manifest 缺失字段、`authorized_r0_input` 非 true、payload hash 不匹配、lineage 直接指向禁用来源、payload 或输出包含 forbidden 字段时，runner 必须阻断。单配置执行失败时，应保留 `FAILED.json`、traceback log 和可重试命令；全局 manifest 状态为 `incomplete`，不得伪装成完成。

## 验证命令

```bash
python scripts/build_compendium.py --check
python scripts/validate_configs.py
python scripts/validate_manifests.py
ruff format --check scripts tests src
ruff check scripts tests src
python -m unittest discover -s tests -v
git diff --check
```

## 回退方式

如 R0-T09 runner 或 contract 出现问题，可回退本 PR 中新增的 runner、CLI、contract/schema、测试和 task 索引变更。已生成的 `data/generated/r0/r0_t09/<run_id>` 属于可重建 generated artifact，不应提交；回退代码后删除对应本地 generated 输出并重新从 R0-T08 artifact 或授权上游 manifest 物化即可。
