# MF772 美国区域银行分贷款组合信用压力测试
## Codex 执行计划

> 项目依据：MF772 Final Project Proposal。  
> 核心原则：**核心数据定义、信用损失重构、时间顺序验证和压力测试必须严谨；边缘模块允许使用明确 fallback。**  
> 所有结果数字必须由真实 pipeline 和模型输出生成，不得硬编码或借用 baseline repo 的结果。


# Batch 1 — 数据工程与 Core Credit Panel

## 目标

从零建立可重复运行的数据工程管道，最终产出可信的 `bank × loan segment × quarter` 核心信贷面板。

本 Batch 不追求模型结果。唯一目标是证明：

1. 银行样本定义合理；
2. FFIEC Call Report 原始数据可以稳定下载和解析；
3. 监管字段跨年份可以正确映射；
4. YTD 核销/回收可以正确季度化；
5. CRE、C&I、Mortgage 的真实 quarterly NCO 可以重构；
6. 并购、缺失、单位、字段版本和异常跳跃受到控制；
7. 数据质量可以通过 reconciliation 和 manual audit 验证。

---

## 1. 建立仓库骨架

建议结构：

```text
mf772-bank-credit-stress/
├─ README.md
├─ pyproject.toml
├─ requirements.txt
├─ Makefile
├─ configs/
│  ├─ project.yaml
│  └─ sample.yaml
├─ data/
│  ├─ raw/
│  ├─ standard/
│  ├─ derived/
│  └─ manifests/
├─ metadata/
│  ├─ field_mapping.csv
│  ├─ institutions.csv
│  ├─ institution_lineage.csv
│  └─ exclusion_log.csv
├─ src/bankstress/
│  ├─ io/
│  ├─ metadata/
│  ├─ transform/
│  └─ qa/
├─ scripts/
├─ tests/
└─ outputs/qa/
```

### 必须实现

- 所有路径由 config 控制；
- raw 数据不进 Git；
- raw 文件保存 SHA-256；
- 所有 pipeline 可以重复执行；
- pytest 可运行；
- 不允许在代码中硬编码最终样本规模或结果数字。

---

## 2. 银行样本宇宙

### 主方法

使用 FDIC institution/history 数据建立候选银行池。

### 初始筛选

优先：

- 美国 FDIC-insured bank legal entity；
- 传统贷款/存款型银行；
- 资产约 10B–250B USD；
- 至少 40 个季度历史；
- 优先使用 FFIEC 031 / 041；
- 历史失败、退出、被并购银行可保留用于估计；
- 最终 2026 stress ranking 只针对 2025Q4 仍活跃银行。

### 排除

核心模型不与以下特殊业务银行混用：

- pure credit-card；
- auto finance；
- custody；
- broker-dealer / trading dominant。

### 输出

`metadata/institutions.csv`

最低字段：

```text
bank_id
cert
rssd_id
bank_name
parent_name
assets
form_type
first_report_date
last_report_date
active_2025q4
failed_flag
acquired_flag
specialized_business_flag
core_sample_flag
exclusion_reason
```

### 验收

- 目标：30–40 家 core banks；
- 候选池可以大于 40；
- rejected banks 必须保留 reason。

### Fallback

若不足 30 家：

1. 资产上限放宽至 300B；
2. 最低连续季度降至 32；
3. 仍不足时接受 25–30 家；
4. 不得为了凑数量混入特殊业务银行。

---

## 3. 下载 FFIEC Call Report Raw Data

### 主方法

FFIEC quarterly bulk files。

### Pilot

先下载并解析：

- 2005Q1；
- 2009Q4；
- 2020Q2；
- 2025Q4。

确认格式稳定后再下载完整 2005Q1–2025Q4。

### Raw 保存规则

每个文件记录：

```text
source_url
download_timestamp
file_name
sha256
report_period
version
```

原始文件永不覆盖。

如果同季度有 amendment / regenerated version：

- 新版本另存；
- manifest 记录版本；
- 不覆盖历史 snapshot。

### 输出

`data/raw/ffiec/`
`data/manifests/ffiec_manifest.csv`

### QA

- 季度是否缺失；
- 文件是否可解压；
- 机构数是否异常；
- 字段文件结构是否出现断点。

---

## 4. 建立版本化监管字段字典

这是本 Batch 最关键的工作之一。

### 主方法

结合：

- FFIEC instructions；
- MDRM；
- XBRL taxonomy；
- Covas et al. 附录字段作为 seed。

### 绝对禁止

不能把某一年的字段代码无条件用于 2005–2025 全时期。

### 核心指标

#### Exposure

- CRE:
  - Construction & Land Development；
  - Multifamily；
  - Nonfarm Nonresidential。
- C&I；
- Residential Mortgage。

#### Loss Flow

- segment charge-offs；
- segment recoveries；
- total charge-offs / recoveries。

#### Credit Quality

- segment NPL/noncurrent；
- total NPL。

#### Capital / Buffer

- allowance / ACL；
- total loans；
- total assets；
- Tier 1 capital；
- RWA；
- ROA / PPNR candidate fields。

### `field_mapping.csv`

必须包含：

```text
raw_code
standard_metric
segment
schedule
form
start_date
end_date
stock_flow
ytd_flag
unit
formula_group
source_reference
source_url
qa_rule
notes
```

### 验收

