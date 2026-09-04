# MF772 美国区域银行分贷款组合信用压力测试
## Codex 执行计划

> 项目依据：MF772 Final Project Proposal。  
> 核心原则：**核心数据定义、信用损失重构、时间顺序验证和压力测试必须严谨；边缘模块允许使用明确 fallback。**  
> 所有结果数字必须由真实 pipeline 和模型输出生成，不得硬编码或借用 baseline repo 的结果。


# Batch 2 — 宏观数据、EDA、研究规格冻结与核心计量模型

## 目标

在 Batch 1 的可信 credit panel 上：

1. 构造历史时点可得的宏观数据；
2. 完成 EDA；
3. 冻结 primary research specification；
4. 建立 AR baseline；
5. 建立 Dynamic Fixed-Effects 主模型；
6. 完成 CRE concentration interaction。

本 Batch 结束后，核心研究问题必须已经可以回答，即使高级模型尚未实现。

---

## 1. 宏观数据

### 数据源

FRED / ALFRED。

### 核心变量

#### CRE

- CRE price growth；
- GDP growth；
- BBB yield/spread；
- rate；
- unemployment secondary。

#### C&I

- GDP growth；
- BBB yield/spread；
- unemployment；
- short rate。

#### Mortgage

- unemployment；
- house price growth；
- mortgage rate。

---

## 2. 历史时点可得性

### 主方法

ALFRED vintage + release calendar。

定义 forecast origin：

> 当季度 t 的银行信息可合理获取时，只使用当时已经公开的宏观信息预测 t+1。

### 保存

`metadata/macro_release_calendar.csv`

字段：

```text
series_id
observation_date
release_date
vintage_date
value
frequency
aggregation_rule
transformation
source
```

### 频率转换

- monthly → quarterly mean 或 quarter-end；
- weekly mortgage → quarterly mean；
- GDP → quarterly；
- price index → q/q 或 y/y growth。

所有规则写入：

`configs/macro_series.yaml`

### 必须测试

随机选择历史 forecast origin，例如 2010Q1：

- merged macro release date 不得晚于 forecast origin；
- 不得出现未来季度数据；
- final vintage 和 real-time vintage 分开保存。

### Fallback

若完整 ALFRED 工程延迟：

1. GDP + unemployment 保持 vintage；
2. 其他序列使用 final vintage，但至少 lag 1 quarter；
3. 自动生成 limitation note；
4. 不允许悄悄降级。

---

## 3. 构造 Model Panel

将：

```text
credit_panel
+
macro_panel
```

合并成：

`data/derived/model_panel.parquet`

主键：

```text
bank_id
segment
report_date
```

### 必须包含

- current/lagged NCO；
- current/lagged NPL；
- exposure；
- CRE share；
- CRE-to-Tier1；
- allowance；
- capital；
- loan growth；
- macro variables；
- merger flags；
- model eligibility。

---

## 4. EDA

### 样本统计

输出：

- banks；
- segments；
- quarters；
- observations；
- exposure distribution；
- NCO/NPL distribution；
- CRE share；
- CRE-to-capital。

### 时间图

2005–2025：

- segment NCO；
- segment NPL；
- unemployment；
- CRE price；
- house price；
- BBB spread。

标记：

- GFC；
- COVID；
- 2022+ rate/CRE stress。

### Lead-Lag

检查：

```text
Macro_t
→ NCO_t+1 ... NCO_t+4
```

用于理解合理滞后。

### CRE 分组

按 pre-stress CRE exposure：

- low tercile；
- middle tercile；
- high tercile。

比较：

- NCO；
- capital；
- allowance；
- loss-to-capital candidate metrics。

---

## 5. 冻结 Research Specification

创建：

`configs/model_specs.yaml`

至少固定：

```text
primary_outcome
primary_segments
primary_cre_exposure
primary_lags
ar_baseline
dynamic_fe_spec
cre_interaction_spec
oos_windows
quantiles
bayesian_core_spec
secondary_hypotheses
```

之后若修改：

`metadata/spec_changes.md`

必须记录：

- 原 specification；
- 新 specification；
- 修改时间；
- 修改原因；
- 是否在看到结果后改变。

---

# Model 0 — Autoregressive Baseline

## 目的

最低 benchmark。

按 segment：

```text
NCO(b,k,t)
=
entity_effect
+
rho × NCO(b,k,t-1)
+
error
```

### 要求

- 与复杂模型使用相同 OOS split；
- 保存 prediction；
- 不能只报告 in-sample fit。

---

# Model 1 — Dynamic Fixed Effects

## 主模型

```text
NCO(b,k,t)
=
alpha(b,k)
+ rho_k NCO(b,k,t-1)
+ theta_k NPL(b,k,t-1)
+ beta_k Macro(t-l)
+ gamma_k BankFeatures(b,t-1)
+ error
```

