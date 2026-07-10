# A股收敛状态量化交易研究：基础文档集（合订本）


---

<!-- 由 scripts/build_compendium.py 生成；请勿手工编辑。 -->


---

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
| `docs/stages/` | 研究阶段纲领稳定入口 | 保存 R0–R6 阶段纲领，用于阶段级设计说明和下游交接；不作为正式产物、运行记录或门禁证据目录 |
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


---

# AGENTS.md
## A股收敛状态量化交易研究

本文件是项目内所有开发、研究、数据处理、自动化代理、脚本执行与代码审查的最高执行规则。若局部目录存在更严格的 `AGENTS.md`，可补充但不得放宽本文件规则。

## 1. 项目目标

本项目研究 A 股个股是否进入由 P、C、T、V 四个维度共同构成的收敛状态，研究状态何时形成、何时释放、释放后路径如何演化，以及在严格交易约束下是否具有可交易价值。

- **P — Price Compression**：价格压缩；
- **C — Reference-Price Convergence**：参考价格趋同；
- **T — Trend Neutrality**：趋势中性；
- **V — Participation Contraction**：参与度收缩。

研究顺序必须遵守：先定义状态，后研究释放；先冻结定义，后研究交易价值。

## 2. 最高原则

1. 研究定义先于代码；代码先于正式运行；正式运行先于结论；结论先于下游使用。
2. R0–R2 不得使用未来收益、未来波动扩张、未来突破方向、未来路径或回测收益选择指标、参数或事件规则。
3. 原始交易价格、公司行为事实和连续研究价格必须分层保存，禁止覆盖或混用。
4. 所有正式结果必须可追溯至数据版本、代码提交、配置哈希、运行环境、输入哈希和输出哈希。
5. 任何未通过门禁的结果只可标记为探索性，不得作为正式证据。
6. 冻结产物不可覆盖。实质变更必须创建新版本，并重新经过相应门禁。
7. 不得通过补写文档、补充说明或重命名，追认未按规则产生的结果为正式证据。

## 3. 目录职责

```text
docs/              研究章程、方案、契约、工程标准、实验与决策记录
configs/           数据、运行与研究参数的版本化配置
src/               可复用实现
scripts/           薄入口；仅做参数解析、编排、日志和退出码
tests/             单元、合成、集成、回归与契约测试
data/raw/          原始数据快照，只读
data/external/     外部公司行为、主数据与参考数据快照，只读
data/interim/      可重建中间数据
artifacts/         candidate、validated、frozen、released 产物
manifests/         数据、运行与产物清单
logs/              运行日志
```

核心逻辑只能进入 `src/`。不得把正式业务逻辑仅保留在 Notebook、临时脚本或手工操作中。

## 4. 数据与时间语义

每个正式数据表必须定义数据源、许可证、抓取时间、快照版本、SHA-256、主键、代码体系、交易日字段、时区、字段类型、单位、缺失值和异常值规则。

对任意时点 `t`，状态只能使用 `observed_at ≤ t` 的信息。若数据发生历史修订，必须明确采用“最终修订历史”还是“当时可得历史”。

## 5. 价格、公司行为与交易约束

必须同时维护：

```text
raw_open/raw_high/raw_low/raw_close
adj_open/adj_high/adj_low/adj_close
adjustment_factor
factor_as_of_time
corporate_action_flag
trading_status
price_limit_status
raw_gap
adjusted_gap
gap_attribution
```

- P、C、T 默认使用连续研究价格；
- V 使用经明确归一化的成交额、换手率、流通股本或其他参与度代理；
- 订单、成交、涨跌停、停牌、滑点和成本使用原始交易事实层；
- 公司行为产生的机械缺口不得直接解释为普通市场跳空、趋势变化或释放；
- `unknown`、缺失或低质量状态不得静默转换为 `False`。

## 6. 阶段与门禁

```text
数据产品层：D0 → D1 → D2 → D3
研究主线：R0 → R1 → R2 → R3 → R4 → R5 → R6
横向门禁：G0 → G1 → G2 → G3 → G4 → G5 → G6 → G7
```

所有正式 Step 必须通过：

- G0：立项与契约；
- G1：设计审核；
- G2：测试与合成样本审核；
- G3：代码审核；
- G4：运行授权；
- G5：运行验收；
- G6：产物与结论审核；
- G7：关闭与冻结。

未通过前一门禁，不得进入后一门禁。

## 7. 代码、配置与测试

- 所有研究参数必须来自版本化配置，禁止隐式常量或 Notebook 临时参数。
- 新功能必须附带测试；缺陷修复必须附带回归测试。
- 合成测试至少覆盖公司行为、停复牌、涨跌停、缺失日、重复数据、乱序、NaN、窗口不足、事件冲突和多线程一致性。
- 正式运行前必须通过静态检查、单元测试、合成测试、契约测试和最小集成测试。
- 单线程基线与正式 worker 数必须在文件集合、schema、主键、排序、事件边界和关键统计量上满足预先声明的一致性要求。
- 不得用 `fillna(0)` 掩盖 NaN 差异。

## 8. 运行、日志与产物

每次正式运行必须记录：

```text
run_id
stage / step
data_version
input hashes
code commit
environment lock hash
config hash
random seed
parallel mode
worker count
start/end time
exit code
peak memory
output paths and hashes
```

长任务必须输出 heartbeat。异常必须包含证券、日期、配置键和输入版本；捕获后必须重新抛出或以非零退出码结束。

产物生命周期：

```text
draft → candidate → validated → frozen → released
```

没有 manifest 的产物不得进入 `validated`、`frozen` 或 `released`。

R1-R6 formal experiment 必须遵守 `docs/03_可复现研究工程标准.md` §12.8-12.14：工程 validator 通过不等于科学结果通过；正式运行后必须立即读取并分析真实结果包；author-draft 阶段不得自行设置 `scientific_review_status=passed` 或推进 downstream gate；superseded 结果不得作为当前 evidence、formal input、参数选择或 README gate 依据。

## 9. Pull Request 与变更控制

- `main` 只接受通过审核与 CI 的 PR。
- `README.md`、`AGENTS.md` 与 `docs/00_*.md` 至 `docs/05_*.md` 是基础文档唯一权威来源；根目录合订本只能由 `scripts/build_compendium.py` 生成，禁止手工编辑。
- 数据集、运行和产物 manifest 必须分别通过 `schemas/` 中对应的 JSON Schema；不得用运行清单替代数据集或产物清单。
- 每个 PR 必须说明目标、非目标、受影响阶段、数据/参数/schema/统计定义变化、验证结果、风险与回退方案。
- 数据源、公司行为、连续价格、PCVT 指标、事件规则、未来标签、对照组、交易成本等任何变化，均必须在决策记录中登记，并评估需要回退到哪个阶段。
- 任何影响冻结状态定义的变更，必须创建新版本，不得修改旧版本。

## 10. 结论纪律

正式结论必须区分：

1. 直接统计事实；
2. 基于事实的有限推断；
3. 尚未验证的机制解释；
4. 不适用范围；
5. 需后续阶段回答的问题。

