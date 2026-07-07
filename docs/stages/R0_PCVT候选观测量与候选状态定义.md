# R0：PCVT 候选观测量与候选状态定义

> 文档类别：Candidate State Design Specification  
> 所属阶段：R0  
> 状态：草案（v0.4，待 R0-T03 设计审核与 R1 结构验证）
> 版本：0.4
> 前置依赖：D2 时点一致连续价格体系；D3 标准化市场观测面板  
> 后续阶段：R1 结构验证 → R2 状态冻结  
> 生效边界：本文件只定义候选观测量、候选参数配置与候选状态日表；不定义未来标签，不使用未来波动扩张、未来收益、未来突破方向或回测结果选择指标及参数。

> v0.4 变更摘要：补充 `S_PCT` 与 `S_PCVT` 双主线定位；将 `weak` 维度规则确定为 R0 baseline，`strict` 不进入 baseline 或 sidecar；明确 `score_P / score_C / score_T / score_V` 的连续分计算方式；补充 `AdjVWAPSpread_5_60`、`TurnoverShrink20_60` 与 `AmountLevel20Pct` 的 R0 readiness gate；将 V1 baseline 从原始成交量收缩切换为 D3-T11 `turnover_float` 口径；明确“突破后回踩均线再突破”属于 R3/R4 的 Post-Up-Release Short-PCT 路径研究，不改写 R0 状态本体；新增 R0 task 级路线图和 R0-T03 V 层 turnover contract。

---

## 1. 研究目标与边界

本研究拟识别由四类当期可观察特征共同构成的候选收敛状态：价格波动收缩（P）、多周期参考价格趋同（C）、趋势方向消失（T）以及交易参与度下降（V）。v0.3 将 `S_PCT = P ∧ C ∧ T` 与 `S_PCVT = P ∧ C ∧ T ∧ V` 明确为两条核心候选状态线：`S_PCT` 表示不要求参与度枯竭的结构收敛，`S_PCVT` 表示叠加参与度收缩的枯竭型收敛。候选状态的经济解释是：价格在不同时间尺度和不同参考中心上趋于聚合，趋势方向减弱；若 V 同时成立，则进一步表示交易参与相对自身历史收缩。

R0 的目标不是预测涨跌方向，也不是建立买卖信号。R0 只回答：在严格时点一致性条件下，如何将 PCVT 四维状态实现为可复现、可审计、可比较的候选状态日表。状态是否稳定、是否超过随机同步、是否提供超越低波动的增量信息，以及是否对应未来波动扩张，分别由 R1、R2 之后的阶段回答。

R0 的正式最低输出包括：

1. 八项候选指标的公式、字段、窗口、缺失规则与单位约束；
2. 候选参数配置集与统一评分规则；
3. 单指标、单维度、PCT 与 PCVT 的候选状态日表；
4. `score_P / score_C / score_T / score_V` 及 `score_*_min` 等连续维度分诊断字段；
5. weak baseline 规则下的状态频率、覆盖率和 `score_*_min` 边界诊断摘要；
6. 每日 `valid / invalid / unknown` 状态及可追溯计算元数据；
7. 供 R1 使用的覆盖率、层内相关性和候选状态频率基础统计；
8. R0 task 级路线图和 R1 交接清单。

R0 不得使用以下任何信息来筛选指标、窗口、阈值、权重或确认规则：未来收益、未来最大涨跌幅、未来实现波动率、未来突破方向、未来路径类别、回测收益、交易成本后收益或样本外表现。

---

## 2. 阶段定位与关键依赖

研究主线如下：

```text
D0 → D1 → D2 → D3
               ↓
              R0 → R1 → R2 → R3 → R4 → R5 → R6
```

R0 依赖 D2 提供的时点一致连续研究价格，以及 D1/D3 提供的交易状态、停复牌、公司行为、成交量、成交额、股本、换手率和基础质量标记。P、C、T 默认使用连续研究价格；V 使用 D3-T11 标准化的 `turnover_float` 与 `amount_yuan`，并以交易状态、股本可比性和异常标记约束其可用性。

R1 只能读取冻结数据版本下由 R0 授权运行生成的候选产物。R2 只能在 R1 的结构验证完成后冻结一个或多个状态定义版本。R3 才能定义“释放”、风险集、未来波动扩张标签和对照组；R0 不得反向读取这些结果。

---

## 3. 构念设计原则

PCVT 四维不是同义重复，而是分别回答四个不同问题。

| 维度 | 构念 | R0 中需要排除的混淆 |
|---|---|---|
| P | 当前及近期价格活动是否压缩 | 仅凭低日波动误判为平台收敛 |
| C | 不同时间窗口或成交权重下的参考价格是否聚合 | 将“价格靠近某一均线”误作参考价格趋同 |
| T | 价格路径是否缺乏持续方向 | 将低波动但缓慢单边漂移误作中性 |
| V | 市场交易参与是否相对既往收缩 | 将稳定成交或停牌/零成交误作低参与 |

每一维保留两个候选指标。两个指标不是为了堆叠信号，而是要求“核心水平”与“动态或跨尺度特征”同时可观测。该设计在 R0 中控制复杂度，在 R1 中再检验层内冗余和增量信息；若两项高度重复或一项没有结构贡献，R2 应删除、替代或降权，而不是机械保留八项。

### 3.1 v0.3 状态族定位

v0.3 将 `S_PCT` 从单纯的嵌套中间层提升为重点研究辅线。`S_PCT` 不要求 V 成立，适合描述价格结构收敛、参考价格粘合与趋势方向消失，但尚未出现或不要求交易参与枯竭的状态。`S_PCVT` 则是在 `S_PCT` 基础上叠加 V，表示枯竭型收敛。

因此，R0/R1 至少应并列报告以下两条核心状态线：

```text
S_PCT  = P ∧ C ∧ T
S_PCVT = P ∧ C ∧ T ∧ V
```

`S_PCT` 可作为 `S_PCVT` 的上层风险集，也可作为独立的结构收敛候选状态。R1 对 V 的增量检验必须在 `P=C=T=1` 条件风险集内比较 `V=1` 与 `V=0`，而不是只比较无条件 `S_PCVT` 与非 `S_PCVT`。

### 3.2 突破后回踩均线再突破的边界

交易中常见的“5–60 日均线粘合后向上突破，随后回踩或盘整，并在 5/10/20 或 5/10/20/30 均线附近重新粘合后再次突破”，在本研究中暂不改写 R0 的 `S_PCT` 本体。该现象涉及已经发生的向上释放、释放后路径和再次释放，属于 R3/R4 的事件与路径研究。

R0 只定义一般化的 `S_PCT`。R3 可在冻结状态后定义 `upward_release`，R4 再定义和研究 `Post-Up-Release Short-PCT` 或 `Continuation PCT` 路径子类型，例如使用 `MA5/10/20` 或 `MA5/10/20/30` 的短周期参考价格趋同规则。这样可以保留该交易场景，同时避免在 R0 使用未来突破方向或未来路径定义状态。

