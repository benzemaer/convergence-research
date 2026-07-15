# R3-T01 result analysis

## Actual run and scope

The analyzer reread 18 declared artifacts from `R3-T01-20260715T023116Z` after the independent validator passed. It did not open the canonical database; the run is synthetic-only.
Implementation SHA: `8c2589bb97fb014da9e925611d2d1ce716a94602`. Formal execution SHA: `8c2589bb97fb014da9e925611d2d1ce716a94602`.

## Contract and independent replay

The run contains 31 synthetic cases and 16 natural exit attempts. ID uniqueness=False; ordinal conservation=False; production/independent case equality=True.
Landmark availability: {"H10": 0, "H20": 0, "H30": 0, "H5": 0, "T1": 6, "T2": 5}. Mutation results passed: 24/24.

## Anomaly scan

The validator anomaly artifact reports 0 findings. The analyzer added 0 independent pathology findings.
- No additional analyzer pathology was detected.

## Supported conclusions

The artifacts support only that the declared R3-T01 protocol, synthetic replay, independent replay, artifact ownership, mutation checks, and deterministic rebuild checks were executed and reconciled for this run.

## Not supported

This analysis does not support future-return, boundary, path-label, model-performance, or trading-advantage claims. It also does not replace scientific review of the implementation or downstream sample-outcome validation.

## R3-T02 recommendation

R3-T02 is not authorized by this artifact. Any analyzer finding requires resolution before downstream progression; the repository gate remains authoritative.