未经 R5 样本外与交易约束验证，不得宣称稳定交易优势。不得将相关性写成因果，不得将探索性结果写成冻结结论。

## 11. 禁止事项

- 禁止未来数据泄漏；
- 禁止直接修改 `data/raw/` 或 `data/external/`；
- 禁止覆盖 frozen 产物；
- 禁止绕过 G0–G7；
- 禁止在脚本中硬编码正式研究参数；
- 禁止吞掉异常后继续发布结果；
- 禁止提交大规模原始数据、密钥或许可证文件；
- 禁止用非版本化、不可追溯数据支撑正式结论；
- 禁止把供应商标签（例如“前复权”）当作时点一致性的充分证明。


---

# 研究章程
## A股收敛状态量化交易研究

> 文档类别：Research Charter
> 状态：草案
> 版本：0.1
> 研究对象：[待决策：市场、证券范围与频率]
> 生效条件：经审核冻结后，作为项目最高层研究约束

研究阶段纲领稳定入口位于 `docs/stages/`，当前执行 task 状态以 `docs/tasks/README.md` 为准；研究章程不维护 `current_task`。

---

## 1. 研究目的

本项目研究股票价格与交易参与特征是否会形成可识别的“收敛状态”，该状态在何时被确认、何时释放，以及释放后的价格路径和交易约束如何演化。

项目不以直接预测单日涨跌或寻找历史最优收益参数为起点。研究首先建立满足时点一致性、可解释性、可复现性和可冻结性的状态识别框架；仅在状态定义冻结后，才研究释放、方向、幅度、路径和潜在交易价值。

## 2. 核心研究命题

在交易日 `t`，若以下四类现象同时或以预先定义的组合方式出现，则股票可能处于收敛状态：

- **P — Price Compression（价格压缩）**：价格波动、振幅或区间宽度相对历史水平收缩；
- **C — Reference-Price Convergence（参考价格趋同）**：不同周期或不同定义的参考价格之间的离散程度降低；
- **T — Trend Neutrality（趋势中性）**：价格运动的方向性减弱、消失或进入预先定义的中性区域；
- **V — Participation Contraction（参与度收缩）**：成交与流动性参与度相对历史水平收缩。

`P ∧ C ∧ T ∧ V` 是“枯竭型收敛”的候选状态，并不预设为唯一有效的收敛类型。`P ∧ C ∧ T ∧ ¬V` 等中间状态必须保留，用于检验价格结构收敛与参与度收缩是否具有不同后续行为。

## 3. 研究问题

### 3.1 状态识别

1. 在不使用未来信息的前提下，如何在任意交易日识别 P、C、T、V 的观测状态？
2. 四个维度的联合状态是否显著区别于随机共现、样本结构或市场共同波动所能解释的结果？
3. 状态的开始日、确认日、持续区间、终止日和事件锚点应如何定义？

### 3.2 状态释放

4. 收敛状态在何种可观察条件下被认定为“释放”？
5. 不同收敛状态的释放率、释放时间和释放机制是否存在结构性差异？
6. 公司行为、停复牌、涨跌停、流动性约束和市场环境如何影响释放的识别？

### 3.3 路径与交易

7. 释放后价格的方向、幅度、持续期、回撤、跳空与波动路径如何演化？
8. 在冻结的风险集、对照组、样本外设计和交易约束下，状态是否具备可交易价值？
9. 研究结论在哪些市场、股票类型、时间段或流动性条件下不适用？

## 4. 非目标与禁止推断

在状态定义冻结前，项目不得：

- 使用未来收益、未来突破方向、未来最大振幅或交易收益选择 PCVT 指标和参数；
- 将“状态存在”直接推断为“必然上涨”或“具有交易价值”；
- 将观察到的历史关联表述为因果关系；
- 在未冻结状态定义时开展优化型回测；
- 将公司行为导致的机械价格断层解释为普通市场跳空或状态释放；
- 将探索性分析写成正式证据。

## 5. 研究对象、时间范围与分析单位

| 项目 | 当前要求 |
|---|---|
| 市场范围 | [待决策] |
| 证券类型 | [待决策] |
| 样本宇宙 | [待决策：全市场 / 指数成分 / 流动性筛选宇宙] |
| 时间范围 | [待决策] |
| 最早可分析日期 | 由最长窗口、预热期及公司行为完整性共同决定 |
| 频率 | [待决策：默认日频；更高频需单独立项] |
| 基本主键 | `security_id × trading_date × data_version` |
| 分析单位 | 股票—交易日、状态区间、事件、风险集成员 |

若采用指数成分、流动性筛选或行业分类，必须使用历史时点版本；不得以事后成分表替代历史可得宇宙。

## 6. 信息集与时间语义

每项正式观测和结论必须标明：

- `observed_at`：信息实际被系统获得的时间；
- `effective_date`：信息对哪一个交易日生效；
- `as_of_time`：计算允许使用的信息截止时点；
- `signal_time`：状态信号形成的时点；
- `confirmation_time`：状态被确认的最早时点；
- `event_anchor_time`：事件锚点；
- `trade_time`：若用于交易，最早可执行时点；
- `label_end_time`：后续标签窗口结束时点。

任何依赖后续连续天数确认的状态，都必须区分“区间起点”和“实时确认时点”。前者用于描述，后者才可能用于交易或准实时决策。

## 7. 研究路线

项目采用“数据产品层 + 研究主线 + 横向门禁”的结构：

```text
数据产品层：D0 → D1 → D2 → D3
研究主线：R0 → R1 → R2 → R3 → R4 → R5 → R6
横向门禁：每个 D 或 R Step 均须通过 G0 → G7
```

### 数据产品层

- `D0`：数据源资格审查、原始快照与基础审计；
- `D1`：证券主数据、交易状态、公司行为与交易日历；
- `D2`：时点一致的原始价格、连续研究价格和跳空归因；
- `D3`：跨研究复用的标准日频观测表与基础质量指标。

### 研究主线

- `R0`：PCVT 候选观测量与候选状态定义；
- `R1`：状态存在性、结构关系、稳定性与零模型检验；
- `R2`：参数、事件规则与状态版本冻结；
- `R3`：释放定义、风险集、对照组与未来标签；
- `R4`：释放后的方向、幅度、持续期与路径研究；
- `R5`：样本外验证、回测、成本与稳健性检验；
- `R6`：交易可行性、执行约束、运行监控与结论发布。

## 8. 方法原则

1. **先状态，后结果。** R0–R2 不允许通过未来表现反向选择定义。
2. **先可得性，后计算。** 仅使用 `as_of_time` 前可得的信息。
3. **先原始事实，后连续价格。** 原始成交价格与连续研究价格必须并存。
4. **先冻结，后扩展。** R2 冻结后，R3–R6 的发现不得修改同一版本状态定义。
5. **先对照，后结论。** 结构现象必须与预先定义的零模型、对照组或替代口径比较。
6. **先约束，后交易。** 回测和交易讨论必须纳入停牌、涨跌停、流动性、成本与执行时点。

