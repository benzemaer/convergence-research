# R1-T14-02 层级 q-vector 正式结构复验 evidence

`task_id`: R1-T14-02

`run_id`: R1-T14-02-20260710T2306Z

`code_commit`: a17bbf676169305fa921ae5e612b3a71ca3acfe4

`upstream_R0_T15_PR`: #88

`upstream_exact_head`: 35a01fa9ba2e7b20455d7fc5f75d25217892c471

`selection_path_not_independently_confirmed`: true

## Formal inputs

R0-T15 result package SHA-256: `43aa859dc938f6a9796f68297107d978e9a3b1a36b1ea12fec8c10e5aee27f8b`。candidate registry SHA-256: `02fdaf1b94780ef42115a9109ae9f1fd6b90a6e019925a5067ad1bac96d4944f`。正式 family 为 10 vectors、5 max-stat families、`N_perm=10000`。

## Primary artifacts

- candidate registry: `d5bd0d247b2c31e3dfe561a218fbc4a9f989edfa7b7b49aab07360b5201dcf5a` / 10 rows
- R0 lineage reconciliation: `2029e766ddb581ddcf7956484f45b76a352cd34ebb2e04f5b6b8315db33b71a8` / 12 rows
- existence: `762e533f950d6e26ba4bdfd526c232d5694e221a9496bf4ff3351abd80efb2ed` / 24 rows
- intralayer: `a0ee6b67e5b160ac71cf808d3fea4d765b5d833501c78715d699be7fcca72795` / 40 rows
- interlayer: `3959238353869c781a688f7a57ff4473926c588434ef23a48befe9917ef5bcab` / 24,360 rows
- identity: `b7cbfdbb50382803c72b8ac56f0cc653877cef388683c641acd8be6ee20c075a` / 8 rows
- interval: `a351c9a297ccd87edab6c09adfb5c1cd2a607261fd88058a408562383f1b1191` / 12 rows
- year / LOYO: `b8083c55fc1fa0b89a3464bbf9b3649f15fec35a195c827b21384de68de17154` / 132 rows; `e599c16cfaa66819112cc9ae3ad9c2562f2ffdea89bd4b3e4d5bcfd16a1143b9` / 330 rows
- null / family maxima / multiplicity: `88758396d80c82f94c2e0dda40bb1705559f53ca945f307ed8e5e26ca7e964c8` / 30 rows; `16a3a6782cc6b8f3f2646127f73e67a633525b5c755f573992c630d49895419c` / 50,000 rows; `3ac955d1ac0dd2778c97fba8ba5978f372639f4f9e8929c0ad282cdf339fe179` / 30 rows
- neighborhood / dominance / decision: `5e655c15d95279adfd449dd8c1f435bab9bc77018cce39821049ae5c4ab0c765` / 4 rows; `e4b80c27fd1b5da19bafdab520c9cce08d449c56a3af4c9176d8cdd515de7a67` / 8 rows; `13559e3466b60d60957d272c6a6492fceae8fcc097c9cee6e061f509fe64d314` / 8 rows
- anomaly / diagnostic / experiment summary: `32f520aab5076a8015ada8cdde2854650d5fce68f76aabecd0a6b3a39c630d3f`; `b34d7ee16c002d16683f152e4484ab58ad8cf92e684d75f194582ea966110b06`; `13a707423a74ac94f81b3202a71bb0db2fcbdf85eecc691051efe136078405a6`

## Author-side recomputation

工程 validator status=passed。author-side 独立审计确认：8 个 Spearman 与 R1-T05 一致；12 个相交 threshold profiles 的五类 counts 一致；12 个 R0 reconciliation mismatch=0；30 个 adjusted p 逐行满足 `(n_family_extreme+1)/10001`；八个 decision 的 year conflict、pooled/security median reversal、raw/confirmed parent-child violations 均为 0。前两次 superseded run 与权威 run 的八个未受修复影响的核心 artifacts SHA 完全一致。

## Author-draft boundary

四个 centers 为 `formal_structure_supported_with_warning`，四个 neighbors 为 `review_only`。这不是 independent scientific review，也不推进仓库 gate：`scientific_review_status=pending`、`independent_review_status=not_started`、`repository_final_gate_status=pending`、`R1-T10_allowed_to_start=false`、`R2_allowed_to_start=false`、`formal_task_completed=false`。
