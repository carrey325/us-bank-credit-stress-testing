# MF772 美国区域银行分贷款组合信用压力测试
## Codex 执行计划

> 项目依据：MF772 Final Project Proposal。  
> 核心原则：**核心数据定义、信用损失重构、时间顺序验证和压力测试必须严谨；边缘模块允许使用明确 fallback。**  
> 所有结果数字必须由真实 pipeline 和模型输出生成，不得硬编码或借用 baseline repo 的结果。


# Batch 4 — Fed 2026 Stress Test、Loss Attribution 与 Capital Depletion

## 目标

将前面验证通过的模型应用到 Fed 2026 官方宏观情景，生成项目最核心的最终结果：

- baseline vs severely adverse；
- 9-quarter recursive credit-loss paths；
- segment loss attribution；
- CRE vulnerability；
- projected capital depletion；
- scenario sensitivity；
- model/ranking stability。

---

# 1. 下载和标准化 Fed 2026 Scenario

## 官方情景

必须至少包括：

- Baseline；
- Severely Adverse。

### Horizon

主结果：

```text
2026Q1–2028Q1
```

9 个季度。

更后恢复季度可存储，但不是主要资本结果。

---

## Scenario Table

构造统一 schema：

```text
scenario
quarter
unemployment
real_gdp_growth
cre_price
house_price
bbb_yield
mortgage_rate
short_rate
long_rate
...
```

保存：

`data/external/fed_2026_scenarios.parquet`

---

# 2. Stress Jump-Off

起点：

```text
2025Q4
```

每家银行使用真实：

- NCO；
- NPL；
- exposure；
- capital；
- allowance；
- bank features。

如果某银行 2025Q4 不完整：

- 不自动填值；
- 使用清楚 fallback；
- 或从 final stress universe 排除并记录原因。

---

# 3. Recursive Stress Forecast

对每个：

```text
bank × segment × scenario × model
```

执行：

1. 使用 2025Q4 real state；
2. 输入 2026Q1 scenario；
3. 预测 2026Q1 NCO；
4. 将 predicted NCO 放入下一期 lag；
5. 输入 2026Q2 scenario；
6. 重复 9 个季度。

必须保存每一期。

---

## Output Schema

`outputs/stress/stress_paths.parquet`

字段：

```text
bank_id
segment
scenario
model
quarter
horizon
predicted_nco_rate
exposure
predicted_loss
starting_tier1
starting_allowance
```

---

# 4. Exposure Assumption

## Core

Static exposure。

目的：

- 不让贷款增长模型掩盖信用损失主线；
- 保持可解释性。

## Sensitivity

- exposure −5%；
- exposure +5%。

可按总水平同比缩放，不需要复杂 portfolio growth model。

---

# 5. Loss Attribution

## Segment Dollar Loss

```text
Predicted Credit Loss
= Predicted NCO Rate × Exposure
```

## Cumulative Loss

9 季度累计。

## Loss-to-Loans

```text
Cumulative Loss / Starting Loans
```

## Capital Depletion

主要简历和结果指标：

```text
Cumulative Stress Credit Loss
/
Starting Tier1 Capital
```

表达为：

```text
% of starting Tier1 capital consumed
```

这比简化 CET1 路径更稳健。

---

# 6. Allowance Adjustment

构造：

```text
Allowance-Adjusted Loss
=
max(Cumulative Loss - Starting Allowance, 0)
```

用于回答：

> 现有准备金可以先吸收多少信用损失？

---

# 7. CRE Vulnerability Analysis

## 分组

按 stress jump-off 前的：

```text
CRE-to-Tier1
```

将银行分：

- Low；
- Mid；
- High。

Alternative：

```text
CRE Share
```

## 比较

- cumulative credit loss；
- CRE loss；
- capital depletion；
- allowance-adjusted loss；
- CRE contribution to total loss。

### 简历数字规则

例如：

> high-CRE banks faced 30% greater projected capital depletion

只能在以下条件满足后生成：

1. group definition 已预先固定；
2. 数字由脚本计算；
3. 不人工挑组；
4. 报告绝对值和相对值；
5. 明确 scenario 和 model。

