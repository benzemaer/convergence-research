# EXP-A02 raw domain / availability / validity

EXP-A02 is the second implementation stage of the long-lived EXP-A sidecar branch. This commit activates the formal-execution path for the already approved aggregate and validator contract; it does not execute that path. It consumes only the accepted EXP-A01 result handoff and its five bound artifacts. It does not consume D3 evidence directly, alter A1/A2/A2b formulas, register an A-layer indicator, select a winner, create PCATV, or start EXP-A03.

## Governance state

```text
task_id: EXP-A02
program_id: EXP-A
current_sidecar_task: EXP-A02 formal execution activation
phase: formal_execution_activation_implementation_review
approved_A02_aggregate_implementation_sha: f6f0dc961357ffe2f4cc43c07be11e804a7af992
formal_execution_activation_sha:
formal_execution_activation_review_status: pending
implementation_review_status: pending
reviewed_implementation_sha:
formal_run_allowed: false
formal_run_status: not_started
formal_run_executed: false
formal_artifacts_generated: false
result_review_status: not_started
EXP-A02_started: true
EXP-A03_started: false
formal_data_version: false
real_authorized_input_manifest_created: false
real_raw_opened: false
mainline_task_unchanged: true
mainline_current_task: R3-T02
```

The approved aggregate implementation is fixed at `f6f0dc961357ffe2f4cc43c07be11e804a7af992`; the producer file and its aggregate definitions are unchanged. The activation commit is pending exact-SHA implementation review and does not authorize a formal run. The accepted upstream is fixed to `EXP-A01-20260717T040145984Z`, result commit `b7be2577233c045e507efe05d20601a20d373c9b`, and execution implementation SHA `c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d`.

## Input contract

Both synthetic fixtures and a separately authorized formal manifest must contain exactly these five EXP-A01 artifacts, with byte SHA bindings and the accepted upstream cross-bindings replayed from disk:

1. `exp_a01_accepted_result_handoff`;
2. `exp_a01_raw_metrics`;
3. `exp_a01_manifest`;
4. `exp_a01_validator_result`;
5. `exp_a01_anomaly_scan`.

The handoff must state that EXP-A01 is accepted and that EXP-A02 is eligible to consume it. Formal path policies are limited to absolute declared paths, paths relative to the manifest, or a basename resolved under the explicit `--input-root`; synthetic fixtures use only the synthetic-fixture policy. Formal mode requires an approved manifest, `--allow-formal-run`, a reviewed 40-character SHA, an exact clean HEAD, and a non-existing output directory. The input DuckDB is always opened read-only, and the five input hashes are recorded before and after execution. No real authorized manifest or real A01 raw has been created or opened in this activation commit.

## Implemented aggregate contract

The producer uses independent set-based DuckDB SQL to materialize nine compact CSV profiles:

- raw domain and finite-value distribution for A1, A2 and A2b;
- native indicator availability and common-valid availability for A1/A2, A1/A2b, A2/A2b and all three;
- validity-status, reason-code and reason-combination distributions;
- year and security availability;
- deterministic lower/upper extreme-value samples of size 20 per indicator.

A1 and A2b valid values must be finite and nonnegative. A2 valid values must be finite, lie in `[0, 1]`, and lie on the `1/20` grid. Valid rows must have non-null finite raw values; non-valid rows must have null raw values. The validator independently checks indicator identity, one row per key/indicator, row cardinality, A2/A2b status/reason/window/key consistency, A1 prerequisite validity, common-valid sets, all persisted CSV fields, output hashes and forbidden fields.

Year and security `valid_rate_expected` values use the row count within the corresponding year/security and indicator group as their denominator. `valid_rate_present` continues to use the corresponding present-row count. The A2 grid-level anomaly uses the full-domain `unique_value_count` from the raw-domain profile, not the deterministic extreme-value sample.

## Output and failure policy

The allowed compact package consists of the nine CSVs, an output manifest, validator result, anomaly scan and fixed-section result analysis. No output raw DuckDB is generated or copied. The final package is atomically published only after one complete independent core validation, one anomaly scan and one cheap final-package validation. A failed synthetic or formal run preserves the staging compact diagnostics under its local-only failure package, writes a diagnostic `failure_summary.json`, does not publish the requested output directory, and does not classify the package as a formal result.

## Validation boundary

The standalone CLI calls the same independent validator entrypoint used by the runner and performs the full disk-based input-lineage, raw-invariant, aggregate-recompute, persisted-CSV, manifest, input-hash, diagnostic and forbidden-field checks. The validator and cheap final validator both enforce the canonical UTF-8/LF result-analysis text contract: exactly the frozen 20 headings, in order, once each, with an allowed readiness value on the final line. Tests cover producer determinism, group-local availability denominators, full-domain A2 grid detection, the five-artifact lineage contract, formal authorization and path policies, exact-SHA failures before raw open, formal/synthetic CSV identity, input-hash mutation preservation, raw deletion/duplication/unknown-indicator/null/non-finite/domain/grid/pair mutations, all nine aggregate CSV families, analysis-contract mutations, evidence mutations, standalone CLI read-only behavior, and failure-package preservation.

No real EXP-A02 formal run, large A01 raw read, real authorized manifest, result package, A-layer registration, winner selection, PCATV creation or EXP-A03 work is part of this implementation commit. Formal activation review remains pending; `formal_run_allowed=false` and `formal_artifacts_generated=false` remain in force.
