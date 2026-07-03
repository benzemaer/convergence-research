# A股收敛状态量化交易研究

本目录是从零启动的量化研究项目基础文档集。它定义研究目标、数据治理、研究工程、阶段路线、门禁和证据规则；在这些文件经审核冻结前，不开始任何正式数据处理、指标实现或回测。

## 文档来源

`README.md`、`AGENTS.md` 与 `docs/00_*.md` 至 `docs/05_*.md` 是基础文档的唯一权威来源。
根目录的 `A股收敛状态量化交易研究_基础文档集_合订本.md` 是由
`scripts/build_compendium.py` 按固定顺序生成的派生产物，不得手工编辑。CI 会重新生成并检查
工作树是否产生差异。

## 必备文档

| 文件 | 正式名称 | 用途 |
|---|---|---|
| `AGENTS.md` | 项目执行规则 | 为开发、研究与自动化代理提供不可违反的工作边界 |
| `docs/00_研究章程.md` | 研究章程（Research Charter） | 固定研究命题、边界、核心概念与最终问题 |
| `docs/01_研究方案与预分析计划.md` | 研究方案与预分析计划（Research Protocol & Pre-Analysis Plan） | 固定研究单位、时间语义、状态—事件—标签关系与分析纪律 |
| `docs/02_数据治理与时点一致性规范.md` | 数据治理与时点一致性规范（Data Governance & Point-in-Time Specification） | 规定数据源、快照、公司行为、复权和数据契约 |
| `docs/03_可复现研究工程标准.md` | 可复现研究工程标准（Reproducible Research Engineering Standard） | 规定仓库、代码、测试、运行、CI、版本与审计要求 |
| `docs/04_阶段与门禁框架.md` | 阶段与门禁框架（Stage–Gate Framework） | 定义 D0–D3、R0–R6 与 G0–G7 的关系 |
| `docs/05_证据与产物治理政策.md` | 证据与产物治理政策（Evidence & Artifact Governance Policy） | 规定候选、验证、冻结、发布及结论边界 |
| `templates/` | 正式记录模板 | 用于 Step 设计、运行清单、实验记录和决策记录 |

## 启动顺序

1. 审核并冻结 `docs/00_研究章程.md`。
2. 补齐其余文件中的 `[待决策]` 项并冻结。
3. 建立仓库目录、配置样板、manifest 和模板。
4. 从 D0 开始执行；未通过门禁不得提前进入后续阶段。
5. 任何正式产物均必须能追溯到本目录中定义的规则。

## 治理校验

```bash
python scripts/build_compendium.py --check
python scripts/validate_manifests.py
python scripts/validate_configs.py
ruff format --check scripts tests
ruff check scripts tests
python -m unittest discover -s tests -v
git diff --check
```

上述命令只校验治理文件与示例，不执行数据处理、特征计算或研究运行。