---

# 8. Scenario Sensitivity

## Lambda Scenario

构造：

```text
Scenario(lambda)
=
Baseline
+
lambda × (Severe - Baseline)
```

lambda：

```text
0.5
1.0
1.25
```

### 含义

- 0.5：半强度；
- 1.0：官方 severe；
- 1.25：比官方 severe 再强 25%。

必须标记：

> Researcher sensitivity scenario

不得称为 Fed official scenario。

---

## Partial Shocks

预先做：

1. CRE-only；
2. unemployment-only；
3. high-for-longer rates。

用于 attribution，不声称宏观路径完全自洽。

---

# 9. Severity Monotonicity QA

原则上：

```text
Severe aggregate loss
>= Baseline aggregate loss
```

lambda 越高，系统性损失不应无解释下降。

### 若不满足

检查：

- coefficient sign；
- transformation；
- recursive instability；
- lag issue；
- macro variable mapping；
- negative rate effect。

允许个别银行或 segment 例外，但必须解释。

---

# 10. Simplified Capital Roll-Forward

这是次级模块。

只有 loss-to-capital 主结果稳定后才实现。

## 公式

```text
Capital(t+1)
=
Capital(t)
+ PPNR(t)
- Provision(t)
- Taxes(t)
- Distributions(t)
```

Provision：

```text
NCO
+ Target ACL(t)
- ACL(t-1)
```

### Core Simplification

- PPNR：过去 8 季度中位数 / assets；
- RWA：static；
- losses 时 distributions = 0。

### Fallback

只报告：

```text
credit loss / starting Tier1
```

不强行生成伪精确 CET1 path。

---

# 11. Ranking Stability

对不同模型：

- Dynamic FE；
- Quantile；
- Bayesian；

计算银行 stress ranking。

指标：

- Spearman rank correlation；
- top-quartile overlap。

目标：

> 判断“最脆弱银行”结论是否依赖模型。

---

# 12. 最终表格

必须生成：

### T4 Fed Stress Results

```text
bank
baseline_loss
severe_loss
cre_loss
ci_loss
mortgage_loss
capital_depletion
allowance_adjusted_loss
```

### T5 Sensitivity

- lambda；
- partial shocks；
- exposure ±5%；
- model choice。

### CRE Group Table

```text
low / mid / high CRE
mean severe loss
mean capital depletion
median capital depletion
difference high-low
```

---

# 13. 必须生成图

1. Baseline vs Severe 9-quarter system loss；
2. Segment contribution；
3. CRE-to-capital vs capital depletion；
4. High/Mid/Low CRE capital depletion；
5. Lambda sensitivity；
6. Model ranking stability。

---

# 14. Resume Metrics 自动输出

生成：

`outputs/reporting/resume_metrics.json`

Schema：

```json
{
  "n_banks": null,
  "n_observations": null,
  "n_raw_fields": null,
  "reconciliation_rate": null,
  "best_oos_rmse_improvement_vs_ar": null,
  "best_model_name": null,
  "high_cre_capital_depletion_difference": null,
  "high_cre_group_definition": null,
  "stress_scenario": "Fed 2026 severely adverse"
}
```

不得写固定：

```python
0.05
0.30
```

这些数字必须从模型结果自动产生。

---

## Batch 4 Definition of Done

- [ ] Fed scenario ingestion 完成；
- [ ] 9-quarter recursive forecast 完成；
- [ ] baseline / severe 均有结果；
- [ ] segment attribution 完成；
- [ ] capital depletion 完成；
- [ ] CRE group comparison 完成；
- [ ] lambda sensitivity 完成；
- [ ] severity monotonicity 检查完成；
- [ ] ranking stability 完成；
- [ ] resume metrics 自动生成；
- [ ] 不把 simplified capital path 冒充 Fed CET1 model。

---

## Codex 完成后必须回复

1. 最终 stress universe 银行数；
2. 使用模型；
3. baseline aggregate loss；
4. severe aggregate loss；
5. segment attribution；
6. CRE high/low difference；
7. capital depletion 分布；
8. sensitivity 结果；
9. ranking stability；
10. 是否可以进入 Batch 5。