---

## 4. R0 候选八项指标总表

所有指标均设计为“原始数值越低，越符合收敛构念”。除 `AmountLevel20Pct` 本身为过去历史百分位外，其余指标先计算原始值，再计算严格过去历史百分位，并转换为统一收敛分数。

| 层 | 指标代码 | 原始含义 | 收敛方向 | 选用理由 |
|---|---|---|---|---|
| P | `NATR14` | 短期真实价格活动 | 越低越收敛 | 同时覆盖日内振幅与相对前收盘跳空，描述日常真实波幅。 |
| P | `LogRange20` | 二十日价格平台宽度 | 越低越收敛 | 描述中期高低区间，补足单日波动不能反映的平台结构。 |
| C | `LogMASpread_5_60` | MA5/10/20/30/60 的离散度 | 越低越收敛 | 直接刻画多周期时间加权参考价格是否粘合。 |
| C | `AdjVWAPSpread_5_60` | 多周期 VWAP 的离散度 | 越低越收敛 | 刻画成交权重下的价格中心是否聚合，补充均线的时间权重视角。 |
| T | `ER20` | 二十日净位移/总路径 | 越低越中性 | 识别折返、路径低效率和缺乏净方向的价格路径。 |
| T | `AbsTrendT20` | 二十日对数价格趋势显著性 | 越低越中性 | 排除低波动但具有稳定单边漂移的情形。 |
| V | `TurnoverShrink20_60` | 近期流通股本换手率相对既往换手率 | 越低越收缩 | 衡量最近交易参与相对既往基准是否缩减，并用 D3-T11 标准股本口径降低股本变动造成的机械偏差。 |
| V | `AmountLevel20Pct` | 近期平均成交额的过去历史位置 | 越低越收缩 | 衡量资金参与规模是否处于该股票自身历史低位，补足换手率口径。 |

R0-T04 只实现这些指标的 raw/base metric engine。`AmountLevel20Pct` 的 raw base object 是 `LogAmount20`，其严格过去历史百分位和最终 `AmountLevel20Pct` 字段由 R0-T05 生成；R0-T04 不生成 percentile、score、state 或 interval。R0-T05 只生成 strict-past percentile、eligible flag、indicator score、dimension score、`score_*_min` 和 common eligible sample 语义，不应用 q 阈值、不生成 weak rule 状态、不生成 `S_PCT` / `S_PCVT` 或区间。R0-T06 消费 R0-T05 score layer，基于 `q=0.10/0.20/0.30` 与 `weak_delta=0.10` 生成 raw daily weak dimension states、nested raw states 和互斥层；不生成 confirmation、streak、confirmed state 或 interval。

---

## 5. 数据使用约定

### 5.1 字段分层

P、C、T 使用时点一致的连续研究价格：

```text
adj_open, adj_high, adj_low, adj_close,
adjustment_factor, factor_as_of_time,
corporate_action_flag, trading_status, price_limit_status
```

V 使用 D3-T11 标准化交易事实与股本派生层：

```text
volume_shares, amount_yuan,
float_share_shares, free_share_shares,
turnover_float, turnover_free,
turnover_field_status, share_field_status,
provider_turnover_crosscheck_status,
trading_status, suspension_flag,
price_limit_status, corporate_action_flag,
corporate_action_types_in_window,
share_comparability_corporate_action_in_window,
common_share_basis_policy,
volume_comparability_policy,
security_id, trading_date
```

原始交易价格、公司行为事实、连续研究价格与交易约束必须分层保存，禁止相互覆盖。公司行为产生的机械价格断层不得被解释为普通跳空、波动扩张或趋势变化。

### 5.2 时间语义

对任一交易日 \(t\)，R0 的所有输入都必须满足：

\[
observed\_at \le as\_of\_time(t)
\]

若供应商存在历史修订，必须在数据版本中说明采用“最终修订历史”还是“当时可得历史”。本 R0 版本只允许使用已经冻结的数据版本；每次输出都必须写入 `data_version`、`source_snapshot_id`、输入哈希、代码提交、配置哈希和运行标识。

### 5.3 无效与未知状态

每一个指标日都必须输出：

```text
valid / invalid / unknown
```

`unknown` 包括但不限于：窗口不足、停牌、缺失、复权异常、代码映射不完整、公司行为调整失败、单位校验失败、异常零值、不可解释跳空或不适用。`unknown` 不能静默转换为 `False`、零值、前值或均值。

---

## 6. P：价格压缩

### 6.1 P1：NATR14

#### 定义

先在连续研究价格上定义真实波幅：

\[
TR_t=\max\left(
H_t-L_t,
|H_t-C_{t-1}|,
|L_t-C_{t-1}|
\right)
\]

用 Wilder 平滑计算 14 日平均真实波幅：

\[
ATR14_t=WilderMean(TR_t,14)
\]

再按当日连续收盘价归一化：

\[
NATR14_t=\frac{ATR14_t}{C_t}
\]

必要时可以乘以 \(100\) 表示百分比，但单位必须在配置中固定。此处 `NATR14` 采用标准“ATR 除以价格”的项目定义，不使用未明确命名的逐日 \(TR/C_{t-1}\) 平滑替代写法。

#### 选择理由

`NATR14` 描述短期真实价格活动，既覆盖日内高低振幅，也覆盖相对前收盘的跳空。它与 `LogRange20` 的中期价格平台宽度具有不同时间含义：前者观察近期日常活动，后者观察较长窗口内的总体约束。

#### 数据与计算注意事项

- 使用同一复权基准下的连续 \(H,L,C\)。
- 前收盘缺失时，当日 `unknown`；不得以同日开盘、前值填补或零跳空替代。
- 至少需要 15 个有效交易日才能计算 Wilder 平滑结果。
- 停牌日不得以重复收盘价写入窗口。
- 因分红、送转、配股、拆并股引起的机械缺口必须由公司行为体系归因；调整失败时指标应为 `unknown`。
- 涨跌停和一字板可能产生表观低波动，必须保留 `price_limit_status`，供 R1 分层诊断。

### 6.2 P2：LogRange20

#### 定义

\[
LogRange20_t=
\log\left(
\frac{\max(H_{t-19:t})}
{\min(L_{t-19:t})}
\right)
\]

数值越低，代表最近二十个有效交易日的价格平台越窄。

#### 选择理由

它直接描述中期横向价格区间，与短期真实波幅互补。采用对数高低价比而不是以当日收盘价归一化，是为了减少窗口终点价格水平和方向对区间指标的机械影响。

#### 数据与计算注意事项