## 9. 正式产出

- 可追溯的市场数据产品与数据契约；
- PCVT 指标与状态定义的版本化规格；
- 状态日、确认区间、事件和风险集数据集；
- 释放、路径、方向与幅度的统计研究结果；
- 样本外与交易约束下的验证报告；
- 结论登记册，明确事实、推断、限制与不适用范围。


---

# 研究方案与预分析计划
## A股收敛状态量化交易研究

> 文档类别：Research Protocol & Pre-Analysis Plan
> 状态：草案
> 版本：0.1
> 前置文件：`00_研究章程.md`
> 生效条件：在 R0 正式实现前冻结；后续修改必须新建版本并记录影响范围

---

## 1. 研究设计

研究被拆分为三个严格隔离的层次：

1. **状态定义层（R0–R2）**：仅使用当期及过去信息，定义并验证 PCVT 收敛状态；
2. **结果研究层（R3–R4）**：在状态定义冻结后，研究释放、方向、幅度和路径；
3. **交易验证层（R5–R6）**：在样本外和可执行约束下，检验潜在交易价值。

任何未来结果、路径标签或回测利润均不得参与状态定义层的指标选择、参数搜索或规则调整。

## 2. 分析单位

| 单位 | 主键 | 用途 |
|---|---|---|
| 股票—交易日 | `security_id, trading_date, data_version` | P/C/T/V 观测、特征与状态日 |
| 状态区间 | `state_interval_id` | 连续状态的开始、确认、结束与持续期 |
| 事件 | `event_id` | 释放、终止、失效或其他预定义锚点 |
| 风险集成员 | `risk_set_id, security_id, anchor_date` | 对照、匹配、路径与回测分析 |

所有 ID 必须包含状态定义版本、数据版本和配置版本，以防不同版本结果混合。

## 3. PCVT 候选观测量

R0 的具体候选指标、score、strict / weak 规则、`S_PCT` / `S_PCVT` 状态族和 R0 task 路线图由 `docs/stages/R0_PCVT候选观测量与候选状态定义.md` 承载。本文件只固定研究设计边界，不复制 R0 阶段纲领全文。

### P：价格压缩

候选观测量可以包括连续研究价格的滚动收益波动率、平均真实波幅、相对 ATR、区间宽度、振幅以及其历史分位位置。最终指标和窗口须在 R2 冻结。计算必须使用时点一致的连续研究价格；原始价格用于审计、交易约束与跳空归因。

### C：参考价格趋同

候选观测量可以包括多个滚动均线、VWAP、区间中枢或其他预先定义的参考价格之间的相对离散程度，以及其历史分位位置。每一种参考价格都必须有明确公式、最小有效样本、缺失规则和时点语义。

### T：趋势中性

候选观测量可以包括滚动斜率、趋势强度、方向连续性、方向切换频率，以及价格相对参考价格的方向性偏离。趋势中性不等于价格不动；它必须与 P、C 有清晰的概念边界，避免同一信号被重复计入多个维度。

### V：参与度收缩

候选观测量可以包括成交额、换手率、流通股本或自由流通市值归一化后的参与度、流动性指标及其他经批准的市场参与代理。成交量绝对值不得单独作为 V 的正式定义，除非其经过份额变化、上市阶段和证券规模的明确处理。

## 4. 状态定义与确认

### 4.1 日频候选状态

每个维度对每一交易日输出：

```text
valid / invalid / unknown
```

- `valid`：维度满足预设条件；
- `invalid`：维度不满足预设条件；
- `unknown`：数据不足、交易异常、缺失、不可观测或不适用。

不得把 `unknown` 静默转换为 `False`。

联合状态至少明确：

```text
S_PCT  = P ∧ C ∧ T
S_PCVT = P ∧ C ∧ T ∧ V
```

### 4.2 确认区间

状态日不自动等于可研究事件。确认区间至少规定：最短连续有效日数、允许缺口、缺口是否可跨越停牌或公司行为日、区间开始/确认/结束规则、冷却期和去重规则，以及多个区间的合并分割规则。

确认规则一经 R2 冻结，不得因 R3–R6 的后续表现修改。

## 5. 结构验证与零模型

R1 至少覆盖：

1. 状态在时间、股票、行业和市场环境中的频率与覆盖率；
2. P、C、T、V 的共现、条件保留率与独立性诊断；
3. 不同年度、流动性层级、市场状态和股票子集的稳定性；
4. 合理替代定义、窗口和分位计算方式的比较；
5. 保留边际频率、时间结构或股票异质性的预设零模型；
6. 确认区间长度、碎片率、重叠率、重复触发和冷却期影响；
7. 原始价、连续价、公司行为标记和不同数据源口径的差异归因。

R1 的结论仅限于状态结构是否存在、是否稳定、是否超出指定零模型；不得写成未来预测结论。

## 6. 冻结规则

R2 冻结至少包含：数据版本与样本宇宙、P/C/T/V 指标、窗口、阈值、分位规则、最小样本要求、缺失/停牌/涨跌停/公司行为规则、状态日、确认区间、事件锚点、冷却期、输出 schema 与 manifest。

任何实质变更均创建新状态版本，并独立完成 R0–R2；不得覆盖旧版本。

## 7. 释放、路径与未来标签

R3 在状态版本冻结后定义释放。释放定义应区分：

- 状态失效；
- 波动释放；
- 方向释放；
- 交易释放；
- 由公司行为、停复牌、退市、涨跌停或数据缺失导致的异常终止。

每一种释放均须有明确的可观察时点、窗口、右截尾规则和冲突优先级。

路径研究至少预先定义：未来收益、最大上行/下行、实现波动、回撤、持续期、跳空、成交额、流动性、方向分类、观察窗口、竞争风险或多事件处理、以及停牌/退市/涨跌停的处理规则。

## 8. 样本隔离

项目至少划分：设计样本、验证样本、冻结后评估样本和时间前推/样本外样本。若数据长度不足，必须预先声明滚动、扩展窗口或时间分块替代方案，并明确限制。不得用相同样本反复筛选、验证和最终宣称。

## 9. 报告要求

每次正式报告至少包含：样本宇宙、时间范围、数据版本、状态版本、分析单位数、股票数、状态日数、区间数、事件数、排除原因、点估计与不确定性、参数搜索说明、零模型或对照组、稳健性设计，以及不适用范围。

## 10. 变更控制

PCVT 指标、窗口、阈值、逻辑关系、样本宇宙、数据源、公司行为规则、连续价格规则、确认区间、事件锚点、标签、对照组和回测规则的改变，均构成研究设计变更。变更必须写入决策记录，并说明受影响阶段与重跑范围。


---

# 数据治理与时点一致性规范
## 市场数据、公司行为与连续价格的数据契约

> 文档类别：Data Governance & Point-in-Time Specification
> 状态：草案
> 版本：0.1
> 生效范围：D0–D3、R0–R6 的全部正式数据输入与输出

---

## 1. 目的

本规范确保数据具有明确来源、许可边界、时间语义、版本、可追溯性和可重建性。目标不是寻找单一“最真实”的供应商价格，而是建立能够区分原始交易事实、公司行为事实和连续研究价格的可审计数据体系。

