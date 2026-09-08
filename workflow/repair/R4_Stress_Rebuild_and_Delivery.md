# R4 — 压力结果重建、勘误归因与最终交付

前置：R3 COMPLETE，用途清单与本轮数据/模型 hash 一致。
阅读：总控、原 Batch 4、原 Batch 5、R1–R3 交接和用途清单。

## 1. 范围

复用现有 `stress.py`、`reporting.py`、Batch 4/5 入口、Makefile 与测试。只重建获准范围内的结果，并修正报告中的过度解释。

不开发完整资本 roll-forward、Mortgage 新模型、Bayesian、市场外部验证或新样本。若最终 stress universe 变化，记录原因，不以原 14 家为必须恢复的目标。

## 2. 模型与情景输入门槛

使用已留存、来源核验的 Fed 2026 最终 baseline/severely adverse 场景及其 manifest，不以未经检查的新版本替换原输入。复用已核实的下载文件。

只允许 R3 清单准许 conditional mean stress 的模型生成主路径。一步 quantile 模型没有多期尾部分布身份，不得因原 Batch 4 要求 Quantile ranking 就强制加入正式排名。

如果没有获准的均值压力模型，本阶段交付诚实的验证/局限报告，明确不提供可信的 Fed stress 数字；不使用失效旧结果占位。诊断性路径与正式结果彻底分开。

## 3. 同一套宏观变换和时间合同

核对历史特征与情景特征的增长率/指数、同比/环比、百分数/小数、yield/spread 口径；同比计算所需历史边界水平必须来自匹配的来源与定义。

处理方法复用 R2 时间合同，不另写一套只在 stress 中成立的变换。区分假设已知的未来宏观情景与历史真实可得信息，记录每期输入来自哪个场景季度、哪个 lag、哪个边界历史值。

检查 2025Q4 起点是否满足数据和模型用途要求；未完整的银行/组合逐项给出缺什么及原因。不能把缺失 Mortgage 视为零，也不能只凭有 CRE 数据就把其与双组合银行混成同口径总风险排名。

## 4. 九季度损失路径与单位

主期限按原方案 2026Q1–2028Q1，静态 exposure。保存每季度预测状态，不只保存总和。

统一单位：

```text
quarter_loss_thousands
  = annualized_nco_rate_decimal / 4 * exposure_thousands
```

如果配置或变量改为百分数，显式除以 100 后再换算，不能重复年化。

历史负 NCO 保留。压力聚合是否使用非负 floor 是另一个建模选择：按已记录设定处理，并报告应用次数和有/无 floor 的敏感性。不能为让 severe > baseline 而悄悄改变 floor、截断预测或更换系数符号。

`Loss / starting Tier1` 是 modeled credit-loss burden，不是完整资本变化，也不是 CET1 ratio 的百分点下降。中文优先称“累计信用损失相当于初始 Tier1 的比例”，避免直接宣称这些资本实际已经被消耗。

Allowance-adjusted loss 只作为简化覆盖指标。采用全行 allowance 抵扣部分组合损失时必须说明范围、不能每类组合重复抵扣整笔准备金，更不能称为完整会计资本路径。

## 5. CRE 分组与归因

依据修正后的 jump-off CRE/Tier1 重新分组，保存分组规则、成员与阈值。不能继续使用旧 tercile cutoffs。

提供两种同范围结果：

- 模型预测损失率下的资本压力。
- 每种贷款给所有银行相同参考损失率时的机械暴露对照；参考率来源与计算规则必须固定，明确只是描述性分解。

二者帮助解释差异是否主要与暴露/资本构成相关，但不能把剩余差额称为因果的 concentration effect。额外单位损失率证据仍来自 R2 规范检验。

比较旧新结果时分开共同银行样本与新的有效全样本，标注分组成员变化。28.41pp 等旧值只可出现在“失效版本对照”，不作为继续保留的结果目标。

## 6. 敏感性和稳定性

保留原 lambda=0.5/1/1.25、exposure ±5%、有限 partial shocks 等已有轻量实验，使用同一获准模型和统一输入版本。研究者比例场景不称为 Fed 官方额外场景。

严重程度单调性失败时输出诊断与原因。不能强行排序/截断使测试通过，也不能把无解释的路径作为正式主结论。

排名比较仅在共同银行/组合和可比预测目标上进行。不同尾部/均值目标的对照最多是用途敏感性，不能解释为均值预测模型优劣。报告 Spearman、交集规模、top group overlap 的分母。

## 7. 旧结果失效与整链重建核验

从 R1 的新 panel 到 R2/R3 模型、residual calibration、压力路径、最终图表、PDF、README 和 resume metrics，校验 run/hash/spec 依赖。

必须有一个回归测试：故意提供旧 mapping 产物、旧模型或旧校准残差时，正式入口拒绝产出报告。

尽量完成在已恢复的 manifest-backed raw 输入上的干净重建。不能在缺 raw、缺环境或没有真正执行全链时宣称端到端复现 PASS。可以区分 unit/integration/artifact-consistency/end-to-end 四类证据。

R4 不得临时更改 R1 映射或 R2 主规格。发现上游实质错误，返回责任阶段并使依赖产物失效；不要仅改报告数字。

## 8. 最终交付

复用原 T1–T5 和 10-page report 结构，不为了模型未完成填假图。结果缺失时明确写 unavailable/deferred，并解释对研究范围的影响。

必须新增简明 `outputs/reporting/errata.md`：

```text
旧错误/不准确表述
证据
修复方式
受影响数据与输出
修复后可支持的结论
仍不可支持的结论
```

T1：有效样本、表单/年份覆盖、排除原因，区分历史 panel、模型评分、stress universe。
T2：独立字段/范围核验、缺失、组件完整性、资本核对，说明不同 QA 指标含义。
T3：同目标、同样本的 AR/FE/可用 challenger 比较，不把 quantile pinball 与 mean RMSE 混成一个排行榜。
T4：有合格模型则给 baseline/severe 九季度结果，没有则给用途限制与 unavailable 状态。
T5：有限稳健性、预测区间、模型用途与排名稳定性。

README 只保留本轮已验证事实。历史错误数字不再作为 Key Results。主张必须对应有效结果文件和版本。

`resume_metrics.json` 从已验证表计算，增加必要的 scope/status；未验证或不可用为 null + reason，不是 0。数据修复改变了目标定义时，不把旧新 RMSE 变化说成预测方法提升。

最终结论对 RQ1–RQ4 分别给 SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE / NOT_EVALUATED，并列对应证据和限制。没有显著性也可以完成；没有可靠输入却不能发布强结论。

## 9. R4 完成标准

所有最终产物来源一致、数值可追踪、无混入旧输出、用词不超出模型用途、原始数据未被覆盖、测试与重建证据真实、未完成扩展清楚列出，并提交本轮最后 checkpoint。

最终回复应包括：真实样本、有效模型用途、baseline/severe 是否可发布、CRE 结论、尾部结论、旧新差异、复现层级、最终文件路径、未决问题和建议停止/继续的明确范围。

此阶段的目标是结束一轮可验收的修复，而不是因为报告不够亮眼再自动启动下一轮模型开发。
