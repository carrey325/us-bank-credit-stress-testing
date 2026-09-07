# R2 — 时间口径、核心模型重估与研究决策

前置：R1 COMPLETE，独立数据验收通过，输入 hash 匹配。
阅读：总控、原 Batch 2、R1 交接记录及相关 Batch 3 接口。

## 1. 范围

修改现有 `macro.py`、`modeling.py`、model config、必要的特征/时间接口和测试。重建 model panel、EDA、AR、Dynamic FE、SPJ 诊断、CRE interaction。

不开发新模型家族，不增加股票/NLP/地理数据，不尝试穷举 lag、winsorization、样本选择以获取有利结果。

## 2. 先记录修改种类，再运行

在 `metadata/spec_changes.md` 逐条区分：

- DATA_CORRECTION：字段、范围、单位等有外部证据的纠错。
- IMPLEMENTATION_CORRECTION：时序、分组、计算、评价错误修复。
- SPECIFICATION_AMENDMENT：公式、特征、估计/预测时点的实质修订。
- EXPLORATORY_DIAGNOSTIC：看过结果后的有限诊断。

记录原值、新值、理由、证据、是否已看过结果以及影响窗口。不得把当前新增规格称为原始预注册。

首先在修正数据上重跑原规格；若旧实现有已知错误，这条回放只能用于诊断，不因其沿用旧代码而成为有效基准。之后再形成 VALID_CORRECTED 主比较。

## 3. 建立一致的预测时间合同

明确保存四个不同概念：

```text
report_period
available_at
forecast_origin
target_period
```

季度末不是自动的报表公开日。available_at 缺准确记录时采用明确、保守的规则并说明限制；下载于今天的修订报表不能被称为完整历史实时快照。

原 Batch 2 允许 final-vintage + lag fallback，但这只是局限披露，不消除所有修订偏差。对宏观构造记录 observation/release/vintage/transform，不要在宏观层和模型层不加区分地重复施加“为可得性而滞后”。真实的经济滞后仍应保留并解释。

按任务区分：

- 历史一步预测：输入只来自起点实际可得信息。
- 历史条件 pseudo-stress：允许给定之后真实宏观路径，但不能用之后银行结果、控制变量或真实状态修正递归。
- Fed 压力：宏观未来路径属于假设输入，不是偷偷使用未来真实信息。

保留原测试时期用于可比性；预测时点或目标季度必须改变时，先记录实质修订，不能悄悄移动目标。

## 4. 防止不连续季度和事后筛样

组内 shift(1) 必须验证是紧邻季度。先形成完整季度网格与可得性标志，再做 lag；不能把银行上一条观测无条件当上一季度。

区分 `prediction_eligible` 与 `evaluation_eligible`：前者只依据起点信息和预测输入，后者另要求实际目标可用于评分。预测路径不能因为未来实际 NCO 或未来控制变量缺失而被提前删除。

分银行、分组合、分阶段列出 dropna 的每种原因，定位 C&I 和 2025Q4 起点缺失。无法恢复的记录保留缺失，不能自动填值。

## 5. 先重估最小基线

主比较保持 AR 与原 Dynamic FE，在相同组合、相同 forecast origin/target、相同评估键上比较。R1 数据修正后 SPJ 可重新跑作偏误/稳定性诊断，但不能预设其会更好。

主指标：RMSE、MAE、bias、相对 AR 的改善；原实现 OOS R² 的定义要写清楚，不能把 1-SSE/SST 自动说成“相对 AR 的 OOS R²”。可另报 1-SSE_model/SSE_AR，并使用明确名称。

保存预测明细，不只汇总 pooled 值。分别报告 CRE/C&I 和原四个窗口，附误差贡献最大的银行/季度及相应数据审计状态。等权和 exposure-weighted 指标如并列，明确它们回答不同目标，不能事后挑更好的一项。

检查 FE 的矩阵秩、共线性、尺度、滞后系数与递归稳定性。用独立实现或可手算的小例子核对估计/预测/标准误；不得把换求解器当作经济改进。

最多增加一个精简宏观 FE 作为探索性诊断：在看本轮结果前写入配置，宏观变量限定少数有原研究依据的项，不做自动搜索。它与原规格分表报告，不能覆盖原失败结果。

## 6. CRE interaction：先验收模型含义

继续区分机械暴露效应与单位 CRE 损失率效应。

检查并写清：

- primary exposure 是 lagged CRE/Tier1，不是事后全样本最后一期暴露。
- CRE price shock 是增长率还是下跌幅度。将 shock 乘 -1 只改系数符号，不会把反向证据变成正向支持。
- 若暴露随时间变化，检查是否需要纳入暴露主效应；银行 FE 不自动吸收时变主效应。若修订公式，记录为看过结果后的规格修订。
- 全国季度 shock 主效应可被 quarter FE 吸收，interaction 利用横截面暴露差异，不能解释为严格因果。
- 报告效应、clustered SE/置信区间、样本和符号，不能只报 p 值。

有限稳健性先做原计划已列出的 CRE share 替代定义，以及 pre-2022 暴露设定（只用于其后相应窗口，不能把 2021Q4 值倒填到早期历史）。其余 bank trend、placebo、CRE 子项等保留任务清单，不默认全部展开。增加检验族时按原要求记录多重检验处理。

无稳定证据应表述为“当前数据/设定不足以支持额外放大”，不能进一步宣称集中度绝无效应或机械效应解释了全部风险。

## 7. 结果对照与决策文件

输出建议：

```text
outputs/repair/r2/time_alignment_audit.csv
outputs/repair/r2/sample_attrition.csv
outputs/repair/r2/old_vs_corrected_summary.csv
outputs/repair/r2/error_contributors.csv
outputs/repair/r2/research_decision.md
```

其余正式预测、系数、EDA 继续使用原 `outputs/models/`、`outputs/eda/`，带本轮产物元数据，不建立第二套模型代码。

research_decision 必须回答：数据修复改变了什么；AR/FE 差异是否仍在；哪些窗口/组合是问题来源；CRE 假设得到哪种程度支持；本轮还值得验证什么；建议继续完整 R3 还是最小验证后收尾。

## 8. 测试与完成标准

必须覆盖未来数据不可见、同季度银行公开日、宏观重复 lag、缺报季度、共同评分样本、未见银行、预测时无需目标值、interaction 暴露日期与主效应等。

R2 COMPLETE 的条件是计算和实验比较可信、变化可追踪、结论与结果一致。FE 输给 AR、交互项不显著或反向，都不是自动 BLOCKED。

若时间定义/数据范围尚无可靠实现，或必须扩大研究才能继续，应 BLOCKED/提出范围决策，不先把旧压力数字再发布一次。

R2 完成后，Scheduler 暂停扩展，提交研究范围建议。得到继续或缩减决定后，再按相应范围进入 R3；不得自行启动 Bayesian 或其他扩展。
