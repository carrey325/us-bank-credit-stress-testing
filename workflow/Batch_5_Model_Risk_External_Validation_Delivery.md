# MF772 美国区域银行分贷款组合信用压力测试
## Codex 执行计划

> 项目依据：MF772 Final Project Proposal。  
> 核心原则：**核心数据定义、信用损失重构、时间顺序验证和压力测试必须严谨；边缘模块允许使用明确 fallback。**  
> 所有结果数字必须由真实 pipeline 和模型输出生成，不得硬编码或借用 baseline repo 的结果。


# Batch 5 — Model Risk 扩展、市场外部验证与最终交付

## 目标

在核心项目已经完整完成的前提下，做最有价值的增强，并完成课程报告、GitHub 和最终可复现交付。

优先级：

1. Adaptive Conformal Calibration；
2. Market-price external validation；
3. Final report / GitHub / presentation；
4. 只有仍有时间才做 LightGBM / NGBoost / virtual bank / multimodal。

---

# Part A — Adaptive Conformal Calibration

## 定位

Adaptive Conformal 不是新的 credit-loss 主模型。

它是：

> 对 Quantile / Bayesian 预测区间做样本外校准的 Model Risk 层。

---

## 1. 输入

优先：

- 90% quantile prediction；
- Bayesian posterior predictive interval。

---

## 2. 方法

使用 rolling / adaptive calibration：

1. 训练模型；
2. 在历史 OOS 收集 residual / conformity score；
3. 用过去 calibration window 调整下一期 interval；
4. 严格保持时间顺序；
5. 不随机 shuffle。

---

## 3. 评价

比较：

```text
Raw 90% coverage
Calibrated 90% coverage
Interval width
Winkler score
Crisis underprediction count
```

### 成功标准

不是要求覆盖率恰好 90%。

目标：

- closer to target；
- 区间没有无限膨胀；
- crisis underprediction 减少。

### Fallback

若时间序列 adaptive conformal 实现复杂：

- rolling residual bootstrap；
- 明确标记 fallback；
- 不阻塞 final report。

---

# Part B — Optional Market External Validation

## 目标

检验 credit risk score 是否识别未来市场脆弱性。

不是构造交易策略。

---

## 1. Entity Mapping

必须建立：

```text
bank legal entity
→ BHC / parent
→ listed ticker
```

不得使用模糊银行名称直接匹配 ticker。

保存：

`metadata/bank_parent_ticker_mapping.csv`

---

## 2. Market Outcomes

优先：

- 1 month realized volatility；
- 3 month realized volatility；
- 6 month realized volatility；
- 12 month realized volatility；
- maximum drawdown；
- excess return。

---

## 3. Risk Score

必须使用当时已经可得的监管信息生成。

不得：

- 用后来修订的 Call Report；
- 用未来银行风险分数预测过去股票。

---

## 4. 回归

```text
FutureMarketRisk(i,t+h)
=
alpha
+ beta × CreditRiskScore(i,t)
+ controls
```

Controls：

- size；
- valuation；
- momentum；
- market beta。

---

## 5. 正确结果解释

若：

- high-risk banks 后续 volatility 更高；
- drawdown 更大；

就说明模型识别到脆弱性。

即使：

- excess return 不显著；

也不是失败。

---

## Fallback

数据受限时：

- 只使用公开股票价格；
- 不做 TRACE；
- 不做 CDS；
- 不阻塞课程核心。

---

# Part C — Optional Nonlinear Challenger

只有前面全部完成后再做。

## LightGBM

用途：

- 非线性；
- threshold；
- SHAP；
- monotonic constraints。

### 评价

与 FE 比：

- OOS RMSE；
- stability；
- interpretation。

无改善也可以是结论。

---

## NGBoost

用途：

- probability distribution；
- mean + uncertainty。

### 注意

NCO：

- near zero；
- heavy tail；
- negative recovery values。

可尝试：

- asinh transform；
- Student-t。

如果工程成本过高，优先放弃 NGBoost 而不是主项目。

---

# Part D — Optional Data Extensions

只有课程报告、模型和压力测试全部冻结后才做。

## Virtual Bank Merger Reconstruction

按 merger lineage 重新合并历史银行。

价值：

- 更接近 Covas et al.；
- 改善并购连续性。

成本高，非核心。

---

## Text Extension

