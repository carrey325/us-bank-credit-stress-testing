# MF772 — 勘误、必要补齐与重新验收总控

版本：Repair Cycle v1（建议方案，尚未在 GitHub 执行）
基准：规划时读取的 main 为 `09e036b827463d915990f423941b6bff5c3349b0`。
启动时必须重新核对 HEAD，不能覆盖该提交之后用户的新修改。

## 1. 本轮采用什么组织方式

保留原 Batch 1–5 作为模块职责和历史实施记录。新增 R1–R4 作为本轮的增量执行任务，而不是新增功能型 Batch 6–9，也不是重建一个新的 bankstress 系统。

| 修复任务 | 原模块 | 本轮性质 |
|---|---|---|
| R1 — 数据定义与面板修复 | Batch 1，必要的公共运行入口 | 官方字段复核、修复、数据重建、旧结果失效标记 |
| R2 — 宏观、核心模型与 CRE 复验 | Batch 2 | 修复后原规格重估、时间口径检查、有限诊断 |
| R3 — 尾部与历史验证修复 | Batch 3 + Batch 5 Part A | 区分预测目标、补齐公平基准、限制递归解释 |
| R4 — 压力结果与最终交付 | Batch 4 + Batch 5 其余交付部分 | 只使用本轮允许用途的模型重建压力结果与报告 |

严格串行：`R1 → R2 → 研究范围复核 → R3 → R4`。

必须区分：代码需要局部修复；所有受上游变化影响的派生数据、模型、误差、区间、分组、压力结果和报告都需要重建。代码没改，不等于旧输出仍可用。

## 2. 与原计划的关系

本轮是对原五份计划的显式勘误和范围收缩。未列出的数据真实性、唯一键、负 NCO、时间顺序、来源记录、禁止硬编码等要求继续有效。

正式启动前，在 AGENTS.md 增加简短 Repair Cycle 入口，并修正其 `plan/` 与实际 `workflow/` 路径不一致问题。入口列出本轮 R1–R4 的跨模块授权范围；不把整个旧文件重写一遍。旧五份任务文档保留，只加“本轮执行入口见 workflow/repair/00_Repair_Control.md”的短说明。

本轮对旧条款的替换：

- 原 Batch 1 的字段存在性和公式自洽检查，补强为“监管含义、组件完整性、分子分母范围一致性”的独立证据检查。
- 原 Batch 2 的已冻结研究目标继续保留。实现错误需要修复；任何实质规格变化都必须记录，不把看过结果后的修改称为事前预注册。
- 原 Batch 3 的固定 Q90 逐期反馈不再默认获得“多期预测分位数”身份。没有多期分布验证，不发布累计损失 Q90。
- 原 Batch 3 的 Bayesian 在本轮明确延后。不得删除已有代码或假装已收敛。
- 原 Batch 4 不再要求所有计划模型都必须产生排名。仅使用 R3 用途清单准许的模型；没有合格模型时生成限制报告，而不是强行给出正式排名。
- 原 Batch 5 的外部市场验证、LightGBM、NGBoost、virtual bank、文本和地理扩展在本轮延后。保留 deferred 原因。
- 任何“RMSE 必须下降、交互项必须显著、危机漏报必须减少”的预期都不能作为工程完成的必要条件。方法、计算和评价正确才是完成条件。

这不是认可原预测效果，而是避免为了符合预期结果修改数据和方法。

## 3. 两类状态必须分开

任务状态：`PENDING / RUNNING / WAITING_REVIEW / COMPLETE / BLOCKED`。

研究结论状态：`SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE / NOT_EVALUATED`。

任务可以正确完成而假设不获支持。任务不能因为结果漂亮而跳过方法或数据失败。`COMPLETE` 也不自动等于获准发布压力排名。

模型用途由 R3 单独记录：是否可用于历史描述、一步均值预测、一步尾部预测、条件均值压力路径、多期尾部分布。不得用一个笼统的“approved”代替用途。

## 4. 最小工作流修改，不建设第二套平台

使用现有仓库和同一开发分支串行继承前一阶段提交，不为串行任务创建多个独立 worktree。需要隔离时，最多在开始时建立一个修复分支；不自动切换或丢弃用户现有分支。