- 使用连续研究高低价。
- 窗口必须含 20 个有效交易日；停牌、缺失、异常复权或未完成代码映射均使当日 `unknown`。
- 不得以最近有效价格向前填充停牌日来凑满窗口。
- 对涨跌停、一字板和复牌跳空保留独立标记；R0 不直接将其剔除，但 R1 必须检验候选状态是否被此类交易约束主导。

---

## 7. C：参考价格趋同

### 7.1 C1：LogMASpread_5_60

#### 定义

设多周期移动平均线集合为：

\[
\mathcal{M}_t=
\{MA5_t,MA10_t,MA20_t,MA30_t,MA60_t\}
\]

其中每条均线均以连续研究收盘价计算。定义：

\[
LogMASpread_{5\_60,t}
=Std\left(
\log MA5_t,
\log MA10_t,
\log MA20_t,
\log MA30_t,
\log MA60_t
\right)
\]

#### 选择理由

该指标直接衡量不同时间跨度形成的参考价格是否聚合，即技术分析语境中的“多均线粘合”。它测量的是参考价格彼此之间的离散程度，而不是现价距某条均线有多远，因此与 C 的构念保持一致。

#### 数据与计算注意事项

- 所有 MA 必须由连续研究收盘价计算；不得在原始价与复权价之间混用。
- MA60 未满足最小有效样本时，当日 `unknown`。
- 停牌日不得作为重复价格进入均线窗口。
- 复权因子、公司行为生效日、证券代码变化必须可追溯；任一环节不能确认时，应中断指标可用性。

### 7.2 C2：AdjVWAPSpread_5_60

#### 定义

先计算每日成交量加权均价：

\[
DailyVWAP_t=\frac{Amount_t}{Volume_t}
\]

将每日成交价格与成交量转换至与连续研究价格一致的共同公司行为基准后，定义窗口 VWAP：

\[
VWAP_{h,t}=
\frac{
\sum_{j=0}^{h-1}DailyVWAP^*_{t-j}\times Volume^*_{t-j}
}{
\sum_{j=0}^{h-1}Volume^*_{t-j}
},
\quad h\in\{5,10,20,30,60\}
\]

最终定义：

\[
AdjVWAPSpread_{5\_60,t}
=Std\left(
\log VWAP_{5,t},
\log VWAP_{10,t},
\log VWAP_{20,t},
\log VWAP_{30,t},
\log VWAP_{60,t}
\right)
\]

#### 选择理由

均线提供时间加权的历史价格中心，VWAP 提供成交权重下的成交价格中心。两者同时趋同时，候选状态不仅表现为“不同时间窗口的价格重合”，也表现为“不同成交持有期的交易中心重合”。这使 C 层不依赖单一价格参考体系。

#### 数据与计算注意事项

- 必须明确 `Amount` 的单位（元、千元、万元等）和 `Volume` 的单位（股、手等）。
- 单位统一后，`DailyVWAP` 应在合理误差内落于当日原始价格 \([Low,High]\) 区间；不通过则暂停该指标并排查数据契约。
- 跨分红、送转、配股、拆并股窗口时，不得直接将原始日成交额和原始日成交量跨日累计后得到“复权 VWAP”。必须先将每日价格与成交量转换到共同基准，或在该窗口标记为 `unknown`。
- `DailyVWAP` 是成交价格中心，不等同于当前持仓者成本，报告中不得做超出该定义的解释。
- 出现停牌、零成交、异常金额或极端单位错误时，应根据数据契约标记为 `unknown`，不得作为低参与的普通观察值。
- R0-T02 必须先执行 C2 readiness gate：若 D3 仅声明 amount/volume 单位规则，但未提供可审计的 `adjusted_vwap_policy` 或等价共同公司行为基准，则 `AdjVWAPSpread_5_60` 不得被硬算为正式 C2 值。可执行策略为：无跨公司行为窗口且单位与 DailyVWAP 区间校验通过时可计算；跨分红、送转、配股、拆并股等窗口时，必须有共同基准转换，否则标记 `unknown` 或阻塞本配置。
- R0-T02 将以独立 contract / schema / tests 固化 C2 与旧 V1 输入 readiness gate；R0-T03 进一步固化 V 层 turnover baseline readiness gate。后续 raw metric engine 只能读取允许为 `ready` 的输入条件，或按固定 reason 传播 `unknown / diagnostic_required / blocked`。

---

## 8. T：趋势中性

### 8.1 T1：ER20

#### 定义

\[
ER20_t=
\frac{
|\log C_t-\log C_{t-20}|
}{
\sum_{j=1}^{20}
|\log C_{t-j+1}-\log C_{t-j}|
}
\]

数值通常位于 \([0,1]\) 区间。数值越低，表示总价格路径较长但最终净位移较小，价格折返较多、方向效率较弱。

#### 选择理由

`ER20` 不是简单的上涨或下跌指标，而是衡量路径是否有效地朝一个方向累积。低 ER 可以识别来回震荡和缺乏净方向的价格路径；与 P、C 同时成立时，才能构成“收敛且中性”的候选状态。

#### 数据与计算注意事项

- 使用连续研究收盘价的对数收益。
- 分母为零且窗口内价格完全不变时，定义 `ER20=0`。
- 分母缺失、窗口不足、价格非正、复权异常或停牌破坏窗口时，当日 `unknown`。
- 不得以收益率零填补停牌日或缺失日。

### 8.2 T2：AbsTrendT20

#### 定义

对最近二十个有效交易日的对数价格做 OLS 回归：

\[
\log C_{t-19+j}=\alpha+\beta j+\epsilon_j,
\quad j=0,\ldots,19
\]

定义趋势显著性为：

\[
AbsTrendT20_t=
\left|
\frac{\hat{\beta}}
{SE(\hat{\beta})}
\right|
\]

数值越低，表示在窗口内相对于噪声并不存在显著的持续线性漂移。

#### 选择理由

`ER20` 可能在某些低波动、缓慢单边行情中仍然无法完整排除趋势性；`AbsTrendT20` 则衡量趋势斜率相对残差噪声是否显著。两者结合能够区分“路径反复且无方向”与“低波动但稳定单边”的情形。

#### 数据与计算注意事项

- 使用连续研究收盘价的对数值。
- 至少需要二十个有效观测。
- 若价格完全不变，定义趋势统计量为 0。
- 若残差标准误为 0 且斜率不为 0，说明存在机械单边路径，指标不得错误设为 0；应标记为高趋势强度或 `unknown`，具体实现规则须在配置中固定。
- 指标用于描述性趋势强度，不在 R0 中解释为正式计量显著性结论。
- 若残差标准误为 0 且斜率为 0，可定义为 `AbsTrendT20=0`，但仍须检查是否由停牌、重复补值或不可交易状态造成。若残差标准误为 0 且斜率不为 0，不得因除零问题将指标设为 0；应按预设规则标记为强趋势不满足 T，或在疑似机械路径、数据插值、复权异常、连续涨跌停约束主导时标记为 `unknown / diagnostic_required`。