## 2. 数据产品层

### D0：数据源资格审查与原始快照

D0 负责数据源评估、许可证、访问方式、频率限制、原始文件/API 响应快照、字段字典、代码体系、单位精度审计、行数日期范围主键检查、数据源版本、抓取时间、哈希与 manifest。

D0 不改写原始字段，不在原始数据上直接计算研究特征。

### D1：市场事实账本

D1 建立证券主数据、交易日历、上市退市、停复牌、风险警示、涨跌停和可交易性、分红送股配股拆并股代码变更、行业板块和历史时点成分等可追溯事实表。D1 不混入研究解释或状态判断。

### D2：时点一致价格体系

D2 建立三套互相可追溯的数据：

1. `raw_price`：原始 OHLCV 与成交额，反映实际交易价格；
2. `adjustment_events / factors`：公司行为事件及复权因子；
3. `asof_adjusted_price`：在给定 `as_of_time` 下构造的连续研究 OHLC。

原始价与连续价必须并存，禁止覆盖。

### D3：标准化市场观测

D3 产出可跨课题复用的中性观测：交易状态、可交易标记、原始与连续 OHLCV、成交额、换手率、流通股本、基础归一化字段、基础滚动统计、公司行为/停复牌/跳空归因标签。D3 不包含 PCVT 最终阈值、联合状态或未来标签。

## 3. 数据契约

每张正式表必须声明：

| 类别 | 必须内容 |
|---|---|
| 身份 | 表名、版本、owner、用途、证据等级 |
| 来源 | 数据源、许可证、抓取方式、抓取时间、快照标识 |
| 键 | 主键、唯一性、连接键、代码体系 |
| 时间 | `trading_date`、`observed_at`、`effective_date`、`as_of_time` 语义 |
| 字段 | 类型、单位、精度、缺失值、值域、派生逻辑 |
| 质量 | 完整性、重复、异常、容差、审计断言 |
| 版本 | 输入哈希、代码提交、配置哈希、schema 版本 |
| 使用 | 允许进入哪些 D/R 阶段，禁止进入哪些阶段 |

没有数据契约的表不得进入正式研究。

## 4. Point-in-Time 原则

任意计算时点 `t`，仅允许使用 `observed_at ≤ t` 的信息。若同时存在事件发生时间、公告时间、除权生效时间和供应商更新时间，必须全部保存并明确用途。

历史修订必须保存快照日期和哈希；项目需明确采用“最终修订历史”还是“当时可得历史”。需要严格回测或实时重放的任务，必须使用 point-in-time 快照或可重建的 as-of 版本。

## 5. 原始价格、连续价格与公司行为

### 5.1 原始交易事实

`raw_open/raw_high/raw_low/raw_close` 用于交易可行性、涨跌停、停复牌、原始跳空审计、订单成交成本和外部数据对账。

### 5.2 连续研究价格

`adj_open/adj_high/adj_low/adj_close` 用于 P、C、T 研究、多窗口参考价格、波动区间趋势与连续路径。连续价格必须附带：

```text
adjustment_factor
factor_as_of_time
factor_source
factor_version
corporate_action_event_id
```

### 5.3 公司行为

公司行为至少保存：

```text
security_id
event_type
announcement_time
record_date
effective_date
cash_dividend
stock_dividend_ratio
rights_ratio
rights_price
split_ratio
source
source_version
observed_at
```

缺失字段必须显式标记，不得用默认值伪造完整性。

## 6. 跳空归因

必须保存：

```text
raw_gap
adjusted_gap
gap_attribution
```

`gap_attribution` 至少包括：`market_gap`、`corporate_action_gap`、`suspension_resume_gap`、`price_limit_gap`、`data_quality_gap`、`unknown`。公司行为导致的机械价格变化不得直接进入普通市场跳空、波动释放或突破统计。

## 7. 数据源资格审查

每一个候选数据源必须检查：历史覆盖和预热期、OHLCV/成交额/换手率/交易状态字段、公司行为类型和时间字段、代码和证券状态追溯、更新延迟与可用性、许可证、快照能力、以及其适合作为主源、备源或交叉验证源的角色。

“提供前复权/后复权价”本身不等于满足正式研究要求。

## 8. 数据质量验收

每次正式版本发布前至少检查：文件集合、schema/dtype、主键、日期和证券覆盖、价格逻辑、量额和单位、缺失/无穷/异常值、公司行为日期与因子变化、原始价与连续价可反推关系、与备源/历史版本差异归因，以及全部哈希。

## 9. 数据版本发布

每个正式版本必须生成：

```text
data_version
schema_version
source_snapshot_id
input_hashes
transformation_code_commit
config_hash
run_id
created_at
quality_report_path
output_hashes
```

进入 `frozen` 的数据版本不得覆盖；修订必须创建新版本并保留差异报告。

## 10. 访问与安全

API Key、账号、许可证文件不得写入代码、日志、manifest 或提交历史。原始和外部快照只读；大型数据集不得直接输出到对话、Issue 或 PR 正文；导出和共享必须遵守许可证；数据源故障或字段变更必须记录并评估下游影响。


---

# 可复现研究工程标准
## Reproducible Research Engineering Standard

> 文档类别：Research Engineering Standard
> 状态：草案
> 版本：0.1
> 生效范围：代码、配置、运行、测试、CI、产物与协作流程

---

## 1. 目标

本标准将研究工作组织为可审计、可重复、可回滚的工程流程。任何正式结论必须可以由固定的数据版本、代码提交、配置和运行环境重新生成。

## 2. 仓库原则

- 研究定义、数据契约、代码、配置、测试、manifest 与实验记录必须同仓或由不可变引用关联；
- `main` 只接受已审核 PR，不作为直接开发分支；
- 每个可独立审核任务使用独立分支；
- 提交保持单一目的，避免把数据、重构、参数和结论混入同一提交；
- 正式变更必须说明影响的 D/R 阶段、数据版本和证据等级；
- 不提交原始大数据、临时缓存、密钥、私密环境文件或无 manifest 的结果。

## 3. 建议目录结构

```text
docs/
  charter/ protocol/ governance/ standards/ contracts/
  stages/ experiments/ decisions/ reviews/
configs/
  data/ runtime/ research/
src/
  ingest/ market_ledger/ prices/ observations/ pcvt/
  events/ labels/ validation/ backtest/
scripts/
  d0/ d1/ d2/ d3/ r0/ r1/ r2/ r3/ r4/ r5/ r6/
tests/
  unit/ synthetic/ integration/ regression/ contracts/
data/
  raw/ external/ interim/ reference/
artifacts/
  candidate/ validated/ frozen/ released/
manifests/
  data/ runs/ artifacts/
logs/
```