- 至少 40 个原始监管字段；
- CRE/C&I/Mortgage 的 exposure、charge-off、recovery 可以构造；
- 每个字段有 source 和有效日期；
- 对 2005 / 2010 / 2020 / 2025 至少做一次字段存在性验证。

### Fallback

若 segment NPL 跨期不稳定：

- NCO 仍为主 outcome；
- total NPL 作为 bank-level leading indicator；
- missing 不得填 0。

---

## 5. Standard Layer

### 目标

把不同季度不同格式转成统一长表，但不计算研究指标。

### Schema

```text
bank_id
report_date
form
raw_code
standard_metric
raw_value
numeric_value
unit
source_file
source_version
mapping_version
```

### 输出

建议：

`data/standard/call_report_standard.parquet`

或 partitioned Parquet：

```text
/year=YYYY/quarter=QX/
```

### QA

- 唯一键；
- 数值类型；
- 单位；
- form mismatch；
- 字段突然全缺失；
- 重复 bank-date-metric。

---

## 6. YTD → Quarterly Flow

### 规则

对于年初至今累计流量：

```text
Q1 quarterly = Q1 YTD
Q2 quarterly = Q2 YTD - Q1 YTD
Q3 quarterly = Q3 YTD - Q2 YTD
Q4 quarterly = Q4 YTD - Q3 YTD
```

跨年必须 reset。

### 特殊情况

- 前一季度缺失：返回 missing + reason；
- YTD 下降：
  - 保留差分值；
  - `amendment_or_reclass_flag = 1`；
  - 不自动清零。
- recovery > charge-off：
  - NCO 可以为负；
  - 不视为错误。

### 单元测试

必须覆盖：

1. 正常 Q1–Q4；
2. 跨年 reset；
3. Q2 缺 Q1；
4. YTD 向下修订；
5. recovery > charge-off；
6. 负季度 NCO。

---

## 7. 重构真实 Quarterly NCO

### 公式

```text
Quarterly NCO
= Quarterly Charge-Off
- Quarterly Recovery
```

```text
Average Exposure
= (Exposure_t-1 + Exposure_t) / 2
```

```text
Quarterly NCO Rate
= Quarterly NCO / Average Exposure
```

```text
Annualized NCO Rate
= Quarterly NCO Rate × 4
```

### 构造指标

- segment_nco；
- segment_nco_rate；
- segment_npl_rate；
- cre_share；
- cre_to_tier1；
- allowance_coverage；
- tier1_ratio；
- loan_growth；
- lagged_nco；
- lagged_npl。

### Small Exposure

小暴露记录：

- 保留；
- 标记 `eligible_for_model = 0`；
- 不从 derived data 中完全删除。

---

## 8. 并购和断点处理

### 主方法

使用 FDIC history / structure events：

- 标记 merger quarter；
- 检测资产/贷款/资本异常跳跃；
- 默认排除 merger quarter；
- 可选排除前后各 1 个季度；
- 保留前后正常时期；
- 生成 `merger_recent_flag`。

### Challenger

Virtual bank reconstruction。

### Fallback

若 lineage 太复杂：

- 不做 virtual bank；
- 只排除明显并购断点；
- 限制到连续性更好的银行。

---

## 9. Reconciliation 与 Manual Audit

### Loan Reconciliation

如果已经映射完整贷款树：

```text
sum(all segment exposures)
≈ reported total loans
```

如果只做 CRE/C&I/Mortgage：

- 不强制三类等于总贷款；
- 报告 `covered_share_of_total_loans`。

### NCO Reconciliation

```text
sum(all mapped segment NCO)
≈ reported total NCO
```

### Capital Reconciliation

```text
Tier1 Capital / RWA
≈ reported Tier1 Ratio
```

### Manual Audit

随机 100–200 条：

```text
bank
quarter
segment
raw field
raw value
formula
derived value
pass/fail
reviewer note
```

---

## 10. 最终输出

必须产出：

```text
metadata/institutions.csv
metadata/institution_lineage.csv
metadata/field_mapping.csv
metadata/exclusion_log.csv

data/standard/call_report_standard.parquet
data/derived/credit_panel.parquet

outputs/qa/data_quality_report.md
outputs/qa/reconciliation_summary.csv
outputs/qa/manual_audit.csv
```

---

## Batch 1 Definition of Done

进入 Batch 2 前必须满足：

- [ ] core sample 至少约 25–30 家银行；
- [ ] CRE/C&I/Mortgage 均有可用 exposure；
- [ ] charge-off/recovery 已正确季度化；
- [ ] 真实 NCO 已重构；
- [ ] negative NCO 没被错误删除；
- [ ] merger quarter 已标记；
- [ ] field mapping 有版本日期；
- [ ] manual audit 未发现系统性公式错误；
- [ ] data quality report 可重复生成；
- [ ] 不存在明显 bank ID 错配。

### 硬性停止条件

出现任意以下情况，不得开始模型：

- YTD 没有正确季度化；
- 跨年份字段含义不明；
- 缺失值被填 0；
- 并购造成的跳跃未处理；
- 主要 segment NCO 无法与监管总量解释。

---

## Codex 完成后必须回复

1. 修改文件列表；
2. 新增/删除文件；
3. 数据源和下载季度；
4. core bank 数量；
5. field mapping 字段数量；
6. derived observation 数量；
7. reconciliation 数字；
8. pytest 结果；
9. 已知问题；
10. 是否建议进入 Batch 2。