---

## 9. V：参与度收缩

### 9.1 V1：TurnoverShrink20_60

#### 定义

定义最近二十个有效交易日平均流通股本换手率：

\[
\overline{TurnoverFloat}_{20,t}=
\frac{1}{20}\sum_{j=0}^{19}TurnoverFloat_{t-j}
\]

定义其此前六十个有效交易日的非重叠基准：

\[
\overline{TurnoverFloat}_{60,prior,t}=
\frac{1}{60}\sum_{j=20}^{79}TurnoverFloat_{t-j}
\]

定义：

\[
TurnoverShrink20\_60_t=
\frac{\overline{TurnoverFloat}_{20,t}}
{\overline{TurnoverFloat}_{60,prior,t}}
\]

数值越低，表示近期换手率相对既往换手率越明显收缩。

#### 选择理由

该指标直接回答“最近的交易参与是否比此前一段时期更低”。采用“最近 20 日 / 此前 60 日”的非重叠设计，而不是“20 日 / 包含最近 20 日的 60 日均值”，是为了避免分子被包含在分母中而形成机械重叠，增强动态收缩的识别力。使用 `turnover_float` 可以把成交量除以流通股本，降低送转、拆并股、配股等股本变化造成的机械偏差。

#### 数据与计算注意事项

- `turnover_float` 必须来自 D3-T11 标准字段，并与 `volume_shares`、`float_share_shares` 和 provider turnover crosscheck 保持一致。
- 窗口内停牌与零成交不能被当作普通低参与日；窗口应无效或根据预设规则中断候选状态区间。
- 上市初期、重大解禁、复牌、代码变更、市场制度变化及数据字段变更应有独立标记。
- 若 80 日窗口内发生送转、拆并股、配股或其他改变股份数量可比性的公司行为，必须存在 `common_share_basis_policy` 或 `volume_comparability_policy`，或将 `TurnoverShrink20_60` 标记为 `unknown`；不得将股本机械变化解释为参与度收缩。
- R0-T03 必须先执行 V 层 readiness gate：若 `turnover_float` 缺失、`float_share_shares` 非正、股本字段状态无效、turnover 字段状态无效、provider crosscheck fail、停牌/零量或公司行为可比性策略缺失，必须输出固定 reason，不得硬算。
- R0-T03 将以独立 contract / schema / tests 固化 `TurnoverShrink20_60` 输入 readiness gate；R0-T04 只能读取 R0-T03 允许为 `ready` 的输入条件，或按固定 reason 传播 `unknown / diagnostic_required / blocked`。
- 极端成交量不应静默截尾；若使用 winsorize 或对数化版本，只能作为 R1 替代口径并完整记录。

### 9.2 V2：AmountLevel20Pct

#### 定义

先计算最近二十个有效交易日的平均成交额：

\[
\overline{Amount}_{20,t}=
\frac{1}{20}\sum_{j=0}^{19}Amount_{t-j}
\]

为处理成交额的右偏分布，先取对数：

\[
LogAmount20_t=\log(\overline{Amount}_{20,t})
\]

再计算其严格过去历史百分位：

\[
AmountLevel20Pct_t=
Percentile_{W,t}(LogAmount20_t)
\]

`AmountLevel20Pct` 越低，表示近期资金参与规模越处于该股票自身历史低位。该指标本身就是历史位置，不再重复计算一层相同的百分位。

R0-T04 只计算 `LogAmount20_t` base object，并以 `V2_LogAmount20_base` 标识输出。`AmountLevel20Pct_t` 的严格过去历史百分位、eligible 样本和 score 体系属于 R0-T05；任何 R0-T04 输出中出现 `AmountLevel20Pct`、strict-past percentile、score 或 state 都应视为越界。

#### 选择理由

成交量体现交易份额，成交额体现资金规模。只使用成交量容易受股本变化、拆并股和交易单位影响；使用相对历史成交额位置可补充“资金参与是否处于该证券自身低位”的信息，同时避免将不同市值股票的绝对成交额直接横向比较。

#### 数据与计算注意事项

- 成交额使用 D3-T11 标准字段 `amount_yuan`；成交额单位必须固定，并在数据契约中明示。
- 金额为零、缺失、停牌或异常成交不得被解释为普通低成交额。
- 供应商成交额是否包含集合竞价、盘后大宗或其他特殊成交必须说明；R0 版本中必须固定口径。
- 本指标衡量的是“相对自身历史的低参与”，不是跨股票绝对流动性。R1 与后续阶段仍需按市值、流动性或可交易性分层分析。

### 9.3 Turnover 替代口径的后续边界

D3-T11 已提供 `float_share_shares`、`free_share_shares`、`turnover_float` 与 `turnover_free`。R0-T03 将 `TurnoverShrink20_60` 确认为 V1 baseline，`AmountLevel20Pct` 继续作为 V2 baseline；`FreeTurnoverShrink20_60`、`TurnoverLevel20Pct` 与 `FreeTurnoverLevel20Pct` 仅作为 R1 sensitivity 或 optional alternative，不进入 R0 baseline。

---

## 10. 历史分位体系、资格判定与统一评分

### 10.1 三类窗口必须严格区分

R0 至少存在三类时间窗口，配置和实现中必须使用不同字段名，禁止混淆：

| 窗口类别 | 示例 | 含义 | 是否用于相对历史比较 |
|---|---|---|---|
| 原始指标观测窗口 | `NATR14` 的 14 日、`LogRange20` 的 20 日、`TurnoverShrink20_60` 的 20/60 日 | 生成某一个原始指标值所需的历史交易日 | 否 |
| 参考价格窗口 | MA/VWAP 的 5、10、20、30、60 日 | 构造 C 层不同持有期或不同时间权重的参考价格 | 否 |
| 历史分位窗口 \(W\) | 120、250、500 个有效指标值 | 判断当日原始指标在该股票自身过去历史中的位置 | 是 |

例如，`TurnoverShrink20_60` 中的 20/60 日只定义“近期相对既往换手率是否下降”；其结果仍须用另一个严格过去分位窗口 \(W\) 判断是否异常低。不得把 `60` 日基准误认为历史分位窗口，也不得以 \(W\) 替代原始指标的经济窗口。

### 10.2 指标资格与历史样本

对指标 \(i\) 和历史分位窗口 \(W\)，当日只有同时满足下列条件时，才具备可计算资格：

\[
Eligible_{i,W,t}=1
\]

其条件为：当日原始指标 \(x_{i,t}\) 有效；该指标此前存在至少 \(W\) 个有效历史值；本指标所需的价格、成交、公司行为、交易状态与单位校验均通过。这里的 \(W\) 指此前 **有效指标观测数**，而非自然日、日历日或简单向前数 \(W\) 个交易日期。

