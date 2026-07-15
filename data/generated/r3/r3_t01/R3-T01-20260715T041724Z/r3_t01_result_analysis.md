# R3-T01 result analysis

## Actual run and scope

The analyzer reread 18 declared artifacts from `R3-T01-20260715T041724Z` after the independent validator passed. It did not open the canonical database; the run is synthetic-only.
Implementation SHA: `460728eb42fb4464b781a34595f3ad544677c113`. Formal execution SHA: `460728eb42fb4464b781a34595f3ad544677c113`.

## Contract and independent replay

The run contains 21 synthetic cases and 17 natural exit attempts. case-scoped ID uniqueness=True; case-scoped ordinal conservation=True; production/independent case equality=True.
ID uniqueness is evaluated within each independent synthetic case. Ordinal conservation is evaluated within case_id × state_version_id × event_id; reuse of an identity across different cases is expected and is not a duplicate. Cross-case identity reuse count=3.
Executable synthetic cases=21; non-executable synthetic cases=0.
Landmark availability: {"H10": 1, "H20": 1, "H30": 1, "H5": 1, "T1": 7, "T2": 6}. Mutation results passed: 24/24.

## Anomaly scan

The validator anomaly artifact reports 0 findings. The analyzer added 0 independent pathology findings.
- No additional analyzer pathology was detected.

## Supported conclusions

The artifacts support only that the declared R3-T01 protocol, synthetic replay, independent replay, artifact ownership, mutation checks, and deterministic rebuild checks were executed and reconciled for this run.

## Not supported

This analysis does not support future-return, boundary, path-label, model-performance, or trading-advantage claims. It also does not replace scientific review of the implementation or downstream sample-outcome validation.

## R3-T02 recommendation

R3-T02 is not authorized by this artifact. Any analyzer finding requires resolution before downstream progression; the repository gate remains authoritative.