### Entity Effect

优先：

```text
bank × segment fixed effect
```

### 标准误

优先：

- bank-clustered SE。

可选：

- Driscoll-Kraay。

### 为什么不加完整 Quarter FE

因为全国宏观变量在同一季度对所有银行相同。

如果加入完整 quarter dummy：

- unemployment；
- GDP；
- CRE price；

会被 quarter FE 吸收。

---

## Bias-Corrected FE

### 主 challenger

Split-Panel Jackknife。

实现：

1. full sample FE；
2. first-half FE；
3. second-half FE；
4. 计算 bias-corrected estimate；
5. 对比：
   - lag coefficient；
   - NPL；
   - macro coefficients。

### GMM

仅作为可选 challenger。

如果实现：

- 只用有限 lag；
- collapse instruments；
- 报告 AR(2)；
- 报告 Hansen/Sargan；
- 诊断失败时不进入主结果。

---

# Model 2 — CRE Concentration Interaction

## 目标

区分：

1. CRE 暴露更多导致美元损失更多；
2. CRE 集中度是否额外提高单位 CRE 贷款损失率。

## 模型

CRE-only：

```text
CRE_NCO(b,t)
=
bank_FE
+ quarter_FE
+ lagged risk controls
+ beta × PreShock_CRE_to_Capital(b,t-1)
       × CRE_Price_Shock(t)
+ error
```

### Primary Exposure

优先：

```text
CRE-to-Tier1 Capital
```

Alternative：

```text
CRE Share
```

### 为什么这里可以加 quarter FE

因为：

- 全国 CRE shock 主效应被 quarter FE 吸收；
- interaction 仍通过银行之间暴露差异识别。

---

## 预先规定的 Robustness

1. CRE-to-capital；
2. CRE share；
3. pre-2022 exposure；
4. size controls；
5. bank trend；
6. placebo shock；
7. CRE subclasses：
   - CLD；
   - Multifamily；
   - Nonfarm NR。

---

## 如果 CRE Interaction 不显著

禁止 p-hacking。

按以下顺序处理：

1. 报告 mechanical exposure effect；
2. 正式报告 interaction 无显著证据；
3. 检验预注册 CRE subclasses；
4. C&I × BBB spread；
5. Mortgage × unemployment/HPI；
6. secondary tests 使用 Benjamini-Hochberg FDR。

允许得到的正式结论：

> CRE 风险主要来自暴露规模和资本缓冲，而没有稳定证据表明 concentration 进一步提高单位贷款损失率。

---

## OOS Split

本 Batch 先建立统一 split engine：

1. Train 2005–2011 → Test 2012–2016
2. Train 2005–2016 → Test 2017–2019
3. Train 2005–2019 → Test 2020–2021
4. Train 2005–2021 → Test 2022–2025

实际起点若因数据变化，必须在 config 中更新。

---

## Mean Model Metrics

统一计算：

- RMSE；
- MAE；
- OOS R²；
- bias。

RMSE improvement：

```text
(RMSE_AR - RMSE_Model) / RMSE_AR
```

不得用不同 sample 比较。

---

## 最终输出

```text
data/derived/macro_panel.parquet
data/derived/model_panel.parquet

configs/macro_series.yaml
configs/model_specs.yaml
metadata/macro_release_calendar.csv
metadata/spec_changes.md

outputs/eda/
outputs/models/ar/
outputs/models/dynamic_fe/
outputs/models/cre_interaction/
```

### 必须生成表格

- sample stats；
- segment descriptive stats；
- AR OOS；
- FE OOS；
- FE coefficient table；
- bias-corrected comparison；
- CRE interaction table。

---

## Batch 2 Definition of Done

- [ ] Macro merge 无未来数据泄漏；
- [ ] model spec 已冻结；
- [ ] AR baseline 可以完整 OOS；
- [ ] Dynamic FE 可以完整 OOS；
- [ ] FE 与 AR 使用相同样本；
- [ ] Bias-corrected FE 至少完成一个可靠实现；
- [ ] CRE interaction 模型可以运行；
- [ ] exposure effect 与 interaction effect 分开解释；
- [ ] EDA 能解释主要数据规律；
- [ ] 任何模型失败均有 log，而不是静默删除。

---

## Codex 完成后必须回复

1. 宏观 series 列表；
2. ALFRED / fallback 使用情况；
3. model panel 样本规模；
4. primary specification；
5. AR OOS metrics；
6. FE OOS metrics；
7. bias-corrected 主要差异；
8. CRE interaction 结果状态；
9. 测试结果；
10. 是否可以进入 Batch 3。