SEC 10-K / 10-Q：

- CRE；
- office；
- refinancing；
- criticized loans；
- reserve build；
- deposit competition。

研究：

> 文本风险是否在控制 Call Report 后增加未来 NCO 预测能力？

---

## Geography Extension

FDIC SOD + county macro：

- branches；
- deposits；
- local employment；
- local income；
- construction activity。

注意：

- branch geography ≠ loan geography；
- 只能作为 proxy。

---

# Part E — Final Tables / Figures

## 必须表格

### T1 Sample Coverage

- banks；
- quarters；
- raw fields；
- observations；
- exclusions。

### T2 Data Quality

- mapping；
- missingness；
- reconciliation；
- manual audit。

### T3 Model Comparison

- AR；
- FE；
- bias-corrected FE；
- Quantile；
- Bayesian；
- optional challenger。

### T4 Fed Stress Results

- baseline；
- severe；
- segment losses；
- capital depletion。

### T5 Robustness / Model Risk

- CRE exposure definitions；
- scenario lambda；
- model ranking；
- conformal coverage。

---

## 必须图

1. Segment NCO/NPL history；
2. Exposure/loss heatmap；
3. CRE-to-capital vs severe capital depletion；
4. FE mean vs quantile/Bayesian intervals；
5. Historical pseudo-stress；
6. Fed baseline/severe paths；
7. Ranking stability；
8. Optional market validation。

---

# Part F — Final 10-Page Report

建议：

## Page 1
Abstract / RQ / Contribution

## Page 2
Literature + Baseline Gap

## Page 3
Data + Sample + Regulatory Fields

## Page 4
NCO Reconstruction + QA

## Page 5
Dynamic FE + CRE Interaction

## Page 6
Quantile + Hierarchical Bayesian

## Page 7
OOS + Historical Pseudo-Stress

## Page 8
Fed 2026 Stress Results

## Page 9
Capital Depletion + Model Risk + Robustness

## Page 10
Conclusion + Limitations

---

# Part G — GitHub Release

## README 结构

只写：

1. Problem；
2. Data；
3. Method；
4. Key Results；
5. Reproducibility；
6. Limitations。

不要把论文全文塞进 README。

---

## Replication Commands

目标：

```bash
make raw
make standard
make panel
make qa
make models
make stress
make report
```

如果 raw data 太大：

- 提供 manifest；
- 提供 download script；
- 不把原始监管大文件提交到 GitHub。

---

# Part H — Final Reproducibility Audit

最终自动检查：

- [ ] missing 没有被错误填 0；
- [ ] YTD 已季度化；
- [ ] field mapping 有 effective dates；
- [ ] merger quarters 有记录；
- [ ] 宏观无 look-ahead；
- [ ] OOS 没随机 shuffle；
- [ ] stress results 无硬编码；
- [ ] resume metrics 无硬编码；
- [ ] quantile 没用错误 RMSE 逻辑判断；
- [ ] Bayesian diagnostics 已保存；
- [ ] CRE 不显著后没有未经预注册的数据挖掘；
- [ ] 所有 final table/figure 可由脚本重建。

---

# Part I — 最终 Resume Metrics

最终才生成真实简历 bullet。

计划中的数字：

- 30 banks；
- 7K+ observations；
- 40+ fields；
- RMSE -5%；
- high-CRE +30% capital depletion；

都只能由：

`outputs/reporting/resume_metrics.json`

真实读取。

任何预期数字与真实结果不一致时，以真实结果为准。

---

## Batch 5 Definition of Done

- [ ] Adaptive Conformal 完成或明确 fallback；
- [ ] Optional market validation 完成或明确不做；
- [ ] Final tables 自动生成；
- [ ] Final figures 自动生成；
- [ ] 10-page report draft 完成；
- [ ] README 完成；
- [ ] reproducibility audit 通过；
- [ ] resume metrics 自动生成；
- [ ] 项目所有局限和失败结果有记录。

---

## Codex 完成后必须回复

1. Adaptive Conformal 结果；
2. Market validation 是否完成；
3. Final table/figure 清单；
4. Final report 路径；
5. GitHub README 状态；
6. Reproducibility audit；
7. 最终真实样本规模；
8. 最终 OOS improvement；
9. 最终 CRE / capital result；
10. 未解决问题和下一步研究建议。
