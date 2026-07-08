# R0-T10-03 R0-T06 Nested State Materialization Evidence Repair 20260708T1740Z

## Summary

`task_id`: R0-T10-03

`status`: completed

`run_id`: R0-T10-03-20260708T1740Z

`code_commit`: 9195dfebebe71802c582d4094fbaec2427c46d27

This evidence records the repaired R0-T06 nested state materialization from the repaired R0-T05 score artifacts. It records only paths, hashes, counts, coverage, validation status, and gates. It does not embed row-level payloads or copy generated DuckDB / shard contents.

## Input

`input_r0_t05_evidence_path`: `docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence_repair_20260708T1730Z.md`

`input_indicator_score_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_indicator_score_results.duckdb`

`input_indicator_score_duckdb_sha256`: `6da065875c8270e321910083409f4dba5c1ee63bc6328e56aff3a1d489924447`

`input_dimension_score_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_dimension_score_results.duckdb`

`input_dimension_score_duckdb_sha256`: `4a04fbada9ecac15936e3ab5d968cba8f1205db5dbe66a0491c7141e6fc5b8a5`

`input_common_eligible_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb`

`input_common_eligible_duckdb_sha256`: `fa3f7bf59956339ae667c6e8680bb6c67a896bd344029d9c002c3eb394a96de1`

`input_indicator_score_row_count`: 41,538,456

`input_dimension_score_row_count`: 20,769,228

`input_common_eligible_row_count`: 1,730,769

`input_security_count`: 800

`input_date_min`: 20160104

`input_date_max`: 20260630

## Command

```powershell
python scripts/r0/run_r0_t10_03_materialize_nested_states.py `
  --r0-t05-evidence docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence_repair_20260708T1730Z.md `
  --indicator-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_indicator_score_results.duckdb `
  --dimension-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_dimension_score_results.duckdb `
  --common-eligible-duckdb data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb `
  --output-dir data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06 `
  --run-id R0-T10-03-20260708T1740Z `
  --code-commit 9195dfebebe71802c582d4094fbaec2427c46d27 `
  --max-workers 16 `
  --duckdb-threads 1 `
  --duckdb-memory-limit-per-worker 2GB `
  --chunk-size-securities 1 `
  --resume
```

## Output

`output_dir`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/`

`indicator_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_indicator_state_results.duckdb`

`indicator_state_duckdb_sha256`: `c82fda0c89265ed9b8d5fbbb4f4fec9ca64acfd8b0d2954b856841a72ef7cc2e`

`dimension_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_dimension_state_results.duckdb`

`dimension_state_duckdb_sha256`: `bbbb49ea2056bf6f257c1821236eb2b657eb1490153dfc9e56acee8f33264e08`

`nested_daily_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`

`nested_daily_state_duckdb_sha256`: `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`

`manifest_path`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_state_results_manifest.json`

`manifest_sha256`: `b979836cd9a80cc4b2a0b4247bdc9e8f2d11f77a889499a93120d980e7106f60`

`summary_path`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_execution_summary.json`

`summary_sha256`: `db15a1e66130468f8f17bc2623a9ac183e2ce87d6b1e9ef51544e4b8e33288b1`

`indicator_state_row_count`: 124,615,368

`dimension_state_row_count`: 62,307,684

`nested_daily_state_row_count`: 15,576,921

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

## Nested State Repair Check

`S_P_raw_true_count`: 2,690,161

`S_PC_raw_true_count`: 1,253,587

`S_PCT_raw_true_count`: 399,013

`S_PCVT_raw_true_count`: 123,129

`exclusive_state_layer_distribution`: BLOCKED=11,111; NONE=10,674,548; P_ONLY=1,331,475; PC_ONLY=854,574; PCT_ONLY=269,699; PCVT=123,129; UNKNOWN=2,312,385

`S_P_validity_valid_count`: 13,364,709

`S_PC_validity_valid_count`: 13,259,610

`S_PCT_validity_valid_count`: 13,259,610

`S_PCVT_validity_valid_count`: 13,253,425

The repaired run preserves row-level validity for backward compatibility and adds state-specific validity/reason fields for `S_P`, `S_PC`, `S_PCT`, and `S_PCVT`.

## Validation

```powershell
python scripts/r0/validate_r0_t10_03_materialization.py `
  --output-dir data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06 `
  --r0-t05-evidence docs/evidence/r0/R0-T10-02_r0_t05_strict_past_score_materialization_evidence_repair_20260708T1730Z.md `
  --indicator-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_indicator_score_results.duckdb `
  --dimension-score-duckdb data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_dimension_score_results.duckdb `
  --common-eligible-duckdb data/generated/r0/r0_t10/R0-T10-02-20260708T1730Z/r0_t05/r0_t05_common_eligible_sample_results.duckdb
```

`validator_status`: passed

`nested_recompute_check`: passed

`nested_recompute_mismatch_count`: 0

`state_specific_validity_schema_check`: passed

`nested_invariant_check`: passed

`exclusive_layer_uniqueness_check`: passed

`forbidden_field_check`: passed

`legacy_v1_check`: passed

`confirmation_field_absence_check`: passed

`K_absence_check`: passed

## Downstream Gate

`R0-T07_allowed_to_start`: true

R0-T07 is allowed to start because this evidence shows completed repaired R0-T06 materialization, validator-passed nested-state invariants, state-specific validity schema, row counts, output hashes, forbidden field checks, and no confirmation/K leakage into R0-T06.