具体实现可以调整，但输入快照、代码、配置、测试、产物、manifest 和实验记录必须有明确边界。
`docs/stages/` 是 R0–R6 阶段纲领稳定入口，用于保存阶段级目标、边界、定义、路线图和交接说明；它不替代 task 文档、运行 manifest、数据/产物 manifest、decision record 或 G0–G7 证据。
上例中的 `scripts/ d0/ d1/ d2/ d3/ r0/ ... r6/` 是早期目录边界示意，不改变 D3-T09
确立后的 R 阶段规则：D0–D3 历史 scripts 可以保留现状；从 R0 开始，R 阶段核心逻辑必须进入
`src/r0` 至 `src/r6`；R 阶段如有脚本入口，只能作为调用 `src` 模块的薄 wrapper，不得作为核心实现入口。

## 3.1 R 阶段工程分层

D0–D3 已形成的历史实现文件作为 legacy data-product implementation layer 保留。本规则不追溯迁移、重命名或删除既有 D 阶段 `scripts/`、`tests/`、`schemas/`、`configs/` 或 task 文件。若未来需要整理 D 阶段历史结构，必须另开专门 refactor PR，且不得混入研究逻辑变化。

从 R0 开始，R0–R6 作为 research implementation layer 必须按阶段分层。若某阶段尚无实现文件，可以不创建空目录；一旦新增 R 阶段实现文件，必须放入对应阶段目录：

```text
src/
  r0/
  r1/
  r2/
  r3/
  r4/
  r5/
  r6/
tests/
  r0/
  r1/
  r2/
  r3/
  r4/
  r5/
  r6/
schemas/
  r0/
  r1/
  r2/
  r3/
  r4/
  r5/
  r6/
configs/
  r0/
  r1/
  r2/
  r3/
  r4/
  r5/
  r6/
```

R 阶段核心研究逻辑不得新增到根级 `scripts/*.py`。R 阶段代码应以 `src/r0`、`src/r1` 等阶段目录为实现入口；如需 CLI 或薄入口，应优先使用 `src` 模块入口。未来若必须增加脚本入口，该脚本只能是薄 wrapper，不得承载核心研究逻辑，也不得与 D 阶段既有平铺入口混用。R 阶段测试、schema 和 config 应与 `src` 阶段分层保持一致。

## 4. 配置即研究定义

所有正式参数必须来自版本化配置，包括：数据版本、宇宙、时间范围、指标窗口、阈值、分位规则、状态确认、缺口、冷却期、事件规则、标签窗口、对照组、并行、种子、内存和输出路径。

禁止将正式参数隐藏在脚本常量、Notebook 单元格、环境变量默认值或人工操作流程中。

## 5. 测试策略

### 单元测试

覆盖公式、边界、缺失、时间对齐、排序、主键、因子应用和异常输入。

### 合成测试

至少覆盖：正常交易、除权除息、送股、配股、拆并股、停牌复牌、涨跌停、上市退市、代码变更、缺失日、重复记录、乱序、NaN、零值、长窗口不足、多事件冲突、冷却期以及单线程/多线程一致性。

### 数据契约测试

验证 schema、字段类型、主键、日期范围、单位、值域、缺失语义和来源 manifest。

### 回归测试

对冻结小样本保存预期输出。任何核心逻辑修改都必须比较状态、事件、因子、排序和关键统计量。

### 集成测试

验证从小型输入快照到最终产物的最小闭环，并检查 manifest 与日志生成。

## 6. 运行与可复现性

每次正式运行必须记录：

```text
run_id
stage / step
data_version
input manifests and hashes
code commit
environment lock hash
config path and hash
random seed
parallel mode
worker count
start/end time
exit code
peak memory
output paths and hashes
```

运行命令必须可由 manifest 重放；环境需有锁文件、容器标识或等效不可变记录。

## 7. 并行与确定性

- 先建立单线程正确性基线；
- 仅允许一个并行层级：参数、证券、重采样或模型折中择一；
- 不得依赖任务完成顺序决定种子、排序或输出；
- 单线程与正式 worker 数必须在预先声明的语义层面一致；
- 数值容差逐列声明；
- 不得用 `fillna(0)` 掩盖 NaN 差异；
- 额外、缺失、乱序或 dtype 改变必须被比较工具明确报告。

## 8. 日志、异常与资源

正式任务须输出标准日志和 heartbeat，记录当前配置、进度、资源、耗时和异常上下文。异常必须携带证券、日期、配置键和输入版本，并以重新抛出或非零退出结束。禁止“记录错误后继续生成正式产物”。

## 9. PR 与代码审核

每个正式 PR 至少包括：目标和非目标、受影响 D/R 阶段、数据/schema/参数/统计定义/结论是否变化、测试与 CI、关联设计/决策/manifest/实验记录、风险、回退和下游影响。

审核至少检查：设计一致性、前视、时间错位、错误 `merge_asof`、索引混用、缺失/停牌/公司行为/涨跌停处理、隐式参数、吞异常、非确定排序和产物覆盖。

## 10. CI 最低门槛

CI 至少包括：格式与静态检查、单元与合成测试、数据契约测试、最小集成测试、`git diff --check`、配置 schema 校验、正式 PR 的 manifest/文档完整性检查。影响数据转换或状态事件算法的 PR 需运行固定小样本回归检查。

## 11. 版本与回滚

数据、代码、配置、产物和研究定义分别版本化。`frozen` 不可覆盖。发布必须给出输入版本、输出版本和变更摘要。发现错误时必须记录影响范围、修复、重跑范围和是否撤销结论。

## 12. R阶段正式运行、物化与交接 PR 规范

本节约束 R1–R6 后续所有 formal analysis、formal materialization、audit 和 handoff PR。R0-T10 formal materialization 已验证的工程规则在此固化为 R 阶段通用规范；后续 PR 不得把这些规则降级为单一任务经验或可选建议。

### 12.1 适用范围

本节适用于 R1–R6 中所有会产生 formal artifact、manifest、evidence、audit report、handoff 或推进 README gate 的 PR。contract-only、synthetic-only、smoke-only PR 可以完成代码和契约验证，但不得声称完成 formal run。R 阶段任何正式结论必须绑定 evidence、validator 和 manifest；R 阶段不得绕过上一阶段 evidence chain 直接读取本地 loose artifact，也不得把 optional、blocked 或 diagnostic artifact 标记为 formal input。

### 12.2 两阶段推进

R 阶段 formal PR 默认采用两阶段推进。第一阶段提交代码、CLI、validator、tests 和 task doc，不得推进 downstream gate。第二阶段在真实运行后提交 evidence、hash、row count、coverage 和 validator result。没有真实运行 evidence 不得把 task 标记 completed；没有 validator passed 不得推进 README。代码完成不等于研究完成，artifact 生成完成也不等于下游授权完成。

### 12.3 Evidence 最小字段

Formal evidence 至少记录以下字段：

```text
task_id
status
run_id
code_commit: full 40-char SHA
input_evidence_paths / sha256
input_artifact_paths / sha256
input_row_counts
input_security_count
input_date_min / input_date_max
config / grid / parameter coverage
output_paths / sha256
output_row_counts
validator_command
validator_status
forbidden_field_check
lineage_check
full_code_commit_check
manifest_contains_row_payload: false
summary_contains_row_payload: false
downstream_gate_allowed
<next_task>_allowed_to_start
```