联合状态的资格必须更严格：

\[
Eligible_{PCVT,W,t}=
\bigwedge_{i\in\{P1,P2,C1,C2,T1,T2,V1,V2\}}
Eligible_{i,W,t}
\]

任何一项不具资格时，不得把 PCVT 记为“未触发”；应标记为 `unknown`，并写明具体原因。对 `AmountLevel20Pct`，原始对象为 \(LogAmount20\)，其百分位输出就是该指标的最终历史位置；不得对其再嵌套计算同一层百分位。

当比较 \(W=120,250,500\) 的结构差异时，必须另建 `common_eligible_sample`：仅保留三个 \(W\) 下八项指标均有资格的股票—交易日。否则，500 日配置因更长预热期而自然偏向成熟股票和较晚样本，比较结果会混入样本构成差异。

### 10.3 严格过去历史百分位

对普通原始指标 \(x_i\)，用此前 \(W\) 个有效历史值构造中位秩百分位：

\[
Percentile_{i,W,t}=
\frac{
\#(x_{i,\tau}<x_{i,t})+
0.5\#(x_{i,\tau}=x_{i,t})
}{W},
\quad \tau<t
\]

参考集合仅包含此前有效观测，当前值不得进入参考分布。中位秩处理使大量相同取值（例如涨跌停、量额取整或长期不变价格）不会因任意排序而被拆分到阈值两侧。

对 V2：

\[
AmountLevel20Pct_t=
Percentile_{LogAmount20,W,t}
\]

阈值比较采用固定的闭区间规则：

\[
Percentile_{i,W,t}\le q
\quad\Leftrightarrow\quad
Score_i(t)\ge 1-q
\]

若由于并列值使实际入选比例偏离 \(q\)，保留该偏离并报告；不得为了凑足精确的 10%、20% 或 30% 而随机打散并列值。

### 10.4 分数的含义与限制

统一收敛分数定义为：

\[
Score_i(t)=1-Percentile_{i,W,t}
\]

对 V2：

\[
Score_{V2}(t)=1-AmountLevel20Pct_t
\]

高分仅表示“该指标在该股票自身、严格过去历史中处于低位”；它不是概率、也不是跨指标的经济量纲。因而维度均值可用于图形、平滑性和敏感性诊断，但不能被解释为某种可加总的经济强度，更不能以未来结果反向学习指标权重。

### 10.5 维度连续分与最低单项分

R0 必须在二值状态之外输出连续维度分。对每个维度 \(D\in\{P,C,T,V\}\)，设两个指标分数为 \(Score_{D1,t}\)、\(Score_{D2,t}\)。定义：

\[
score_D(t)=\frac{Score_{D1,t}+Score_{D2,t}}{2}
\]

\[
score_{D,min}(t)=\min(Score_{D1,t},Score_{D2,t})
\]

`score_P / score_C / score_T / score_V` 是维度连续强度诊断字段；`score_P_min / score_C_min / score_T_min / score_V_min` 用于识别单项短板和 weak 规则的非补偿约束。若任一指标为 `unknown`，对应维度连续分也应为 `unknown`，不得用另一项分数补齐。

维度连续分不得被解释为概率、收益预期或跨维度可加总经济强度。其用途限于 R0/R1 的覆盖率、平滑性、层内相关性、状态边界和敏感性诊断。

### 10.6 基线与敏感性窗口

\[
W\in\{120,250,500\},\qquad q\in\{10\%,20\%,30\%\}
\]

其中，\(W=120\) 更灵敏但更容易随近期制度和成交状态变化而漂移；\(W=250\) 对应约一个交易年，是首选基线；\(W=500\) 更稳定但对结构变化反应更慢，并提高预热要求。\(q=10\%\) 提供更严格、更稀少的低尾部状态；\(q=30\%\) 提供更宽松的状态；\(q=20\%\) 为基线。

这些配置的作用是验证“状态结构是否对合理历史标尺稳健”，不是寻找未来波动扩张最强的窗口或阈值。R2 的选择规则必须由 R1 的结构门槛决定，不能通过 R3/R4 的未来标签、收益或回测表现选择。

---

## 11. 日度状态、嵌套状态与确认层

### 11.1 为什么需要确认层

需要确认层，但确认层只应建立在 **联合日度状态** 之上，而不应为八个单项指标分别设置确认。原因是：单项确认会增加不同维度的异步滞后，破坏 PCVT 在同一可观察时点的联合语义；联合确认则只处理状态的短暂闪现、碎片化和重复触发。

R0 必须同时输出三种对象：

1. **日度原始状态**：回答“今天是否满足定义”；
2. **实时确认状态**：回答“截至今天，是否已经有足够过去证据确认状态”；
3. **描述性区间信息**：回答“这段连续条件最早何时开始、何时被确认、因何终止”。

三者不可互相替代。尤其不得把在第 \(t\) 日才确认的状态回填为第 \(t-K+1\) 日的可交易或可实时观察状态。

### 11.2 指标、维度与联合日度状态

对维度 \(D\in\{P,C,T,V\}\) 的两个指标，设：

\[
I_{D1,t}=\mathbb{1}(Score_{D1,t}\ge 1-q),\qquad
I_{D2,t}=\mathbb{1}(Score_{D2,t}\ge 1-q)
\]

R0 必须同时输出连续维度分与候选维度状态：

\[
score_D(t)=\frac{Score_{D1,t}+Score_{D2,t}}{2},\qquad
score_{D,min}(t)=\min(Score_{D1,t},Score_{D2,t})
\]

在两项均具资格时，R0 baseline 维度状态采用非补偿性的 weak 规则：

\[
D^{weak}_t=
\mathbb{1}
\left(
score_D(t)\ge 1-q
\land
score_{D,min}(t)\ge 1-q-\delta
\right)
\]

首版 weak 配置固定 \(\delta=0.10\)，不进入 \(W,q,K\) 的完全交叉主网格。以 \(q=20\%\) 为例，weak 要求维度均值分至少为 0.8，同时两个单项中较低者至少为 0.7。该规则允许轻微异步，但禁止一个指标极强、另一个指标明显不成立时被均值补偿通过。若任一指标为 `unknown`，则 \(D^{weak}_t=unknown\)，而不是 0。

strict 曾作为备选维度规则讨论，但 R0 v0.3 当前决定不进入 baseline 或 sensitivity sidecar，以避免规则族扩张，并贴合维度内两个指标可能轻微异步的业务事实。基础嵌套状态按 baseline `dimension_rule = weak` 生成：

\[
S^{raw}_{P,t}=P^{raw}_t
\]

\[
S^{raw}_{PC,t}=P^{raw}_t\land C^{raw}_t
\]

\[
S^{raw}_{PCT,t}=P^{raw}_t\land C^{raw}_t\land T^{raw}_t
\]