保留 `workflow/state.json` 的旧建设历史。新增一份 `workflow/repair/repair_state.json` 记录本轮状态，让 Scheduler 显式读取它，而不是依据旧的 Batch 5 COMPLETE 判断整个修复已完成。

复用原 Router/Worker 模式。以本轮 stage_files 和 state_path 启动，不复制整个调度框架。AGENTS、Router、Worker 的入口和完成状态名称应在 R1 预检时对齐；找不到计划文件或存在规则冲突时，报告具体冲突，不自行猜测。

建议 repair_state 只保存：cycle_id、base_commit、current_stage、status、active_worker_id、input_run_id、checkpoint_commit、review_status、blocker、next_action。不要新建数据库或通用工作流引擎。

## 5. 开工保护与输出失效

R1 开始先执行 git 状态、输入文件、现有 Worker 和长任务检查。保护无关更改，不重写历史，不自动强制 reset/clean。

旧结果用基准 Git 提交定位。未提交且将被覆盖的数据或模型文件，先在 Git 忽略的本地目录保存清单与必要快照，或明确记为无法恢复。不能假装有旧预测 parquet。

raw 输入按现有 manifest/hash 尽量复用。修复不等于重新下载所有季度最新修订文件。需要恢复或补数据时单独记录新来源和版本；不能把 raw 版本变化和代码修复的影响混为一谈。

R1 尽早给旧结果设置 `INVALID_PENDING_REBUILD` 状态，并在 README 加临时说明。旧 PDF、表格和简历指标不得继续被作为本轮有效结果引用。旧文件可留作审计，不得悄悄当作新上游输入。

所有新关键产物有 sidecar/manifest，至少记录：

```text
run_id
stage
code_commit（运行时的提交）
code_tree_hash_or_dirty_diff_hash（若尚未提交）
input_artifact_hashes
raw_manifest_hash
field_mapping_hash
data_definition_version
model_spec_hash（适用时）
created_at
validation_status
```

只实现轻量元数据校验并接入现有入口，不重构整个目录系统。下游发现旧版或未验证输入必须拒绝生成正式结果。R4 增加故意混入旧模型/旧区间的回归测试。

## 6. 阶段边界和复核规则

每个阶段一个 Worker。同一时间只允许一个 Writer；下一阶段读取前一阶段已完成、已提交的成果。

每个阶段实现基本完成后最多一次正式最终 Reviewer。Reviewer 检查证据、方法与测试，不仅检查文件是否存在。修复本阶段范围内意见，再运行相关测试；本阶段仍有关键未决问题则 BLOCKED，不为获得 COMPLETE 放宽门槛。

下游发现上游问题，登记 issue，暂停依赖结果，再回到责任阶段做有编号的补修 checkpoint。不得让 R4 私自修映射后只重跑报告。上游产物变化后，所有依赖产物重新失效。

不要假设 Worker 创建成功就已运行。必须记录运行环境返回的可查询 task/thread ID；ID 未注册时先检查现有任务，不能并行反复创建。当前运行环境不支持自动调度或 Reviewer 调用时，按相同顺序手工交接，不能伪造任务或审查记录。默认不启用 Automation/heartbeat。

Worker 最终交接模板：

```text
Rk STATUS: COMPLETE / BLOCKED
Base Commit:
Changed Files:
Issues Closed / Still Open:
Input Run / Hashes:
Validation Commands and Actual Results:
Research Result Status:
Permitted Downstream Uses:
Invalidated or Regenerated Artifacts:
Reviewer Disposition:
Commit:
Next Action:
```

## 7. 对照实验原则

尽量保留三个层次，不能混写“修复让模型提升了 X%”：

1. OLD：基准提交下已保存的旧结果，仅用于定位问题，明确已失效。
2. DATA_FIXED_SAME_SPEC：在修正数据上重跑原模型公式与窗口，隔离数据修复影响。若继承旧实现缺陷，只能标为诊断回放。
3. VALID_CORRECTED：修正必需的时间、计算、评价错误后，形成当前可解释基线；额外简化规格另标探索，不混入基准。

