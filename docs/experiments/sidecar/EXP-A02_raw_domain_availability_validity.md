# EXP-A02 raw domain / availability / validity

EXP-A02 is the second implementation stage of the long-lived EXP-A sidecar branch. It consumes only the accepted EXP-A01 result handoff and its five bound artifacts. It does not consume D3 evidence directly, alter A1/A2/A2b formulas, register an A-layer indicator, select a winner, create PCATV, or start EXP-A03.

## Governance state

```text
task_id: EXP-A02
program_id: EXP-A
phase: implementation_review
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
execution_mode: synthetic_fixture_only
```

The accepted upstream is fixed to `EXP-A01-20260717T040145984Z`, result commit `b7be2577233c045e507efe05d20601a20d373c9b`, and execution implementation SHA `c9a52dc29f7d41c85ab416e99bb9ef8cc6411b9d`. The implementation package does not authorize a formal run. A later formal authorization, if any, must be issued against a newly reviewed exact implementation SHA and a separate authorized input manifest.

## Input contract

The EXP-A02 synthetic manifest must contain exactly these five EXP-A01 artifacts, with byte SHA bindings and the accepted upstream cross-bindings replayed from disk:

1. `exp_a01_accepted_result_handoff`;
2. `exp_a01_raw_metrics`;
3. `exp_a01_manifest`;
4. `exp_a01_validator_result`;
5. `exp_a01_anomaly_scan`.

The handoff must state that EXP-A01 is accepted and that EXP-A02 is eligible to consume it. The raw DuckDB is opened read-only only inside synthetic tests. The runner rejects an authorized/formal manifest during this implementation phase before opening its raw path; it accepts only `exp_a02_synthetic_input_manifest` with `formal_run_allowed=false`.

## Implemented aggregate contract

The producer uses independent set-based DuckDB SQL to materialize nine compact CSV profiles:

- raw domain and finite-value distribution for A1, A2 and A2b;
- native indicator availability and common-valid availability for A1/A2, A1/A2b, A2/A2b and all three;
- validity-status, reason-code and reason-combination distributions;
- year and security availability;
- deterministic lower/upper extreme-value samples of size 20 per indicator.

A1 and A2b valid values must be finite and nonnegative. A2 valid values must be finite, lie in `[0, 1]`, and lie on the `1/20` grid. Valid rows must have non-null finite raw values; non-valid rows must have null raw values. The validator independently checks indicator identity, one row per key/indicator, row cardinality, A2/A2b status/reason/window/key consistency, A1 prerequisite validity, common-valid sets, all persisted CSV fields, output hashes and forbidden fields.

## Output and failure policy

The allowed compact package consists of the nine CSVs, an output manifest, validator result, anomaly scan and fixed-section result analysis. No output raw DuckDB is generated or copied. The final package is atomically published only after independent validation. A failed synthetic run preserves the staging compact diagnostics under its failure package, writes a diagnostic `failure_summary.json`, does not publish the requested output directory, and does not classify the package as a formal result.

## Validation boundary

The standalone CLI calls the same independent validator entrypoint used by the runner and performs the full disk-based input-lineage, raw-invariant, aggregate-recompute, persisted-CSV, manifest, diagnostic and forbidden-field checks. Tests cover producer determinism, the five-artifact lineage contract, authorized-manifest rejection, raw deletion/duplication/unknown-indicator/null/non-finite/domain/grid/pair mutations, every aggregate CSV family, evidence mutations, standalone CLI read-only behavior, and failure-package preservation.

No real EXP-A02 formal run, large A01 raw read, result package, A-layer registration, winner selection, PCATV creation or EXP-A03 work is part of this implementation commit.
