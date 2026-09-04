# MF772 美国区域银行分贷款组合信用压力测试
## Codex 执行计划

> 项目依据：MF772 Final Project Proposal。  
> 核心原则：**核心数据定义、信用损失重构、时间顺序验证和压力测试必须严谨；边缘模块允许使用明确 fallback。**  
> 所有结果数字必须由真实 pipeline 和模型输出生成，不得硬编码或借用 baseline repo 的结果。


# Batch 3 — Tail Models、Hierarchical Bayesian 与统一样本外验证

## 目标

在 Dynamic FE 主模型之外，建立两个高级模型：

1. Quantile Regression / FE-QAR；
2. Hierarchical Bayesian。

然后通过统一 OOS 和 historical pseudo-stress 比较：

- 平均预测能力；
- 尾部风险覆盖；
- 参数稳定性；
- 模型不确定性。

本 Batch 不做 Fed 2026 最终 stress path。

---

# Part A — Quantile Regression

## 1. 核心分位数

只做：

```text
0.50
0.75
0.90
```

不要做：

```text
0.95
0.99
```

原因：有效尾部样本不足。

---

## 2. Core Implementation

优先保证可靠：

- `statsmodels.QuantReg`
- bank-segment dummies；
- segment-specific model；
- 与 Dynamic FE 使用相同 feature set。

模型：

```text
Q_tau[NCO(b,k,t) | X]
=
alpha(b,k,tau)
+ rho(k,tau) NCO(b,k,t-1)
+ beta(k,tau) Macro
+ gamma(k,tau) BankFeatures
```

---

## 3. Stretch：L1-Penalized FE-QAR

若普通 QuantReg 稳定后再实现。

推荐：

- CVXPY；
- quantile loss；
- entity FE 加 L1；
- macro coefficients 不机械统一惩罚；
- lambda 用时间顺序 validation 选。

不得为了追求复杂度破坏主结果。

---

## 4. Tail Metrics

必须实现：

- Pinball Loss；
- empirical coverage；
- interval width；
- Winkler score；
- crisis underprediction count。

### 禁止错误比较

不能说：

> 90% quantile RMSE 高于 FE，所以 quantile 更差。

因为：

- FE 预测 conditional mean；
- quantile 预测 conditional tail。

两者目标不同。

---

# Part B — Hierarchical Bayesian

## 1. 目的

让不同银行共享总体规律，同时保留银行/贷款组合异质性。

重点是 partial pooling，而不是“为了用贝叶斯而用贝叶斯”。

---

## 2. Core Bayesian Spec

优先实现可收敛的模型：

```text
NCO(b,k,t) ~ StudentT(mu, sigma_k, nu)

mu =
segment intercept
+ bank-segment varying intercept
+ segment-specific lagged NCO
+ segment-specific lagged NPL
+ segment-specific macro coefficients
```

### 为什么 Student-t

NCO：

- 有右尾；
- 危机时极值；
- recovery 可能导致负值。

Student-t 比 Normal 更能容忍厚尾。

---

## 3. 第二层扩展

只有 core model 收敛后才加入：

- varying CRE shock slope；
- size-group partial pooling；
- segment × macro varying effects。

---

## 4. 工具

推荐：

- PyMC；
- ArviZ；
- NUTS；
- non-centered parameterization。

---

## 5. Priors

使用弱信息但有经济含义的 prior。

禁止：

- 极宽 prior 导致数值不稳定；
- 看到结果后反复调 prior 直到符合预期。

所有 prior 写入：

`configs/model_specs.yaml`

---

## 6. Bayesian Diagnostics

必须报告：

- R-hat；
- ESS；
- divergences；
- posterior predictive check；
- posterior interval coverage。

### 目标

- R-hat < 1.01；
- 0 divergence 为理想；
- 核心参数 ESS 足够；
- posterior predictive 不出现明显不合理尾部。

---

## 7. Fallback

按顺序简化：

1. 去掉 varying slopes；
2. 仅 varying intercept；
3. 三个 segment 分开；
4. stronger reasonable priors；
5. 降低维度。

若仍不收敛：

- Bayesian 明确标记为 stretch failure；
- 不影响 FE + Quantile 主结论；
- 不得用未收敛 posterior 写结果。

---

# Part C — 统一 Expanding-Window OOS

## 核心窗口

统一使用 Batch 2 已冻结 split。

所有模型必须使用相同数据定义和 test periods。

### Mean Metrics

AR / FE / Bayesian posterior mean：

- RMSE；
- MAE；
- OOS R²；
- bias。

### Tail Metrics

Quantile / Bayesian interval：

- pinball；
- coverage；
- width；
- Winkler；
- severe underprediction。

---

# Part D — Historical Pseudo-Stress

## 目标

检查模型是否只在平稳期表现好。

### Window 1 — GFC

在危机前截断训练集，使用之后真实宏观路径递归预测 2007–2010。

### Window 2 — COVID

预测 2020–2021。

### Window 3 — High Rate / CRE

预测 2022–2025。

---

## 递归逻辑

若模型含 lagged NCO：

1. jump-off 使用真实最后一期 NCO；
2. 预测下一季度；
3. 将 predicted NCO 作为下一期 lag；
4. 使用实际宏观路径；
5. 持续到窗口结束。

---

# Part E — Model Comparison

最终比较：

```text
AR
Dynamic FE
Bias-Corrected FE
Quantile 50/75/90
Hierarchical Bayesian
```

Optional：

```text
GMM
```

暂不优先：

```text
LightGBM
NGBoost
```

只有以上模型全部稳定后才考虑额外 ML。

---

## 输出

```text
outputs/models/quantile/
outputs/models/bayesian/
outputs/validation/oos_predictions.parquet
outputs/validation/pseudo_stress.parquet
outputs/validation/model_comparison.csv
outputs/validation/tail_metrics.csv
```

---

## 必须生成图

1. FE mean vs actual NCO；
2. 75/90% quantile bands；
3. Bayesian posterior predictive interval；
4. GFC pseudo-stress；
5. COVID pseudo-stress；
6. 2022+ pseudo-stress。

---

## Batch 3 Definition of Done

- [ ] 0.50/0.75/0.90 quantile 可运行；
- [ ] tail metrics 完整；
- [ ] Bayesian core model 达到可接受收敛，或明确 fallback；
- [ ] 所有模型使用统一 OOS；
- [ ] GFC/COVID/2022+ pseudo-stress 可重现；
- [ ] quantile 没有被错误用 RMSE 判定；
- [ ] Bayesian 结果包含 diagnostics；
- [ ] model comparison 自动生成；
- [ ] 没有手工挑最好窗口。

---

## Codex 完成后必须回复

1. quantile 模型规格；
2. quantile tail metrics；
3. Bayesian 模型规格；
4. R-hat / ESS / divergence；
5. 每个模型 OOS 指标；
6. pseudo-stress 结果摘要；
7. 哪个模型用于 mean forecast；
8. 哪个模型用于 tail forecast；
9. 未解决问题；
10. 是否进入 Batch 4。
