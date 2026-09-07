# R3 — 尾部目标、历史递归与区间校准修复

前置：R2 COMPLETE，研究范围复核已决定继续完整或最小验证。
阅读：总控、原 Batch 3、原 Batch 5 Part A、R2 时间合同与结果。

## 1. 范围与默认路线

复用 `validation.py`、相关配置/测试，以及现有区间计算函数。原项目若将区间算法放在 reporting.py，本阶段可限定修改算法部分，但不提前重写最终报告。

默认保留一步 Q0.50/Q0.75/Q0.90、历史均值模型递归，以及一套明确标记的 residual-calibration fallback。Bayesian 暂不修环境或重新采样，保留原代码及“本轮延后”的状态。

不建设完整 FE-QAR 多期密度模拟，不估计 Q0.95/Q0.99，不加入新 ML 家族。

## 2. 给每个预测对象正确命名

必须区分：

1. 一步条件均值。
2. 一步 Q90 上侧分位：名义超越率 10%。
3. 一步 Q50–Q90 band：名义区间概率 40%，不是 90% 双侧预测区间。
4. 基于残差校准的双侧 90% 预测区间：与 Q90 单侧上界分开评价。
5. 给定宏观路径的均值模型递归点路径。
6. 多期累计损失分布的 Q90。

对象 6 不能由“每个季度喂入上季 Q90，再把各期预测相加”自动得到。原固定分位递归实现可保留作 `recursive_quantile_sensitivity`，但不得标为已校准多期尾部分布，不能作为正式 tail ranking 的依据。

在一般非线性处理、负值 floor 或多期分布问题中，也不能无证明把某条插件式点路径称为精确条件期望。

## 3. 一步分位数的公平比较

重估原三个分位数，使用 R2 的有效输入、时间窗口与共同评分样本。保存拟合收敛信息、crossing 数量及处理前后的预测。若重排分位数，明确记录，不能用重排掩盖不稳定拟合。

给每个 tau 增加一个简单尾部基准：默认使用同 tau 的 AR-only quantile（保留相同实体处理与滞后 NCO），若不可稳定估计则用仅依赖过去数据的历史/残差分位基准并标明差异。复杂 Q90 只与同目标基准比较，不以 mean RMSE 判断。

分别报告 pinball、超越次数/率、分期与分组合指标。Q90 目标为 10% 超越，不是“越少越好”。0% 超越可能来自过宽或过高预测，不应直接写成成功。

## 4. 历史 pseudo-stress 先保证路径正确

继续使用原 GFC、COVID、高利率/CRE 窗口，不删掉表现差的窗口。显式输出每个窗口的训练季度数、银行数、特征数和有效样本。早期 GFC 训练期短时标注局限，不能把跨银行行数当大量独立宏观时点。

从 jump-off 的有效历史状态开始，每季度都生成路径；未来真实 NCO 或控制变量缺失不应导致整条路径“跳过一个季度”。银行控制变量按事先定义冻结或以获准模型生成，不能回填真实未来值。

将预测生成和实际结果评分分开；只在评价层对齐已有真实值。原字段修复引起的缺失不是填值理由。

对均值模型比较一步与多步误差、累计 modeled loss 误差（余额假设相同），分解是否由初值、长期均值、特征或递归不稳定造成。仅通过一步评估的模型不能自动获准九季度用途。

## 5. 区间层使用一个有限、可解释的 fallback

本轮默认比较 static residual calibration 与 rolling residual calibration，不因原计划写了 Adaptive Conformal 就冒充其理论保证。

开始前固定 calibration seed period、窗口长度、更新频率、残差定义、分组规则。只使用在本次 forecast_origin 之前已经观察到目标的残差；“之前发出的预测”不等于其误差已经可知。

同一季度多个银行的误差可能共享冲击；若使用 bootstrap，按时间块并尽可能保留同季度横截面结构，不随机打乱所有 bank-quarter 行。训练、校准、评分对象和缺失处理保持一致，不能每个方法选择不同的好样本。

记录 empirical coverage、interval width、适合该区间定义的 interval/Winkler score、上侧 miss 次数与率、对应实际有效 n。对 nominal 90% 区间比较覆盖和宽度的取舍，不以减少 miss 为唯一目标。

“95% 覆盖”是本样本经验结果，不是危机期覆盖保证。校准在给定历史数据中失败或无增益可以成为研究结果，前提是实现正确。

## 6. 单独输出模型用途清单

在 `outputs/validation/model_use_registry.json` 为每个 model × segment 记录：

```text
model_id
segment
input_run_id
model_spec_hash
descriptive_use
one_step_mean_use
one_step_tail_use
conditional_mean_stress_use
multi_step_tail_distribution_use
evidence_files
limitations
status_reason
```

取值明确为允许、仅诊断、不可用，并给原因。模型选择和用途判断依据 R2/R3 中预先写清的相关诊断；不能只因它叫“预设 structural model”就自动放行。

均值 stress 用途不强制必须打败 AR，但要求字段/时序正确、路径数值稳定、情景特征口径一致、相关历史验证和限制有证据。没有合格用途时写不可用，R4 按限制版交付。

C&I 表现较好不能替 CRE 放行。一步 Q90 通过也不能替多期 tail distribution 放行。

## 7. 最小测试与输出

测试覆盖：各预测目标/名义覆盖标签、分位交叉、实际结果超越计数、残差只有到期后可用、季度块边界、递归路径跨缺失实际值仍连续、future bank controls 不泄漏、禁止固定 Q90 反馈被打上累计 Q90 标签。

正式输出复用原 validation 与 model_risk 路径，附本轮版本信息；另外输出：

```text
outputs/repair/r3/prediction_target_dictionary.md
outputs/repair/r3/validation_limitations.md
outputs/validation/model_use_registry.json
```

完成声明必须说明哪些结果只是诊断、哪些用途获准、哪些模型延后。不要以方法名字或旧的 coverage 数字代替证据。

若用户在 R2 后决定快速收尾，R3 仍需完成正确的一步尾部评价、最小递归检查和用途清单，可以不追加校准实验。将未做项目写为 NOT_EVALUATED，不伪装为方法失败。