\[
S^{raw}_{PCVT,t}=P^{raw}_t\land C^{raw}_t\land T^{raw}_t\land V^{raw}_t
\]

因此：

\[
S^{raw}_{PCVT}\subseteq S^{raw}_{PCT}\subseteq
S^{raw}_{PC}\subseteq S^{raw}_{P}
\]

`S_PCT` 与 `S_PCVT` 均为 R0/R1 重点状态线。`S_PCT` 表示不要求参与度枯竭的结构收敛；`S_PCVT` 表示叠加参与度收缩的枯竭型收敛。该嵌套结构不是假定 C、T、V 只有在 P 存在时才有意义，而是将 P 设为研究中的基础风险集，用于回答“结构、趋势和参与度是否提供超越单纯低波动的增量信息”。

同时，R0 必须保存完整的四维向量 \((P,C,T,V)\) 及其 `unknown` 掩码，不得只输出嵌套状态。这样 R1 仍可检查所有可观察组合，而不会因预设层级丢失反例。

### 11.3 互斥分层与增量比较

用于报告和条件比较时，定义在 C、T、V 均可观察前提下的互斥分层：

\[
E_P=P\land \neg C
\]

\[
E_{PC}=P\land C\land\neg T
\]

\[
E_{PCT}=P\land C\land T\land\neg V
\]

\[
E_{PCVT}=P\land C\land T\land V
\]

`unknown` 不得被写入任何 \(\neg D\) 组。R1 对增量的主要比较应采用条件风险集，而不是仅比较无条件频率：

\[
P=1:\quad C=1\ \text{vs.}\ C=0
\]

\[
P=C=1:\quad T=1\ \text{vs.}\ T=0
\]

\[
P=C=T=1:\quad V=1\ \text{vs.}\ V=0
\]

这能将“V 是否给 PCT 增量”与“PCVT 本身更稀少”区分开来。

### 11.4 实时确认层

设 \(X\in\{P,PC,PCT,PCVT\}\)，\(K\) 为确认所需的连续日数。定义连续长度：

\[
L_{X,t}=
\begin{cases}
L_{X,t-1}+1,& S^{raw}_{X,t}=1\\
0,& S^{raw}_{X,t}=0\\
NA,& S^{raw}_{X,t}=unknown
\end{cases}
\]

实时确认状态为：

\[
S^{conf}_{X,t}(K)=\mathbb{1}(L_{X,t}\ge K)
\]

基线候选取：

\[
K=3
\]

并在 R0/R1 中预先比较：

\[
K\in\{2,3,5\}
\]

R0 始终输出 \(K=1\) 的日度原始状态，但它不是“已确认状态”。\(K=2\) 反应更快、延迟为 1 个交易日；\(K=5\) 最稳定但延迟为 4 个交易日；\(K=3\) 是首轮结构研究中稳定性与时效性的平衡基线。

### 11.5 区间开始、确认和终止时间

对于任一连续原始区间：

- `raw_start_date`：连续 \(S^{raw}_{X}=1\) 的第一个交易日；
- `confirmation_time`：第 \(K\) 个连续有效日，即最早满足 \(S^{conf}_{X}=1\) 的交易日；
- `confirmed_start_date`：等于 `confirmation_time`，用于所有实时、交易或前瞻研究；
- `descriptive_start_date`：可等于 `raw_start_date`，仅用于事后描述；
- `last_raw_active_date`：连续原始状态最后一个为 1 的交易日；
- `termination_type`：`invalid_break`、`unknown_interrupt`、`suspension_interrupt`、`corporate_action_interrupt`、`sample_end_censored` 等。

确认不得跨越 `unknown`、停牌、未通过公司行为处理、交易状态异常或数据缺失。若原始条件在第 3 天确认后第 4 天失效，区间可被描述为“原始长度 3 天、确认后存续 1 天”，但绝不能将它包装为从第 1 天起已知的 3 天状态。

R0 的状态终止只描述候选状态不再成立或观察中断；它不是 R3 的“释放事件”。R3 之后才定义状态失效、波动释放、方向释放与交易释放之间的关系。

### 11.6 Post-Up-Release Short-PCT 的后续研究边界

“突破后回踩到 5/10/20 或 5/10/20/30 均线附近，短周期均线重新粘合后再次突破”的交易场景，不在 R0 中作为状态本体定义。该场景至少包含三个对象：已冻结状态后的向上释放、释放后短周期再收敛、再次向上释放。

R0 只需确保 `S_PCT` 能作为一般结构收敛状态被无前视生成。R3 可定义 `upward_release`，R4 可在释放后窗口内定义 `Post-Up-Release Short-PCT`，并采用短周期参考价格集合，例如 \(\{MA5,MA10,MA20\}\) 或 \(\{MA5,MA10,MA20,MA30\}\)。该路径子类型不得反向修改 R0 的 `S_PCT` 或 `S_PCVT` 定义。

---

## 12. R0 候选参数网格与防止组合爆炸

### 12.1 第一层：固定指标定义下的主网格

第一轮应固定本文件定义的八项原始指标窗口与公式，仅同时检验共同控制参数：

| 配置键 | 候选值 | 基线 | 用途 |
|---|---:|---:|---|
| `percentile_window_W` | 120, 250, 500 | 250 | 股票自身严格过去历史标尺 |
| `low_quantile_q` | 10%, 20%, 30% | 20% | 单指标进入历史低位的阈值 |
| `confirmation_days_K` | 2, 3, 5 | 3 | 联合状态的实时确认长度 |
| `dimension_rule` | weak | weak | 主网格基线，要求 `score_D >= 1-q` 且 `score_D_min >= 1-q-delta` |
| `weak_delta` | 0.10 | 0.10 | 固定维度内轻微异步容忍度，不进入参数网格 |

主网格规模为：

\[
3\times3\times3=27
\]

这 27 个配置均应从相同冻结数据版本、相同股票宇宙和相同代码版本生成，并以 weak 维度规则作为主产物。`weak_delta = 0.10` 固定，不扩大为新的完全交叉主网格；strict 不作为 R0 baseline 或 sidecar 输出。所有配置用于 R1 的结构稳健性比较，不是为了按未来标签挑选最优组合。

`cooldown_days` 不应进入 R0 的状态本体网格。冷却期是事件去重和后续风险集构造规则，原则上在 R2 的状态事件规范或 R3 的释放设计中单独冻结。R0 可报告重复确认和相邻区间间隔，但不以冷却期改写日度状态。

### 12.2 第二层：替代指标定义的受控敏感性

对原始指标窗口或计算口径的替代，只允许以预先声明、一次改变一个构件的方式进行，不得与全部 \(W,q,K\) 完全交叉。例如：