样本变化单独拆解：共同样本的差异和新有效样本的差异分别报告。因目标定义修正，旧新 RMSE 不是同一个目标上的公平预测竞赛。

## 8. 投入上限与停止机制（建议）

建议先投入 R1、R2，再检查是否继续完整版验证，而不是一次命令无限续做所有扩展。

| 阶段 | 建议有效工作预算 |
|---|---:|
| R1 | 5–8 小时 |
| R2 | 3–5 小时 |
| R3 | 2–4 小时 |
| R4 | 2–3 小时 |
| 合计 | 12–20 小时 |

预算是投入上限建议，不是完成保证，不含无人值守下载/计算等待。即将超额先汇报，不通过降低数据要求挤进预算。

R2 后的决策：

- 数据和方法可靠，结果有解释：进入 R3，完成有限尾部验证，再 R4。
- 数据可靠，但模型没有稳定增益：缩减 R3 到必要尾部评价和用途标记，再 R4 收尾。不得靠增加模型追逐显著性。
- 主要数据口径仍未解决：BLOCKED，返回 R1 或提出明确范围缩减，后续阶段不使用问题数据。

没有受支持的核心结果时，可以完成诚实的基准比较和局限报告；不能保证会产生原创发现。范围、样本或目标的大幅修改须由用户确认。

## 9. 本轮明确延后的内容

Bayesian 环境与采样扩建、LightGBM/NGBoost、完整 FE-QAR 多步密度模拟、自动搜参、全面扩充银行样本、virtual bank 重建、证券市场验证、SEC NLP、地理数据、完整 CET1/PPNR/RWA 系统。

Mortgage：保留并验证原有历史数据，不把缺失填零。本轮核心模型先维持已冻结 CRE/C&I；新增 Mortgage 正式 stress 模型不是默认任务。CRE 子项用于数据核对和已有的有限敏感性，不自动发展成多个新研究。

## 10. 输入材料与证据说明

以下是本方案的依据，不代表所有旧规格或旧结果已经验证：

- 用户上传的五份 Batch Markdown 文件，其结构分别对应数据、宏观和均值模型、尾部与验证、Fed 压力、最终交付。
- 仓库 `AGENTS.md`、`workflow/project_config.yaml`、`workflow/router_prompt.md`，读取基准为上述提交。
- 上一轮检查发现的 CRE 映射问题，在 R1 必须落实为可复核的证据记录和失败测试，不把聊天结论直接当完整生产映射。
- FFIEC 2009Q2 041 原表 PDF 第 20、22 页，分别显示有房地产担保建设贷款项目和 2746 备忘项目。
- FFIEC 2005Q3 041 原表 PDF 第 17 页，列示 1415、1460、1480 等房地产贷款余额项目。
- Covas、Rump、Zakrajšek 的 Fed 2013-55 论文，用于区分一步分位数与多步密度预测。

官方证据入口（这两份 041 原表不代表已覆盖 031 或全部切换日期）：

```text
https://www.ffiec.gov/sites/default/files/data/reporting-forms/hv-041/FFIEC041_200906_f.pdf
https://www.ffiec.gov/sites/default/files/data/reporting-forms/hv-041/FFIEC041_20050930_f.pdf
https://www.ffiec.gov/resources/reporting-forms
https://www.federalreserve.gov/pubs/feds/2013/201355/index.html
```

## 11. 可交给 Scheduler 的启动指令

> 在现有 MF772 仓库中执行 Repair Cycle。先完整阅读本文件和 AGENTS.md，并检查当前 HEAD 与未提交更改。保留原 Batch 1–5 的代码和历史记录，不从零重建。以 R1→R2→R3→R4 串行执行，使用同一开发分支，每阶段独立 Worker、最多一次最终 Reviewer、一个清晰 checkpoint。先只启动 R1，R1 验收后再 R2；R2 完成后提交范围决策，未经确认不扩大研究。旧结果在重建验证前保持失效，任何缺失证据、未通过用途校验的模型或未知输入版本不得被包装成正式结果。你的职责是调度和交接，不是替 Worker 编写研究代码。
