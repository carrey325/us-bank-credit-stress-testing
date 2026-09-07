# R1 — 数据定义、监管映射与 Core Panel 修复

前置：完整阅读 `00_Repair_Control.md`、原 Batch 1、AGENTS.md。
原职责：Batch 1。目标不是提高模型分数，而是建立足以支持重新估计的数据。

## 1. 范围

修改现有 `metadata/field_mapping.csv`、`src/bankstress/transform/`、相关 io/metadata/qa、Batch 1 执行入口及其测试。必要时加一个轻量产物元数据帮助函数，不复制一套修复专用 pipeline。

允许在本阶段预检中修正 AGENTS 计划入口、接入 Repair state、增加旧结果失效说明。禁止训练新模型、修改假设、优化结果或补市场/Bayesian。

## 2. 先保护旧状态和原始输入

核对 HEAD、工作区和正在运行的任务，建立本轮状态与基准清单。优先复用 hash 验证通过的 raw 快照，不默认重新下载全部季度。旧结果用于审计的路径/提交必须保存。

旧模型、区间、stress、报告和 resume metrics 标记 `INVALID_PENDING_REBUILD`。临时 README 说明不必等待最终报告阶段。为批量执行入口加最小的上游版本/验证状态检查。

## 3. 逐项落实问题，不只改一个字段

创建 `metadata/repair_issue_log.csv`，字段至少包含 issue_id、affected_file、finding、evidence、status、owner_stage、affected_outputs、resolution。已证实问题、待复核问题和规格变更分别记录。

### 3.1 CRE 贷款余额和核销范围

本轮需要落地复核的问题：

- 旧映射把 2746 放入 CRE 建设贷款余额。2009Q2 FFIEC 041 原表将该备忘项目定义为不以房地产担保、列在 C&I/其他贷款中的地产用途贷款，它不能无条件替代有房地产担保的建设贷款 F158/F159。
- 2005Q3 FFIEC 041 原表中的 1480 非农非住宅地产余额，需与相应核销/回收范围对齐，不能在分母漏掉该项而在分子保留该类损失。
- 1415 与 F158/F159、1480 与 F160/F161 的有效期必须由对应年份的原表、instructions 或 taxonomy 证明。不能把“2009 年看见后继字段”直接当作实际切换日。
- 上述 041 示例不是 031 的自动映射规则。要分清 domestic / consolidated、U.S. / non-U.S. addresses、总项/子项、实报/派生以及表单适用条件。

建立“贷款范围 → stock 字段 → charge-off 字段 → recovery 字段”的对应关系。每条有效映射都要能回答分子分母为什么对应同一贷款集合。

### 3.2 原有 C&I、Mortgage 及银行控制变量

不假设 CRE 是唯一问题。对现有三类组合做范围一致性检查，重点定位 C&I 在 2025Q4 缺失较多的原因：真正缺报、字段变更、表单差异、解析问题，还是本来不适用。不能靠缺失填零、任意选择另一字段或剔除银行掩盖问题。

Mortgage 仍为原定义的 closed-end 1–4 family；核对国内/合并口径与流量是否匹配。不要求本阶段增加 Mortgage stress 模型。

总 NPL、allowance、Tier1、RWA 只核对现有功能使用的字段和口径，修正被证实的错配，不顺带开发新的会计模型。

## 4. 余额也必须检查组成项完整性

现有流量完整性检查要保留并验证。给 stock 增加按 form/date/segment 的组成规则，至少区分：

```text
REPORTED_ZERO
PRESENT
MISSING_REQUIRED
NOT_APPLICABLE
VALID_AGGREGATE_ALTERNATIVE
```

完整总项与完整子项允许按已验证的优先级选择一个，不得总项和子项同时相加。两个范围不同的 RCON/RCFD 项目不能仅按前缀优先级被认作等价。

缺少必要项时，整个该范围余额保持缺失并记录原因；不得用 `sum(min_count=1)` 把部分余额包装成完整组合。