Evidence 不得嵌入 row payload，不得复制 DuckDB、Parquet、CSV 或 JSONL 内容；只能记录路径、hash、counts、coverage、gate 和 validator result。`code_commit` 必须是完整 40 位 SHA，短 SHA 禁止用于 formal run。如果历史 evidence 存在短 SHA，只能作为历史事实保留，不得扩散到新 PR。

### 12.4 R阶段入口分层硬规则

R 阶段 builder、materializer、validator、audit generator 和 handoff generator 的核心实现必须在 `src/rN`。`scripts/rN` 只能是 thin wrapper，不得承载 DuckDB 查询、核心 SQL、validator 规则、hash gate、evidence 解析、参数网格或业务常量。tests、schema 和 config 必须按阶段目录分层，不得新增 root-level R tests/config/schema 平铺文件。D0–D3 历史文件不追溯迁移。

### 12.5 Resume、失败与监控

Partial artifact 不得视为 completed，FAILED marker 不得被 resume 跳过。DONE marker 必须绑定 input hash、config hash、code commit、output hash、schema 和 row count。任一 chunk 或 config failed 时，不得写 completed global manifest，不得设置 `downstream_gate_allowed=true`，必须保留 FAILED marker、traceback/log 和 retry command。Summary 可以写 failed 或 incomplete，但不得伪装成 formal success。Resume 只能在 DONE marker、hash、schema、row count、input manifest 和 code commit 全部一致时跳过。监控字段至少包含 completed/skipped/failed/pending counts、DONE/FAILED marker count、partial usage、worker count、DuckDB threads 和 memory limit。

### 12.6 并发与 DuckDB 写入

对按证券独立的量化计算，必须提前预估内存占用；如果每个 worker 最大占用不超过 1G，worker 默认允许 `--max-workers 16`，建议允许范围 `1..16`。默认只允许一个并行层级，`ProcessPoolExecutor` 必须显式使用 `multiprocessing.get_context("spawn")`。Worker 不得返回 row payload，parent process 不得持有全量 rows。DuckDB worker threads 默认 1，per-worker memory limit 必须显式记录。正式大规模运行不得以 Python 逐行 insert / executemany 作为主写入路径，应优先使用 DuckDB native scan、CTAS、COPY、`read_parquet`、Parquet/Arrow shard。大规模 JSONL 只能作为 shard exchange，不得作为 monolithic production input payload；formal production input 必须是 manifest/artifact-backed，而不是 full row payload JSON。Output ordering 必须 deterministic，row count、hash、coverage 必须可复算。

### 12.7 Validator、README gate 与下游授权

Validator 必须独立复核 source evidence hash、input artifact hash、forbidden fields、lineage、row payload absence、full SHA、一致性和 coverage。Validator result 必须写入 formal evidence。README 只能在 evidence completed 且 validator passed 后推进。下游 task 只能消费 evidence-bound artifacts；不得用后续成功追认前序失败。Optional、blocked 或 diagnostic artifact 不得被标记为 formal input。Validator 字段不得硬编码 passed，必须由实际检查产生。

### 12.8 Formal 实验结果包

R1-R6 中所有参数比较、状态画像、统计检验、Lift / retention / conditional probability、零模型、稳定性分析、敏感性分析、事件研究、预测评估、模型评估、组合或策略评估，均属于 formal experiment。contract-only、schema-only、refactor-only、synthetic-only、smoke-only，以及不产生研究结论的纯 materialization 可以豁免，但豁免任务不得声称完成 formal experiment。

每个 formal experiment 必须提交 clean-checkout 可审核的结果包，至少包含 `experiment_summary.json`、`primary_results.csv` 或小型 JSON、`diagnostic_summary.json`、`anomaly_scan.json`、`engineering_validation_result.json`、`result_analysis.md`、`scientific_review.json`、`scientific_review.md` 和 formal evidence。大型行级 DuckDB/Parquet 不提交，但必须记录 path、sha256、schema、row_count、security_count、date_min/date_max 和 input manifest。

### 12.9 结果分析报告

每个 formal experiment 必须提交作者结果分析报告，至少包含以下章节：研究目标与预注册问题；输入 package、lineage、时间与样本范围；参数网格与 reference baseline；核心结果；预期结果与实际结果对照；coverage / NULL / unknown / blocked / denominator 检查；baseline 与至少两个 challenger 对照；参数响应与敏感性；层级、漏斗、守恒关系与不变量；异常结果及根因调查；替代解释与反证检查；研究限制；可以支持的结论；不可以支持的结论；下游 gate 建议。

报告必须明确区分 `observed_fact`、`derived_statistic`、`inference` 和 `research_judgment`。禁止把描述性差异写成显著性结论，禁止把相关性写成因果关系，禁止把 reference baseline 写成最优参数，禁止把 validator passed 写成科学结论通过，禁止只复制 summary counts 而不分析结果。

### 12.10 运行后即时合理性审查

Codex 或其他执行代理完成正式运行后，必须立即读取真实结果 artifacts，而不是只检查 runner、validator、hash 和 manifest。即时审查至少覆盖：主输出是否非空，是否全部为 0、全部为 1 或全部为 NULL，valid / unknown / blocked 是否合理，参数变化是否产生符合定义的响应，理论上依赖参数的输出是否完全相同，嵌套状态是否满足集合包含，漏斗比例是否可对账，分母是否为 0，样本量是否足够，结果是否与上游 availability / eligibility / reason codes 一致，是否出现数量级突变，是否存在字段名、单位、join key、时间对齐、validity propagation 问题，以及是否存在未来信息或后验选择。

发现异常后必须优先调查字段契约、输入 lineage、schema 映射、单位、join、eligibility、validity propagation、时间语义、窗口语义、状态生成和确认逻辑。不得先调参数，不得先将异常解释为“输入事实”。

### 12.11 强制异常阻断条件

以下情况是 formal experiment 的 hard blocker：主要状态或事件在所有配置下均为 0；主要指标全样本 NULL；关键指标 0% valid；关键指标异常 100% valid 且无解释；理论上受参数影响的输出完全不响应参数；nested invariant 失败；confirmed=0 但 raw streak 已满足 K；分子非零但分母为 0；网格行数、样本空间或漏斗无法对账；相较前一版本出现数量级突变；下游结果与上游 availability 不一致；结论依赖未报告样本删除；结论依赖后验选参；result artifact 与 analysis report 数字不一致。

出现强制异常时，必须设置 `result_analysis_status = blocked`、`anomaly_resolution_status = unresolved`、`scientific_review_status = pending` 或 `blocked`、`downstream_gate_allowed = false`，且 README 不得推进。

### 12.12 独立科学审阅

实现代理不得自我标记 `scientific_review_status = passed`。Codex 在首次推送 formal experiment PR 时最多只能设置 `author_result_analysis_status = passed`、`scientific_review_status = pending`、`downstream_gate_allowed = false`。

