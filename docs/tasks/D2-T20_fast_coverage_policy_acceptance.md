# D2-T20 快速 coverage policy acceptance 推进 D3

## 状态

in_progress。本任务使用显式 policy override 推进 D2 research candidate acceptance，并授权 D3-T07 读取 D2-T20 candidate DuckDB；它不是 formal source publication，不发布 formal data_version，不生成 D3 rows 或 R0。

## 目标

D2-T20 读取 D2-T19 repaired candidate DuckDB，复制到 D2-T20 output-dir，然后在复制库内应用两类显式 policy override：三段 `listing_pause` 区间，以及 688981.SH / 689009.SH 的 adjustment factor policy。目标是在不伪造 daily bar、不写 provider adj_factor rows 的前提下，将剩余 coverage blocker 清零，并输出 D2 acceptance candidate report 与 D3 handoff candidate report。本任务追加 `configs/d2/d2_t20_policy_evidence_manifest.v1.json` 作为 policy evidence manifest；若启用 `--require-policy-evidence`，acceptance 还必须通过 evidence gate。

## 非目标

本任务不生成假 daily bar，不用 0 填充 open/high/low/close，不把暂停上市区间标成 ST，不读写 `data/raw/` 或 `data/external/`，不读 MarketDB 或 `.day`，不写 formal DuckDB，不发布 formal data_version，不生成 R0 states、labels、returns、backtest 或 portfolio，不把 `pro_bar(qfq/hfq)` 写入 canonical staging。

## 输入

必需输入：

```text
--source-duckdb data/generated/d2/d2_t19_targeted_repair_candidate_r2_token_refresh/d2_t15_tnskhdata_staging.duckdb
--output-dir data/generated/d2/d2_t20_fast_coverage_policy_candidate
```

显式授权参数：

```text
--allow-user-attested-listing-pause
--allow-neutral-adj-factor-policy
--authorize-d3-candidate
```

如果缺少任一显式授权参数，脚本只生成 plan/report，不得把 acceptance 设为 accepted。

Policy evidence 参数：

```text
--policy-evidence-manifest configs/d2/d2_t20_policy_evidence_manifest.v1.json
--require-policy-evidence
--allow-pending-evidence-hash
```

`--require-policy-evidence` 启用后，脚本必须校验 listing pause 公告 evidence、688981.SH / 689009.SH adjustment-factor policy target 和 tnskhdata `adj_factor` normalized response hash。当前 manifest 已由 Codex 联网下载或读取公告正文、计算 sha256，并调用 tnskhdata `adj_factor` 补齐因子 evidence；accepted run 不依赖 `--allow-pending-evidence-hash`。若 sha256 为空或 evidence_status 不是 `hash_verified`，acceptance 必须阻塞。

## 输出

输出目录下包含 D2-T20 candidate DuckDB 副本：

```text
d2_t15_tnskhdata_staging.duckdb
```

并输出：

```text
d2_t20_policy_plan.json
d2_t20_policy_ledger.jsonl
d2_t20_post_policy_quality_report.json
d2_t20_acceptance_candidate_report.json
d2_t20_handoff_candidate_report.json
d2_t20_remaining_coverage_gaps.csv
d2_t20_gap_delta.csv
d2_t20_policy_risk_register.md
d2_t20_d3_handoff_notes.md
```

复制 DuckDB 内还会新增 policy evidence 表：

```text
d2_policy_evidence_documents
d2_policy_corporate_action_evidence
```

## Policy Override 规则

`listing_pause` user-attested intervals 固定为：

```text
000155.SZ 20160510-20171217
000629.SZ 20170505-20180823
000792.SZ 20200522-20210809
```

脚本在复制库内新增 `d2_policy_listing_pause_intervals`，以 `policy_type = listing_pause`、`applied_by_task = D2-T20` 记录。若 evidence manifest 的公告 sha256 已填充且 `evidence_status = hash_verified`，`evidence_level = official_announcement_hash_backed`。落在这些区间内的 security-date 标记为 `trading_status = listing_pause`、`daily_status = not_applicable_or_expected_empty`、`price_limit_status = not_applicable_or_expected_empty`，不再计入 listed-open missing daily 或 price-limit dependency blocker。