建议保留 exposure_complete、flow_complete、scope_match、mapping_id、reason 等诊断字段。无需破坏已有主键或另造平行数据表。

## 5. 时间、单位与边界

YTD 季度化沿用原要求，但检查每个字段同一年内相邻季度连续性；Q3 不能减 Q1 当作单季度 Q3。字段切换时只允许有官方依据的同范围累计流量桥接，无证据则保留缺失。

平均余额必须使用相邻季度、同贷款范围；跨缺报、范围切换或并购不能无标记相减/平均。负 NCO 保留，极端观察回查来源，不为提高 RMSE 而删危机损失。

锁定计算单位：

```text
amount_unit = USD_thousands（若原始文件如此）
quarterly_nco_rate = quarterly_nco / average_exposure（小数）
annualized_nco_rate = 4 * quarterly_nco_rate（小数）
展示百分数 = 100 * annualized_nco_rate
```

这避免原 proposal 的百分数展示公式和代码的小数存储公式被混用。

## 6. 独立核验，而非同一公式自证

原 Batch 1 的 100–200 条核对要求保留，但采用固定种子的分层样本：覆盖 031/041、三类组合、字段切换前后、早期/近期、负 NCO/缺失及并购案例。可利用已有审计基础，不能只重新运行同一错误映射。

人工/独立基准要直接从对应原表含义与原始数值计算预期结果。生产 mapping 不能同时充当唯一参考答案。

分清三种核对：

1. 同范围组件/官方总项的一致性。
2. CRE/C&I/Mortgage 作为贷款子集的覆盖率和 gross-flow 上界检查。
3. Tier1/RWA 与单独报告资本比率的一致性。

三类贷款不是所有贷款，不能强制其净核销等于全行净核销。反过来，“不超过全行核销”也不能证明每类余额正确。核对报告明确测试对象和分母。

## 7. 必须增加的失败回归测试

- 缺少一个必要 CRE 余额组件时，不产生完整余额或损失率。
- 备忘地产用途字段不能被误当对应房地产抵押建设贷款分母。
- 总项与子项同时存在时不重复计算；范围不同的 reporting variants 不混拼。
- 字段生效前后、表单不适用、真实零和空值被正确区分。
- 余额缺上季、流量缺上季、跨年及同年跨季度缺口处理正确。
- 分子分母 domestic/consolidated 范围不匹配时拒绝可用 NCO rate。
- 负 NCO 保留，年化小数与百分数展示正确。
- 下游旧版本产物不能被当作本轮已验证输入。

测试中预期值来自固定的、可审计小样本或官方定义构造的最小例子，不来自生产函数再次计算。

## 8. 输出与重跑

复用既有入口重建 standard、credit panel、QA。所有数据变更保存明确版本，不改 raw。

新增轻量证据/差异文件，名称可与现有命名协调：

```text
metadata/repair_issue_log.csv
metadata/field_mapping_evidence.csv
outputs/repair/r1/definition_audit.md
outputs/repair/r1/panel_change_summary.csv
outputs/repair/r1/coverage_by_form_period.csv
outputs/repair/r1/validation_summary.json
```

比较旧新 exposure、NCO rate、CRE share、CRE/Tier1、缺失原因和 eligible 数量。分别报告共同样本与新增/退出样本。不能要求回到旧的银行数量、观察数或风险排序。

## 9. R1 验收

可用数据范围中的核心映射必须有足够证据；stock/flow 组件齐全且范围匹配；抽查没有未解决系统性错配；数据缺口没有填零；影响范围明确；测试与重建日志真实存在。

不能用“99% 检查通过”掩盖某一表单或一整段历史的系统性错误。无法复核的范围应明确标为不可用；重大缩短时期或缩减组合先提出决策。

数据不足以支持已约定范围、或独立证据与生产值持续冲突时，返回 BLOCKED。R1 不以模型改善作为过关条件。

结尾按总控交接模板回复，并说明 R2 可读取的 panel 版本、hash、有效范围及仍需保留的限制。