独立 reviewer 必须直接读取 committed result artifacts 和 `result_analysis.md`，独立复算至少一个核心 count / ratio / statistic，检查 baseline 与至少两个 challenger、参数响应、coverage / NULL / unknown / blocked、状态漏斗和不变量，提出至少一个替代解释，检查结论是否超出证据，并记录 blocking 与 nonblocking findings。

### 12.13 上游变更、结果失效与 supersession

任何上游 data package、字段契约、指标定义、eligibility、validity、状态生成、confirmation、manifest、config、schema 或 formal input hash 变化，都会使依赖结果自动 superseded。Superseded 结果不得继续作为当前 evidence、formal input、参数选择依据、冻结依据、研究结论或 README gate 依据。

被 superseded 的旧 PR 应关闭而不是 rebase，说明 `superseded_by`，链接替代 PR 或 commit，保留历史审计记录，删除无用远端分支，并且不得 cherry-pick 旧 result artifacts。

### 12.14 Draft → Scientific Review → Final Gate 三阶段流程

R1-R6 formal experiment 采用双门禁。工程门禁检查代码、配置、lineage、hash、manifest、determinism、validator 和无前视；科学结果门禁检查结果包完整、作者结果分析完成、异常已解释、独立科学审阅通过且结论没有超出证据。下游放行必须同时满足 `engineering_validator_status = passed`、`result_artifact_status = passed`、`author_result_analysis_status = passed`、`scientific_review_status = passed`、`anomaly_resolution_status = passed` 或 `not_applicable`、`superseded = false`、`downstream_gate_allowed = true`。

工作流顺序为：Phase A 提交代码、runner、task-specific validator 并完成 formal run；Phase B 提交结果包、anomaly scan 和作者 result analysis；Phase C PR 保持 draft，`scientific_review_status = pending` 且 gate=false；Phase D 独立 reviewer 审核实际 artifacts 和报告；Phase E 根据 review 修复或补充分析；Phase F 提交 scientific review record；Phase G final-gate validator passed 后才推进 README 和下游 gate。Codex 不得在 Phase B 后自行跳到 Phase G。


---

# 阶段与门禁框架
## Stage–Gate Framework for PCVT Convergence Research

> 文档类别：Stage–Gate Framework
> 状态：草案
> 版本：0.1
> 生效范围：全部数据产品阶段与研究阶段

---

## 1. 框架结构

```text
D0–D3：数据产品层
R0–R6：研究主线
G0–G7：横向门禁
```

D 阶段定义可复用数据产品；R 阶段回答研究问题；G 门禁决定某个具体 task 是否可进入下一阶段。D 与 R 不构成一条简单串行流水线，而存在明确依赖。

## 2. 数据产品层：D0–D3

| 阶段 | 名称 | 核心问题 | 最低正式输出 |
|---|---|---|---|
| D0 | Source Snapshot | 数据从何而来，是否允许使用，原始字段是否完整？ | 数据源资格报告、原始快照、字段字典、源 manifest |
| D1 | Market Ledger | 证券身份、交易状态和公司行为是否可追溯？ | 证券主表、交易日历、交易状态表、公司行为账本 |
| D2 | Point-in-Time Price | 如何区分原始价、复权因子与连续研究价格？ | 原始价表、因子表、连续价格表、跳空归因表 |
| D3 | Common Observations | 哪些中性日频观测可稳定复用？ | 标准观测面板、数据质量标记、基础滚动观测 |

D3 不发布 PCVT 联合状态，不冻结研究阈值，不产生未来标签。

## 3. 研究主线：R0–R6

| 阶段 | 名称 | 核心问题 | 最低正式输出 |
|---|---|---|---|
| R0 | Candidate State Design | 如何定义 PCVT 候选观测量与候选状态？ | 指标规格、候选配置、状态日表 |
| R1 | Structural Validation | 状态是否存在、稳定且超出零模型解释？ | 结构验证报告、替代口径比较、零模型结果 |
| R2 | State Freeze | 哪个状态版本、事件规则和参数可冻结？ | 冻结状态版本、确认区间表、事件规范 |
| R3 | Release Design | 如何定义释放、风险集、标签和对照组？ | 释放规格、风险集、标签数据集 |
| R4 | Path Analysis | 释放后方向、幅度、持续期和路径如何演化？ | 路径研究报告、统计输出 |
| R5 | External Validation | 结论在样本外、成本和交易约束下是否稳健？ | 样本外报告、回测与稳健性报告 |
| R6 | Operational Translation | 如何转化为监控或交易规则？ | 执行规范、监控指标、发布结论 |

## 4. 关键依赖

```text
D0 → D1 → D2 → D3
                    ↓
                   R0 → R1 → R2 → R3 → R4 → R5 → R6
```

必须遵守：R0 依赖 D3 的正式日频观测入口；V 依赖 D1/D3 的交易状态与参与度数据；R1/R2 只能使用冻结数据版本；R3 只能读取 R2 冻结状态；R5/R6 必须使用 D1 的真实交易约束而非仅用连续价格模拟成交。

## 5. 八级门禁：G0–G7

| 门禁 | 名称 | 目的 | 通过条件 |
|---|---|---|---|
| G0 | 立项与契约 | 确认任务合法、必要、可定义 | 目标、边界、输入、输出、时间语义、禁止事项明确 |
| G1 | 设计审核 | 确认算法与验收可审查 | 设计、公式、边界、断言、资源和回退方案明确 |
| G2 | 测试审核 | 确认正常与失败路径可验证 | 单元、合成、契约和回归测试设计通过 |
| G3 | 代码审核 | 确认实现忠实于设计 | 代码、配置、测试、文档通过审查 |
| G4 | 运行授权 | 确认输入与资源冻结 | 输入、代码、配置、环境、worker、输出路径锁定 |
| G5 | 运行验收 | 确认运行可作为候选产物 | 退出码、断言、日志、资源、manifest 完整 |
| G6 | 产物与结论审核 | 确认数据和结论在边界内成立 | 独立检查 schema、哈希、统计、差异和结论 |
| G7 | 关闭与冻结 | 确认下游可依赖 | 实验记录、版本状态、下游允许用途明确 |

未通过门禁时，task 标记为 `blocked`。不得用后续阶段的成功掩盖前序门禁失败。

## 6. Task-as-Step 的最小结构

Task 是本仓库中 Step 的实现载体。一个 Step 不再以独立的 `Sxx` 路径命名；执行、审核和关闭均以 `D3-T09`、`R0-T01` 这类 task 为最小治理单元。阶段纲领位于 `docs/stages/`，是 Stage 级设计入口，用于说明阶段目标、边界、状态定义、task 路线图和下游交接；task 是 PR 级执行载体。阶段纲领不得替代 task 文件、manifest、decision record 或 G0–G7 门禁证据。

```text
Stage
→ Task ID
→ Task document
→ Design / Gate rules
→ Tests / Validation
→ Code / Config / Schema
→ Authorized run, if any
→ Candidate artifact, if any
→ Independent review
→ Close / Freeze decision
```