| 构件 | 基线 | 可选替代 | 使用目的 |
|---|---|---|---|
| P1 | `NATR14` | `NATR20` | 检查短期波动窗口敏感性 |
| P2 | `LogRange20` | `LogRange30` | 检查平台尺度敏感性 |
| T1 | `ER20` | `ER15`、`ER30` | 检查趋势路径窗口敏感性 |
| T2 | `AbsTrendT20` | `AbsTrendT30` | 检查趋势显著性窗口敏感性 |
| V1 | `TurnoverShrink20_60` | `TurnoverShrink15_45`、`TurnoverShrink30_90`、`FreeTurnoverShrink20_60` | 检查换手收缩时间尺度与股本口径敏感性 |

C 层的 MA/VWAP 期限集合在首轮固定为 \(\{5,10,20,30,60\}\)，避免同时改动参考价格族和历史分位体系。任何 C2 的复权口径变化属于数据与指标定义变更，应单独版本化，不得混入普通参数敏感性。

替代定义的目标是检验构念是否被单一任意窗口支配，而不是从多个组合中筛选未来表现最高者。R2 只可基于预先定义的结构判据选择基线或声明“多个版本并存”，不得用 R3/R4 标签破坏该边界。

### 12.3 R1 选择与淘汰判据

R1 对候选配置至少使用以下不含未来表现的判据：

1. **数据可用性。** 八项指标及 PCVT 联合状态的 `unknown` 比例、股票覆盖和年份覆盖不能由停牌、公司行为或字段缺陷主导。
2. **状态频率与样本容量。** 候选状态不能稀少到无法在年度、流动性层和市场状态下进行结构检验，也不能宽泛到仅等同于普通低波动日。具体最小样本量要求须在 R1 运行前写入配置。
3. **碎片率与确认增益。** 报告原始状态的一日区间占比、确认后区间长度、重复确认率和检测延迟；选择满足预先定义稳定性门槛的最小 \(K\)，而非选择未来结果最优的 \(K\)。
4. **层内冗余与层间边界。** 检查分数的秩相关、阈值共现率与条件保留率。高相关并非自动淘汰，但若某指标几乎不改变维度状态或与另一指标完全同义，R2 应简化定义。
5. **跨样本稳定性。** 在年份、市场状态、行业、流动性、股票年龄和交易约束状态下检验候选状态频率及状态组成是否稳定。
6. **零模型偏离。** 使用预先定义、保留边际频率与时间结构的零模型，检验 PCVT 共现是否只是滚动指标的自然同步。该检验只评价状态结构，不评价未来路径。
7. **低波动增量。** 以 \(P=1\) 为基础风险集，检验加入 C、T、V 后的状态结构、持续期、集中度和零模型偏离是否仍有可辨识变化；不使用任何未来波动标签。

R2 的默认规则应是：若基线 \((W=250,q=20\%,K=3)\) 通过所有预先声明的结构门槛，则优先冻结基线；仅在基线未通过特定门槛且某一替代配置按同一门槛通过时才替代。这样，参数网格是稳健性工具，不是事后优化器。

---

## 13. R0 状态日表、确认区间表与最小输出 Schema

### 13.1 日度状态表

主键为：

```text
security_id × trading_date × data_version × candidate_config_id
```

最小字段包括：

```text
security_id
trading_date
data_version
candidate_config_id
metric_variant_id
state_definition_draft_version

NATR14_raw
LogRange20_raw
LogMASpread_5_60_raw
AdjVWAPSpread_5_60_raw
ER20_raw
AbsTrendT20_raw
TurnoverShrink20_60_raw
LogAmount20_raw
AmountLevel20Pct

percentile_P1 ... percentile_V2
score_P1 ... score_V2
score_P
score_C
score_T
score_V
score_P_min
score_C_min
score_T_min
score_V_min
dimension_rule
weak_delta

validity_P1 ... validity_V2
unknown_reason_P1 ... unknown_reason_V2
eligible_P1 ... eligible_V2
eligible_PCT
eligible_PCVT

P_raw
C_raw
T_raw
V_raw
S_P_raw
S_PC_raw
S_PCT_raw
S_PCVT_raw

streak_P
streak_PC
streak_PCT
streak_PCVT
S_P_conf
S_PC_conf
S_PCT_conf
S_PCVT_conf

trading_status
suspension_flag
price_limit_status
corporate_action_flag
quality_flag
as_of_time
run_id
config_hash
code_commit
```

`AmountLevel20Pct` 为最终历史位置字段；为避免歧义，不应再命名为 `AmountLevel20Pct_raw`。若某一指标为 `unknown`，应同时写明具体代码，例如 `window_insufficient`、`suspension_in_window`、`corporate_action_share_change_in_window`、`adjustment_failure`、`amount_volume_unit_failure` 或 `missing_prior_close`。

### 13.2 确认区间表

确认区间表的主键为：

```text
security_id × state_level × candidate_config_id × confirmed_interval_id
```

最小字段包括：

```text
security_id
state_level                    # P / PC / PCT / PCVT
candidate_config_id
confirmed_interval_id
raw_start_date
confirmation_time
confirmed_start_date
last_raw_active_date
termination_time
termination_type
raw_length
confirmed_length
K
data_version
run_id
config_hash
```

对每个候选状态层级同时输出原始区间和确认区间。任何使用未来标签、风险集、交易时点或事件锚点的后续研究，只能读取 `confirmation_time` 及之后的可实时确认状态，不得使用 `raw_start_date` 作为可得信号时间。

---

## 14. R0 验收条件与 R1/R2 交接

R0 的验收不是“找到有效预测状态”，而是证明候选定义能被无前视地、稳定地、可审计地生成。除既有公式、数据契约和可复现性检查外，R0 进入 R1 前还必须完成：

1. **确认层审计。** 对 \(K=2,3,5\) 输出原始与确认状态的频率、原始区间长度、确认延迟、确认后存续长度和 `unknown` 中断比例。
2. **嵌套一致性审计。** 验证在每个观察日均满足 \(S_{PCVT}\subseteq S_{PCT}\subseteq S_{PC}\subseteq S_P\)，并检查所有互斥分层是否无重叠、无将 `unknown` 误当作否定状态的记录。
3. **历史分位审计。** 验证当前值未进入参考集；历史窗口为此前有效指标值；不同 \(W\) 的比较使用共同可用样本；并列值采用固定中位秩规则。
4. **公司行为与 V 层审计。** 对 `TurnoverShrink20_60` 的 80 日窗口，若存在改变股份数量或交易单位可比性的公司行为，必须存在共同股本基准或成交量可比性策略，或将该指标标记为 `unknown`；不得把送转、拆并股、配股等造成的股本机械变化误解为参与度收缩。
5. **候选网格审计。** 每一个 `candidate_config_id` 都能回溯指标版本、\(W,q,K\)、数据版本、代码提交、运行环境和状态日/区间输出哈希。

