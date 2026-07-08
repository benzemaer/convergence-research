# R0-T10-04 R0-T07 Confirmation Interval Materialization Evidence Repair 20260708T1746Z

## Summary

`task_id`: R0-T10-04

`status`: completed

`run_id`: R0-T10-04-20260708T1746Z

`code_commit`: 4f54efba6cb4525adf2123d87bb56d7ada94cecd

This evidence records the repaired R0-T07 confirmation interval materialization after fixing state-specific validity propagation and the SQL streak boundary bug after non-ready rows. It records only paths, hashes, counts, distributions, validation status, and gates. It does not embed row-level payloads or copy generated DuckDB / shard contents.

## Input

`input_r0_t06_evidence_path`: `docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence_repair_20260708T1740Z.md`

`input_nested_daily_state_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb`

`input_nested_daily_state_duckdb_sha256`: `0c07f4897d76c0a729963118c2e75581bd71521a25245d6d3b650b4f32e68995`

`input_nested_daily_state_row_count`: 15,576,921

`input_security_count`: 800

`input_date_min`: 20160104

`input_date_max`: 20260630

## Command

```powershell
python scripts/r0/run_r0_t10_04_materialize_confirmation_intervals.py `
  --r0-t06-evidence docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence_repair_20260708T1740Z.md `
  --nested-daily-state-duckdb data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb `
  --output-dir data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07 `
  --run-id R0-T10-04-20260708T1746Z `
  --code-commit 4f54efba6cb4525adf2123d87bb56d7ada94cecd `
  --max-workers 16 `
  --duckdb-threads 1 `
  --duckdb-memory-limit-per-worker 2GB `
  --chunk-size-securities 1 `
  --resume
```

## Output

`output_dir`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/`

`daily_confirmation_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/r0_t07_daily_confirmation_results.duckdb`

`daily_confirmation_duckdb_sha256`: `e9bcaafbd60229b6d9e01967cedb2739efb3407159a66d1ef47b3d779689b4e3`

`confirmed_interval_duckdb_path`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/r0_t07_confirmed_interval_results.duckdb`

`confirmed_interval_duckdb_sha256`: `583187e213edc7b9796d5db5ef0b5484ad4b3fb17624212796ea1b9a721208ad`

`manifest_path`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/r0_t07_confirmation_interval_results_manifest.json`

`manifest_sha256`: `0714ec0f36c4f6d47c5b664c441ab124571f0dabc42a774bf03f84586414bb5c`

`summary_path`: `data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07/r0_t07_execution_summary.json`

`summary_sha256`: `783d35064058027ac68520b1598fc4ebd1fe95ee675502a8feda9c00b7f47a7b`

`daily_confirmation_row_count`: 186,923,052

`confirmed_interval_row_count`: 1,012,396

`security_count`: 800

`date_min`: 20160104

`date_max`: 20260630

`shard_count`: 800

`completed_chunk_count`: 800

`failed_chunk_count`: 0

## Confirmation Repair Check

`daily_confirmed_true_count`: 10,206,649

`daily_confirmed_false_count`: 149,205,413

`daily_confirmed_null_count`: 27,510,990

`confirmed_interval_count`: 1,012,396

`open_interval_count`: 3

`closed_interval_count`: 1,012,393

`S_P_confirmed_true_by_K`: K2=2,453,945; K3=2,262,807; K5=1,950,274

`S_PC_confirmed_true_by_K`: K2=1,106,600; K3=986,561; K5=794,318

`S_PCT_confirmed_true_by_K`: K2=257,960; K3=170,726; K5=76,253

`S_PCVT_confirmed_true_by_K`: K2=77,343; K3=49,476; K5=20,386

`S_P_interval_count_by_K`: K2=191,138; K3=165,346; K5=132,767

`S_PC_interval_count_by_K`: K2=120,039; K3=102,671; K5=78,791

`S_PCT_interval_count_by_K`: K2=87,234; K3=57,134; K5=24,442

`S_PCVT_interval_count_by_K`: K2=27,867; K3=17,818; K5=7,149

The repaired run confirms that `S_PC`, `S_PCT`, and `S_PCVT` are non-zero at both raw-state and confirmed-state layers. It also removes the previous SQL over-counting of the first true row after a non-ready boundary.

## Validation

```powershell
python scripts/r0/validate_r0_t10_04_materialization.py `
  --output-dir data/generated/r0/r0_t10/R0-T10-04-20260708T1746Z/r0_t07 `
  --r0-t06-evidence docs/evidence/r0/R0-T10-03_r0_t06_nested_state_materialization_evidence_repair_20260708T1740Z.md `
  --nested-daily-state-duckdb data/generated/r0/r0_t10/R0-T10-03-20260708T1740Z/r0_t06/r0_t06_nested_daily_state_results.duckdb
```

`validator_status`: passed

`daily_recompute_mismatch_count`: 0

`interval_recompute_mismatch_count`: 0

`confirmed_nested_invariant_check`: passed

`no_backfill_check`: passed

`forbidden_field_check`: passed

`legacy_v1_check`: passed

`future_return_absence_check`: passed

`full_code_commit_check`: passed

## Downstream Gate

`R0-T10-05_allowed_to_start`: true

R0-T10-05 is allowed to start because this evidence shows completed repaired R0-T07 materialization, validator-passed deterministic daily and interval recomputation, non-zero confirmed states for all nested state names, row counts, output hashes, forbidden field checks, legacy V1 checks, and no future-return fields.