`Task ID` 使用 `D/R阶段-T序号`，例如 `D3-T09`、`R0-T01`。task 文档是 step 的最小可审核载体，必须明确目标、非目标、输入、输出、验收标准、失败状态和回退方式。task 文档不得替代 run manifest、dataset manifest、artifact manifest、decision record 或 G0–G7 门禁证据。

一个 PR 只能实现一个 task。task 编号只表示阶段内执行顺序，不表示证据等级、冻结状态或研究结论强度。未通过门禁时，task 必须保持 `blocked`、`candidate`、`in_progress` 等对应状态，不得用后续成功追认前序失败。

从 R0 开始，R0–R6 作为 research implementation layer 严格按阶段分层；D0–D3 已合并实现作为 legacy data-product implementation layer，历史平铺式 `scripts/`、`tests/`、`schemas/`、`configs/` 和 `docs/tasks/` 结构暂时保留。本治理规则不追溯迁移 D0–D3 文件。

## 7. 门禁与证据等级

| 状态 | 最低已通过门禁 | 含义 |
|---|---|---|
| planned | 无 | 仅有任务设想 |
| designed | G1 | 设计已审核 |
| implemented | G3 | 代码已审核，尚未正式运行 |
| candidate | G5 | 正式运行完成，待独立产物审核 |
| validated | G6 | 产物和结论通过预设审核 |
| frozen | G7 | 可作为下游唯一正式输入 |
| released | G7 + 发布审核 | 可对外或进入最终结论 |

## 8. 阶段退出规则

- D0：主/备数据源、快照、字段和许可证已审查；
- D1：证券、交易状态、公司行为和历史时点规则可追溯；
- D2：原始价、因子、连续价与跳空归因通过质量与时间一致性测试；
- D3：标准观测面板可稳定重建，质量标记完整；
- R0：候选指标、窗口、缺失规则和联合状态明确；
- R1：存在性、结构、稳定性、替代口径和零模型证据完整；
- R2：状态、确认区间与事件规则冻结；
- R3：释放、标签、风险集和对照组冻结；
- R4：路径研究按冻结设计完成；
- R5：样本外、成本、可交易性和稳健性检查完成；
- R6：使用范围、执行约束、监控与发布边界明确。

## 9. 变更影响矩阵

| 变化 | 最低回退点 |
|---|---|
| 数据源、代码映射、原始字段变化 | D0 |
| 公司行为、停复牌、交易状态规则变化 | D1 |
| 复权因子、连续价格、跳空归因变化 | D2 |
| 基础观测的定义、质量规则变化 | D3 |
| PCVT 指标、窗口、阈值或逻辑变化 | R0 |
| 零模型、稳定性设计或样本切分变化 | R1 |
| 确认区间、冷却期、事件锚点变化 | R2 |
| 释放、标签、对照组或风险集变化 | R3 |
| 路径终点、方向分类或统计模型变化 | R4 |
| 成本、成交、执行约束或样本外设计变化 | R5 |

任何变化均须重新评估受影响下游产物的证据资格。


---

# 证据与产物治理政策
## Evidence & Artifact Governance Policy

> 文档类别：Evidence & Artifact Governance Policy
> 状态：草案
> 版本：0.1
> 生效范围：数据产品、研究结果、报告、图表、模型和发布结论

---

## 1. 目的

本政策规定如何识别、保存、审核、冻结、引用和发布研究证据。每一个结论都必须回溯至明确的数据版本、研究设计、代码、配置、运行记录和产物审计。

## 2. 生命周期

```text
draft → candidate → validated → frozen → released
```

| 状态 | 定义 | 可否用于下游 |
|---|---|---|
| draft | 仍可能改变的实现、数据或分析 | 不可作为正式输入 |
| candidate | 已按授权运行生成，待独立审核 | 不可作为正式结论依据 |
| validated | 已通过预设产物与结论审核 | 可用于限定范围的后续验证 |
| frozen | 已锁定版本、用途和依赖 | 可作为下游唯一正式输入 |
| released | 已完成发布审核 | 可对外或用于最终报告 |

不得通过改名或补写文档让产物跨级。

## 3. 正式产物的最小组成

每个 `candidate` 及以上等级的产物必须具备：

```text
artifact_id
artifact_type
evidence_status
stage / step
data_version
state_definition_version
code_commit
config_hash
environment_lock_hash
run_id
input_hashes
output_hashes
schema_version
created_at
owner
review_record
allowed_downstream_use
```

产物包括数据表、因子、状态日、确认区间、事件、风险集、标签、图表、统计摘要、零模型结果、回测结果、报告和结论记录。

## 4. Manifest

每个正式数据集或结果目录必须有 manifest，并能回答：由什么输入生成、输入哈希、代码/配置/环境/种子、何时运行、退出码和质量检查、输出文件集合/schema/行数/哈希、允许哪些下游任务使用、证据等级及失效条件。

没有 manifest 的文件不得进入 `validated` 或更高等级。

## 5. 独立产物审核

G6 不得只阅读程序打印文本。至少独立检查：文件集合、schema/dtype/列顺序、主键、行数、日期股票范围、排序、NaN/无穷/异常值、输入输出哈希、与上游或替代口径差异、核心会计恒等式、结论是否被产物直接支持。

复杂产物应使用独立脚本或独立实现复核关键统计。

## 6. 结论分类

| 类型 | 定义 |
|---|---|
| 直接事实 | 可由正式产物直接读取的统计结果 |
| 推断 | 基于事实的有限解释 |
| 机制假设 | 尚未被直接验证的解释 |
| 预测/交易结论 | 涉及未来表现或可执行价值 |
| 限制与不适用 | 结论适用边界 |

未经 R5 验证的结果不得作为交易建议。机制假设、探索性发现或统计关联不得表述为确定因果或稳定交易优势。

## 7. 冻结与版本管理

`frozen` 产物须有唯一版本、完整输入输出哈希、不可修改 manifest、上游依赖、下游用途、审核记录和冻结理由。发现错误时创建替代版本并记录旧版本失效范围；不得覆盖历史 manifest。

冻结的是“数据 + 定义 + 代码 + 配置 + 产物 + 结论边界”的组合，而非单个文件名。

## 8. 图表、报告与发布

图表或报告至少显示：数据版本、研究宇宙、时间范围、状态/模型版本、指标/事件定义、证据等级、生成时间与运行标识，必要时附数据许可和非投资建议。不得只展示最优配置；参数搜索、替代定义或未通过稳健性检查须说明。

## 9. 失效、撤回与纠正

出现输入错误、前视、时间错位、公司行为处理错误、代码设计不一致、运行不可复现、产物审计错误、结论超证据边界或许可不符时，相关产物应标记 `superseded`、`invalidated` 或 `withdrawn`。

纠正记录必须说明问题、影响范围、修复、重跑、替代版本和结论变化。

## 10. 结论登记册

项目维护结论登记册，每一条至少包括：

```text
claim_id
claim_text
claim_type
evidence_status
supporting_artifacts
data_version
state_version
scope
limitations
owner
review_date
supersedes / superseded_by
```

结论登记册是研究输出索引，不替代原始产物、manifest 或实验记录。
