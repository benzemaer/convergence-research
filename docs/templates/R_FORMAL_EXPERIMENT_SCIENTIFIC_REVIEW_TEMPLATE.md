# R Formal Experiment Scientific Review Template

```json
{
  "reviewer_identity": "",
  "reviewer_role": "scientific_reviewer",
  "implementation_actor": "",
  "independence_attestation": true,
  "reviewed_code_commit": "",
  "reviewed_summary_sha256": "",
  "reviewed_analysis_sha256": "",
  "independent_recomputations": [],
  "baseline_challenger_review": "",
  "parameter_response_review": "",
  "anomaly_review": "",
  "alternative_explanations": [],
  "blocking_findings": [],
  "nonblocking_findings": [],
  "scientific_review_status": "pending",
  "downstream_gate_recommendation": false
}
```

`reviewer_identity` 必须不同于 `implementation_actor`，且 `independence_attestation` 必须为 true。reviewer 必须直接读取 committed result artifacts 和 result analysis，独立复算至少一个核心 count / ratio / statistic，检查 baseline 与至少两个 challenger、参数响应、coverage / NULL / unknown / blocked、状态漏斗和不变量，并提出至少一个替代解释。

`reviewed_code_commit` 必须等于结果包的 `code_commit`，`reviewed_summary_sha256` 必须等于当前 `experiment_summary` artifact hash，`reviewed_analysis_sha256` 必须等于当前 `result_analysis.md` hash，`implementation_actor` 必须等于结果包中的 implementation actor。不得复用旧实验的 scientific review JSON 作为新实验 final gate 证据。
