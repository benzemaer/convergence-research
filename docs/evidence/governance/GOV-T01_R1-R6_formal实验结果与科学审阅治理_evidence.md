# GOV-T01 R1-R6 formal 实验结果包、异常门禁与科学审阅治理 evidence

`task_id`: GOV-T01
`status`: completed
`task_class`: governance_contract
`code_commit`: d9f566809ab8af3e20ed11fe6e925989cc365345

`engineering_standard_path`: docs/03_可复现研究工程标准.md
`engineering_standard_sha256`: 65d09f4c23d81581786fb564a259fc6337e12f3a94a13d1e6637a540da8d1d8b
`task_template_path`: docs/templates/R_FORMAL_EXPERIMENT_TASK_TEMPLATE.md
`task_template_sha256`: 2c35a102594a0144258192f7062437a8a8784d5bb38e89fc86327c6befc7e99f
`analysis_template_path`: docs/templates/R_FORMAL_EXPERIMENT_RESULT_ANALYSIS_TEMPLATE.md
`analysis_template_sha256`: 990549ea8e85e13360b65a5cb300c233b33e7dd5a0fcf4162067e629e57551da
`review_template_path`: docs/templates/R_FORMAL_EXPERIMENT_SCIENTIFIC_REVIEW_TEMPLATE.md
`review_template_sha256`: 40c613f5a7acdc8eced9cf163a98705bfc8a4473b54c39dd44cd9cf59afee050
`evidence_template_path`: docs/templates/R_FORMAL_EXPERIMENT_EVIDENCE_TEMPLATE.md
`evidence_template_sha256`: 06b3f063a67b70d09449ba5c671711dad20402d77175909e91fa7f2f8c9c3aef
`PR_template_path`: .github/PULL_REQUEST_TEMPLATE/formal_experiment.md
`PR_template_sha256`: 479bd058b61b73e906fb852c3e2ab819c9ebb8e3e1f2217057bac2b6e5e990d3

`governance_config_path`: configs/governance/r_formal_experiment_governance.v1.json
`governance_config_sha256`: 69899456e8c7316b207d6a1a362c2180bddf4f2ac3290fa989d44a37882422ab
`governance_schema_paths`: schemas/governance/r_formal_experiment_governance.schema.json; schemas/governance/r_formal_experiment_result_package.schema.json; schemas/governance/r_formal_experiment_scientific_review.schema.json
`governance_schema_sha256`: 215c2a50ad13df94e850f341b1ea39557c9e389752b8d0f0e88186578990d9c0; dae7e6b428dee14bfd476614791c5b182523c7f39492e54274665484e53bc172; e56df5d6352eb0bfa05df5f681e1478ff35c3eb4519cf4db898867ae2b583a92
`validator_path`: src/governance/r_formal_experiment_package_validator.py
`validator_sha256`: acea6d8b40257ea549de219d27a9a1ba5627ed80dddf0e55811f61b035472dca
`compendium_sha256`: 348cb2ac42c41c0914cb3cf19717b5b487291292db1cb0562fd8eb6ed01a04c0

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
