# R1-T14-02 层级 q-vector 正式结构复验 Scientific Review

## 审阅身份与绑定

独立审阅者为 `benzemaer`，角色为 `independent_scientific_reviewer`；implementation actor 为 `codex`，independence attestation 为 true。审阅绑定 PR #89 head `c6bd78ce7f97271de83739d8196097116463a23a`、run `R1-T14-02-20260711T1100Z`、execution commit `96bf8f0acbfb265d0a242c2d700a54e5ef294b1e` 与 author package SHA-256 `cb5c6c454f7023059ea237c32d574aca13e5b82343ba6ee36e6839711a13eb25`。

## 独立复算与结论

审阅从 committed existence profile 独立复算 confirmed V selectivity。W120 V=.30/V=.25 的 retained ratio 为 0.8295418807002831/0.9180207568927561；W250 V=.30/V=.25 为 0.8337733899667088/0.9236597405579154，均与 decision matrix 一致并高于 0.50。Validator 已从 confirmed source rows 独立复算，旧 raw-ratio package 会 fail closed。

审阅确认 10-vector registry、五个 family、`N_perm=10000`、scope-specific robust envelope、denominator reconciliation、年份、LOYO、邻域及 parent-child/interval invariants 均未退化。最终 author-side 状态保持 4 个 `formal_structure_supported_with_warning` 和 4 个 `review_only`；V center heterogeneity warning 继续保留。

Scientific review 结论为 `passed`，blocking findings 为空，允许进入 repository final gate。审阅原始记录见 [PR #89 comment](https://github.com/benzemaer/convergence-research/pull/89#issuecomment-4945024905)。

## 推断与 Gate 边界

该 PASS 只允许 final gate 后启动 R1-T10，R2 继续关闭。结果不支持 best q、final winner、frozen state、独立确认、因果机制、预测能力或交易优势；`selection_path_not_independently_confirmed=true` 必须永久保留。
