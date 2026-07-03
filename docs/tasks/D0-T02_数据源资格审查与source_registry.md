# D0-T02：数据源资格审查与 source registry 初版

> Task ID：D0-T02
> 状态：designed
> 关联阶段：D0
> 目标门禁：G1
> 当前运行资格：eligible_for_d0

## 1. 目标

建立 D0 阶段的数据源准入契约，定义候选来源的身份、允许用途、禁止用途、字段覆盖、
许可证与条款状态、时点语义、原始快照保留规则、哈希要求、修订策略和失败阻断规则。

本任务的输出只回答“哪些来源可以进入后续设计审查，以及以什么身份进入”，不批准任何
正式抓取、装载或研究运行。

## 2. 非目标

- 不创建 DuckDB 文件；
- 不抓取行情、交易日历、公司行为、财务报表或任何正式数据；
- 不运行 D0 装载；
- 不实现 D1/D2/D3 表结构；
- 不生成 `d3.daily_market_observations`；
- 不计算 PCVT、状态、事件、标签、收益或回测；
- 不把第三方封装工具直接等同为官方数据源；
- 不因 API 能返回数据就自动批准为正式来源。

## 3. Source Registry 产物

本任务新增：

```text
configs/d0/source_registry.v1.json
schemas/d0_source_registry.schema.json
tests/test_d0_source_registry.py
```

`source_registry.v1.json` 是 D0 source registry 初版配置，状态为 `accepted`。
后续任何 D1/D2/D3 任务若要引用来源，必须先检查该来源在
registry 中的 `qualification_status`、`allowed_uses`、`prohibited_uses`、
`as_of_policy` 和 `revision_policy`。

## 4. 来源身份规则

1. 数据源本体、聚合工具、SDK、镜像仓库和端点目录必须分开登记。
2. 第三方封装工具不得替代底层发布方、API 端点、许可证或时点语义审查。
3. 免费访问不等于正式研究可用；API 可返回数据不等于允许进入正式数据产品。
4. 任一来源若缺少原始快照保留、哈希、as-of 规则或 revision 规则，不得进入正式 D1/D2/D3。
5. 任何 API Key、账号 token、密钥、供应商授权文件或许可证文件不得提交到仓库。

## 5. 候选来源结论

### `CSINDEX_OFFICIAL`

定位：中证指数官方来源。

资格状态：`approved_limited_g0_evidence`。

允许用途：

- `universe_membership_evidence`；
- `index_constituent_document_snapshot_audit`。

禁止用途：

- 行情来源；
- 公司行为来源；
- 交易状态来源；
- 财务报表来源；
- 未经新增审查的 D1/D2/D3 正式来源。

结论：只允许延续为已通过 G0 的中证 800 成分证据链，不扩展为行情、公司行为或交易
状态来源。

### `A_STOCK_DATA_RECON`

定位：`simonlin1212/a-stock-data`，端点调研与字段覆盖参考工具。

资格状态：`endpoint_research_only`。

允许用途：

- 端点调研；
- 字段覆盖参考；
- 候选端点发现。

禁止用途：

- 直接作为正式数据源；
- 直接作为原始快照发布方身份；
- 用仓库许可证替代底层端点许可证；
- 直接进入 D1/D2/D3 装载。

结论：如后续使用其中任何端点，必须追溯到底层原始发布方或 API 端点，并创建独立
source registry 记录。

### `HITHINK_FINANCIAL_API`

定位：同花顺 Financial-API，正式候选主数据源审查对象。

资格状态：`formal_candidate_pending_terms_review`。

候选覆盖：

- 行情；
- 代码表；
- 公司行动；
- 财务报表；
- 交易日历；
- 指数；
- 涨停异动；
- 龙虎榜；
- 全市场导出。

阻断条件：

- API Key 管理未审查；
- 许可证/条款未审查；
- 配额、限流、全量/增量导出能力未审查；
- 原始响应保存规则未验证；
- revision/as-of 规则未明确；
- DuckDB 与供应商 `marketdb` 或本地导出缓存边界未明确。

结论：可作为后续正式主数据源尽调对象，但不得在 D0-T02 中批准正式抓取或装载。

### `BAOSTOCK`

定位：历史行情与交易状态的候选备用源或交叉校验源。

资格状态：`backup_candidate_pending_review`。

候选覆盖：

- OHLCV；
- 复权标记；
- 交易状态；
- 估值字段；
- 部分财务报表字段。

阻断条件：

- 免费使用边界和再分发条款未审查；
- 自有数据服务器的版本稳定性未验证；
- 历史修订策略未验证；
- 原始响应保存能力未形成正式规则；
- 复权字段的 as-of 语义未明确。

结论：可进入备用源或交叉校验源审查，不得作为唯一正式主源。

### 其他候选来源

`PUBLIC_A_SHARE_ENDPOINTS_REVIEW_BUCKET` 仅作为候选来源类别占位。交易所、公开网站、
供应商网页接口或其他 API 不得因为被列入该类别而进入正式抓取。任何具体端点必须新增
独立来源登记并完成条款、快照、哈希、as-of 和 revision 审查。

## 6. 失败阻断规则

以下任一情况发生时，来源不得进入 D1/D2/D3 正式数据产品：

- `license_status` 或 `terms_review_status` 不支持目标用途；
- 无法保留原始响应或原始文件快照；
- 无法计算并记录 SHA-256；
- 无法区分最终修订历史与当时可得历史；
- 无法说明历史修订、复权因子、公司行为或交易状态的生效时间；
- 数据源身份是封装工具但未追溯到底层发布方；
- 需要密钥但没有密钥管理、配额和日志规则；
- 来源限制禁止研究使用、保存、再处理或下游审查。

## 7. 验收标准

- 每个候选来源都有明确身份、来源类别、允许用途、禁止用途和资格状态；
- source registry 能区分正式候选源、备用源、交叉校验源、端点调研工具和已阻断来源；
- 对同花顺 Financial-API、baostock、a-stock-data 的定位清晰，不混淆数据源本体和聚合/封装工具；
- D1/D2/D3 后续任务能够根据 source registry 判断每类事实应该从哪个来源进入、何时阻断、何时需要人工审查；
- 配置、schema、测试和生成文档检查通过。

## 8. 后续任务

本任务通过后，后续任务仍为：

1. `D0-T03`：D1 / D2 / D3 数据产品契约

若 D0-T03 需要使用任何来源作为正式输入，必须先引用本 registry 中的资格状态；若资格
不足，必须新增来源审查任务或更新 source registry 版本，不得在 D0-T03 内绕过。