adjustment factor policy 固定用于：

```text
688981.SH
689009.SH
```

脚本在复制库内新增 `d2_policy_adj_factor_overrides`，以 `evidence_level = tnskhdata_adj_factor_hash_verified`、`applied_by_task = D2-T20` 记录。688981.SH 的真实 tnskhdata `adj_factor` evidence 全区间为 1.0，因此使用 `policy_type = neutral_factor_1`、`policy_factor = 1.0`，对应 unresolved adjustment-factor rows 标记为 `neutral_factor_1_policy`。689009.SH 的真实 tnskhdata `adj_factor` evidence 存在非 1.0 区间，因此使用 `policy_type = factor_interval`、`policy_factor = NULL`，对应 unresolved rows 标记为 `factor_interval_policy`，区间写入 `d2_policy_corporate_action_evidence`。不得向 `staging_adj_factor` 伪造 provider rows；若 manifest target 与 D2-T18/D2-T19 policy candidate 不一致，acceptance 必须阻塞。

## 验收标准

before/after delta 必须覆盖：

```text
listed_open_missing_daily_count
price_limit_daily_dependency_missing_count
unresolved_price_limit_status_count
unresolved_adjustment_factor_count
daily_raw_row_count
stk_limit_resolved_count
adj_factor_resolved_count
```

显式授权齐全、blocker 清零且 evidence gate 通过时，`d2_acceptance_decision = accepted_for_d3_candidate_generation`，handoff report 可输出 `d3_candidate_generation_authorized`。accepted run 必须标记 `policy_evidence_pending_hash = false` 与 `policy_evidence_level = official_or_mirror_hash_verified_and_tnskhdata_adj_factor_verified`。即便如此，D2-T20 仍不生成 D3 rows、不发布 data_version、不生成 R0。

## 阻塞条件 / 失败状态

若缺少 `--allow-user-attested-listing-pause`、`--allow-neutral-adj-factor-policy` 或 `--authorize-d3-candidate` 任一参数，不得 accepted。若 policy 后仍有 listed-open missing daily、daily dependency、price-limit unresolved、adjustment-factor unresolved 或其他 quality blocker，不得 accepted。若启用 `--require-policy-evidence` 但 manifest 缺失、listing pause 公告 slot 不完整、688981.SH / 689009.SH target 不匹配、sha256 为空、evidence_status 不是 `hash_verified`，`d2_acceptance_decision` 必须为 `blocked_pending_policy_evidence`。若 PR 生成 fake daily bar、0 price、formal data_version、D3 rows、R0 states、labels、returns、backtest 或 portfolio，PR 必须回退。

## 风险说明

三段 listing_pause 目前已有公告 evidence hash，其中 000155.SZ 暂停上市公告使用公告镜像 HTML/text fallback hash，其余公告使用 PDF hash。688981.SH / 689009.SH 是唯一 adjustment-factor policy target，且由真实 tnskhdata `adj_factor` normalized response hash 决定 neutral 或 factor_interval policy。该 evidence 仍只支撑 research candidate，不升级任何 provider 为 formal source。D2-T20 只用于推进 D3 research candidate；未来 formal data_version 仍需经过后续 gates。

## 回退方式

回退本 PR 新增脚本、policy evidence manifest、任务文档、README 更新和测试即可。D2-T20 不提交 generated outputs、不修改源 D2-T19 DuckDB、不创建 run/dataset/source snapshot manifest 或 data_version。

## Validation

合并前必须通过：

```bash
ruff format --check scripts tests
ruff check scripts tests
python scripts/validate_configs.py
python -m unittest discover -s tests -v
python scripts/build_compendium.py --check
git diff --check
```
