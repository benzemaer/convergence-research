# GOV-T01 R1-R6 formal 实验结果包、异常门禁与科学审阅治理 evidence

`task_id`: GOV-T01
`status`: completed
`task_class`: governance_contract
`code_commit`: 3ef64583a4758787a481c839b55fb213c5f3d259

`engineering_standard_path`: docs/03_可复现研究工程标准.md
`engineering_standard_sha256`: 3a1e3137745c5b76016656c22d3f7a0468eec04883a862fe27fa3db2b157e7d9
`task_template_path`: docs/templates/R_FORMAL_EXPERIMENT_TASK_TEMPLATE.md
`task_template_sha256`: fd9a940d3510b695684791289f500c8a651afd485559c1d0d0ce87419ca66376
`analysis_template_path`: docs/templates/R_FORMAL_EXPERIMENT_RESULT_ANALYSIS_TEMPLATE.md
`analysis_template_sha256`: 990549ea8e85e13360b65a5cb300c233b33e7dd5a0fcf4162067e629e57551da
`review_template_path`: docs/templates/R_FORMAL_EXPERIMENT_SCIENTIFIC_REVIEW_TEMPLATE.md
`review_template_sha256`: 55cbc5b0def3681b65409291cf9cd5e01a7c95420ceec246ea033cacb88347e5
`evidence_template_path`: docs/templates/R_FORMAL_EXPERIMENT_EVIDENCE_TEMPLATE.md
`evidence_template_sha256`: d0ee86e4592142434eb6bbca7b5be2741080b2f079669753fa92b861b9219dde
`PR_template_path`: .github/PULL_REQUEST_TEMPLATE/formal_experiment.md
`PR_template_sha256`: 479bd058b61b73e906fb852c3e2ab819c9ebb8e3e1f2217057bac2b6e5e990d3

`governance_config_path`: configs/governance/r_formal_experiment_governance.v1.json
`governance_config_sha256`: 449bf6dea923172a703c348063c99ac0d542db87d539ba5386f71e97b4584b1b
`governance_schema_paths`: schemas/governance/r_formal_experiment_governance.schema.json; schemas/governance/r_formal_experiment_result_package.schema.json; schemas/governance/r_formal_experiment_scientific_review.schema.json
`governance_schema_sha256`: 98ebbcd0d39e881b226e9a9de7b221d60925f5cd793b73272e929092fd04832f; b7633770b48bf4ceec9b7224a6175430b33bb96d14227989d480375f4f02f55f; e56df5d6352eb0bfa05df5f681e1478ff35c3eb4519cf4db898867ae2b583a92
`validator_path`: src/governance/r_formal_experiment_package_validator.py
`validator_sha256`: 2f07eec78beba5e61973da6233111108c14b645381d5acd1262b5c6b9131468d
`compendium_sha256`: c4c0e04d2514046a130650d4ebdb2e49dfb9ff9d36598db9ef31ebb5879bf806

`tests`: tests/governance/test_r_formal_experiment_governance_contract.py; tests/governance/test_r_formal_experiment_package_validator.py; tests/test_task_index_current.py
`validator_status`: passed
`current_task_unchanged_check`: passed
`R1-T04_execution_performed`: false
`R1-T03_rerun_performed`: false
`research_parameter_change_check`: none
`formal_artifact_change_check`: none
`PR_77_superseded_action`: closed_and_remote_branch_deleted
`PR_77_superseded_by`: PR #78 / 8694cba4ddbd5a18e43ab18454dfc19cfb9903cd

## 说明

GOV-T01 是跨阶段 governance contract，不是 formal experiment，因此不生成 formal experiment result analysis 或 independent scientific review。本 evidence 记录治理规范、模板、schema/config、validator、测试和合订本哈希；不推进 R1-T04，不修改研究参数，不重跑 R1-T03，不修改 PR #78 的 formal artifacts 或研究结果。