R1 使用这些已生成候选产物检验联合状态是否稳定、是否超过预设零模型，以及 C、T、V 是否具有超越 P 的结构增量。R2 才能冻结最终的 \(W,q,K\)、维度逻辑、确认规则、区间规则和状态版本。未来波动扩张、释放事件、风险集和对照组仍严格留在 R3 及之后阶段。

---

## 15. R0 task 级路线图

R0 的 task 拆分遵循“一个 PR 实现一个 task”的治理边界。task 标题使用中文，技术名词保留英文；分支名使用英文 slug。R0-T01 之前必须确认 D3-T09 的 R 阶段工程分层与 Task-as-Step 规范已被接受，且 R0 只能读取 D3 授权入口，不得直接绕过 D3 读取 D1/D2/raw/MarketDB。

| Task | PR 标题建议 | 分支名建议 | 类型 | 目标与理由 |
|---|---|---|---|---|
| R0-T01 | `[codex] R0-T01 PCVT 候选指标规格与状态族定义` | `codex/r0-t01-pcvt-candidate-indicator-spec-state-family` | 必须 | 将本文件 v0.3 固化为仓库内可审核规格，并落账为可机器校验的 R0-T01 candidate spec contract，明确八项指标、`S_PCT` / `S_PCVT` 双主线、禁止未来信息、weak baseline、strict inactive、Post-Up-Release Short-PCT 后续边界。 |
| R0-T02 | `[codex] R0-T02 输入 readiness gate 与 C2/V1 公司行为口径审计` | `codex/r0-t02-input-readiness-c2-v1-corporate-action-gate` | 必须 | 审计 R0 是否具备合法输入。重点检查 amount/volume 单位、DailyVWAP 区间、`adjusted_vwap_policy`、`volume_comparability_policy`、公司行为窗口、停牌/零成交和 D3-only 读取边界。若 C2/V1 条件不足，必须输出 `unknown` 或 blocked，不得硬算。 |
| R0-T03 | `[codex] R0-T03 V层 turnover 替代指标可行性、口径决策与输入门禁` | `codex/r0-t03-v-layer-turnover-baseline-readiness-gate` | 必须 | 将 V1 baseline 确认为 `TurnoverShrink20_60`，固化 D3-T11 `turnover_float` / `amount_yuan` 输入门禁、公司行为可比性和 forbidden outputs；不计算 raw metric。 |
| R0-T04 | `[codex] R0-T04 PCVT raw metric engine 与合成测试` | `codex/r0-t04-pcvt-raw-metric-engine` | 必须 | 实现八项 raw/base 指标计算，包括窗口、单位、停牌、缺失、公司行为、SE=0 规则和 unknown reason 传播；V2 只输出 `LogAmount20` base object，`AmountLevel20Pct` 留给 R0-T05；先不使用未来标签，不输出交易信号。 |
| R0-T05 | `[codex] R0-T05 严格过去分位、eligible 样本与 Score 体系` | `codex/r0-t05-strict-past-percentile-score-eligibility` | 必须 | 实现严格过去历史分位、中位秩并列处理、`W=120/250/500`、`common_eligible_sample`、指标 score、维度 score 和 `score_*_min`；生成 `V2_AmountLevel20Pct` 但不生成 state/q/K/interval。这是 R0 防前视与可比较性的核心。 |
| R0-T06 | `[codex] R0-T06 weak 维度规则、嵌套状态与互斥分层` | `codex/r0-t06-weak-dimension-nested-states` | 必须 | 生成 P/C/T/V raw weak states、`S_P`、`S_PC`、`S_PCT`、`S_PCVT` raw nested states、unknown propagation 和互斥分层。weak 为主网格 baseline，固定 `q=0.10/0.20/0.30` 与 `delta=0.10`；strict 不进入 baseline 或 sidecar，confirmation/streak/interval 留给 R0-T07。 |
| R0-T07 | `[codex] R0-T07 联合确认层、streak 与确认区间表` | `codex/r0-t07-confirmation-streak-intervals` | 必须 | 实现 `K=2/3/5` 的实时确认、streak、`raw_start_date`、`confirmation_time`、`confirmed_start_date`、终止类型和确认区间表。确认不得回填为早期可得信号。 |
| R0-T08 | `[codex] R0-T08 主网格 candidate 状态日表与 manifest` | `codex/r0-t08-main-grid-candidate-state-artifacts` | 必须 | 对 27 个 weak baseline 主网格配置生成 candidate 状态日表、区间表和 manifest；写入 `candidate_config_id`、`config_hash`、`run_id`、`code_commit`、输入输出哈希和数据版本。 |
| R0-T09 | `[codex] R0-T09 R0 审计报告与 R1 交接` | `codex/r0-t09-r0-acceptance-r1-handoff` | 必须 | 输出覆盖率、unknown 分布、C2/V readiness 影响、层内相关性、维度共现、`S_PCT`/`S_PCVT` 频率、weak baseline 边界诊断、嵌套一致性、确认层审计和 R1 handoff。 |
| R0-T10 | `[codex] R0-T10 替代指标口径敏感性骨架` | `codex/r0-t10-alternative-metric-sensitivity` | 可选 | 仅在 R1 需要时启用，用于一次改变一个构件的替代口径，例如 `NATR20`、`LogRange30`、`ER30`、`TurnoverShrink30_90`。不得与全部 W/q/K 完全交叉，不得用未来表现筛选。 |
| R0-T11 | `[codex] R0-T11 Post-Up-Release Short-PCT 研究接口占位` | `codex/r0-t11-post-release-short-pct-interface-placeholder` | 可选 | 只定义后续 R3/R4 所需的字段占位和边界说明，不计算释放、不定义未来路径、不改写 R0 状态。本 task 只有在需要提前对齐 R3/R4 接口时才做。 |
| R0-T12 | `[codex] R0-T12 R0 并行确定性与性能优化` | `codex/r0-t12-deterministic-parallel-runtime` | 可选 | 仅当 27 主网格运行成本过高时启动。目标是保证单线程与并行 worker 在 schema、排序、哈希和关键统计量上确定一致。 |

### 15.1 必须 task 与可选 task 的边界

R0-T01 至 R0-T09 是进入 R1 的最低必要路线。它们分别覆盖定义、输入门禁、指标实现、分位与分数、状态逻辑、确认区间、candidate 产物和交接审计。缺少任一项，R1 都无法合法判断状态是否存在、是否稳定、是否超过零模型或是否具有超越 P 的结构增量。

R0-T10 至 R0-T12 是可选任务。它们不应阻塞基线 R0 完成，除非 R0-T09 审计显示基线样本容量、C2/V 可用性、weak baseline 边界或运行性能已经影响 R1 的可执行性。可选任务不得引入未来收益、未来突破方向、未来路径标签或回测结果。
