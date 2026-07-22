# R2A-T05 CA exit-mechanism formal result acceptance

## Owner acceptance decision

The owner accepts the R2A-T05 formal result, scientific review, and owner-authorized post-run artifact remediation. R2A-T05 is closed as `completed_accepted`; no additional formal run is allowed. The canonical accepted handoff and `DONE` marker establish the completed lifecycle. R2A-T06 becomes eligible to start only after PR #115 is merged and has not started in this closure.

## Accepted lineage

```text
task_id: R2A-T05
scope_id: r2a_t05_ca_exit_mechanism_decomposition.v1
reviewed_implementation_sha: 55dceba70bc967caa75c597ce17acb93a2dac511
reviewed_formal_execution_sha: 99013f57eb9835f57ec7d253b35689f2ffc123e7
accepted_execution_head: 260c3e1fe040eb9a44ee64f54a01142e6c3d8efa
accepted_run_id: R2A-T05-20260722T012719685Z
formal_process_exit: 0
formal_run_attempt_limit: 2
formal_run_attempts_consumed: 2
additional_formal_run_allowed: false
```

The accepted formal input manifest is `data/generated/r2a/r2a_t05/formal-authorization/99013f57eb9835f57ec7d253b35689f2ffc123e7/r2a_t05_formal_input_manifest.v1.json`, SHA-256 `368626145f0d1ba78a8d4b8577b4fbbf53a5832da313068445d7984973958c44`, 10,449 bytes.

## Attempt history

Attempt 1, `R2A-T05-20260721T013805600Z`, failed closed with process exit 124 and classification `external_cumulative_timeout`. It was not accepted. Its retained immutable inventory SHA-256 is `9baeb8a2f6b2ffb47251d937c1551ff83450f62a49996771528c4b3dcf502770`.

Attempt 2, `R2A-T05-20260722T012719685Z`, completed with process exit 0. Four request validators, T04 reconciliation, independent recalculation, two-build determinism, artifact identity, result-package schema, and anomaly checks passed. The formal technical acceptance and scientific review passed, and the owner accepts the result.

## Post-run artifact remediation

The completed package initially contained 11 `compact-review/*.csv` files written with default CRLF line endings. The owner authorized a scope-closed remediation that normalized exactly those 11 CSV files to LF, rebuilt `artifact_manifest.json` and `result_package.json`, and changed exactly 13 authorized RunRoot files. No scientific recomputation, formal reexecution, or formal attempt consumption occurred. CSV header, row order, column count, cell value, null, and JSON-cell semantics remained equivalent; no unauthorized RunRoot file changed.

The remediation is disclosed because the formal package was modified between execution and acceptance. Its manifest is `data/generated/r2a/r2a_t05/formal-artifact-remediations/R2A-T05-20260722T012719685Z/20260722T060039690Z/remediation_manifest.json`, SHA-256 `e84348533b0d7ea7962d44c04fa1c9e5bf6c693f45b692ce45286ea3de52b859`.

The accepted package identities after remediation are:

```text
artifact_manifest.json: 1f61296fa97337f9735b42ba2301fa58380712c6c721a7083d7004535acb22e0 / 6936 bytes
result_package.json: 1cafc65beed826a3cf5e08b4237656e36f32a768197dd19ee57d9eb7cb913913 / 9649 bytes
```

The final review manifest is `data/generated/r2a/r2a_t05/formal-result-reviews/R2A-T05-20260722T012719685Z/20260722T062413707Z/review_manifest.json`, SHA-256 `0319530cd78741e505f539fc3d454df0be894d7cdaf05698b6d7c0a21ef7911f`.

## Accepted scientific result

The research anchor is `CA_q20_k5`, with q=2000 for C and A and K=5. It remains `research_anchor_only`: it is not a best, optimal, winner, selected, or canonical q.

The q20 result contains 5,372 confirmed intervals. Primary termination counts are 5,363 `raw_false`, 8 `quality_or_availability_termination`, and 1 `input_end_open_right_censored`. The raw-false decomposition is 5,244 `A_ONLY_FAIL`, 46 `C_ONLY_FAIL`, and 73 `CA_BOTH_FAIL`.

Quick re-entry analysis, unique cross-q parent mapping, daily identity conservation, q20 fragmentation analysis, and q25 shell conservation passed. All four requests retained `[C, A]`, K=5, and `evaluated_not_selected`; their accepted T04 counts are:

| Request | Raw true | Confirmed true | Intervals | Securities with interval |
| --- | ---: | ---: | ---: | ---: |
| CA_q10_k5 | 20,559 | 1,916 | 751 | 473 |
| CA_q15_k5 | 46,651 | 7,125 | 2,426 | 734 |
| CA_q20_k5 | 81,535 | 17,642 | 5,372 | 775 |
| CA_q25_k5 | 124,893 | 35,098 | 9,107 | 788 |

These facts describe contemporaneous CA exit and cross-q structure only. They do not support claims about returns, direction, future paths, release labels or intensity, trading value, causal mechanisms, or q optimality. No future price path or return data was read; no release/direction/intensity label, trading signal, or backtest was produced.

## Closure hash chain and downstream gate

The accepted handoff is `data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/r2a_t05_accepted_result_handoff.json`, SHA-256 `6d69a6526d14f4844fdc1f5b888bb87768c7eedb58b65ea76445eede3d1a6881`, 10,657 bytes. The canonical marker is `data/generated/r2a/r2a_t05/R2A-T05-20260722T012719685Z/DONE`, which binds that handoff SHA.

R2A-T06 is not started by this closure. It receives `true_after_PR_115_merge` eligibility only when PR #115 has actually merged.
