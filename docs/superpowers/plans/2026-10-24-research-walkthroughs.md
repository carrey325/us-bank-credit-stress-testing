# US Bank Credit Stress Testing：三篇研究导读 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL（如环境可用）：使用 `superpowers:executing-plans` 逐项执行；也可使用 `superpowers:subagent-driven-development`，但共享 helper 和最后验收须顺序完成。若没有这些技能，直接依本文件清单实施，不以安装插件为前置条件。步骤用复选框记录。

**Goal:** 为 `carrey325/us-bank-credit-stress-testing` 增加恰好三篇短而完整、可从干净内核执行的英文研究导读 notebook，让读者理解数据定义、模型比较与压力情景的证据边界。

**Architecture:** 保留现有 `src/bankstress/`、历史回放门控和已发布结果。Notebook 负责问题、公式、少量可执行例子、图表和解释；计算复用现有函数，仅在必要时增加很薄的教学输入/读取 helper。历史结果从已提交证据读取，缺少公开上游输入的机制用独立、显著标记的合成例子解释。

**Tech Stack:** Python 3.11+、现有 pandas/NumPy/matplotlib/bankstress；可选 notebook 执行依赖 `nbformat`、`nbclient`、`ipykernel`、`nbconvert`。

**Spec:** 本文件第 1–4 节是完整任务规格，不依赖另一份设计文档。范围已由用户确认；Codex 收到“执行本计划”后直接按清单推进，不需要重新询问是否采用这三个主题。本文件交付时尚未实施，也没有预先通过文中的验收命令。

**建议存放位置：** 实施时可将本文件加入仓库 `docs/superpowers/plans/2026-10-24-research-walkthroughs.md`，作为本次修改的执行记录。

## 1. 仓库基线与已知事实

- 审阅仓库：https://github.com/carrey325/us-bank-credit-stress-testing
- 审阅 HEAD：`22886c1d98c21fba191f1ebb1e538825094e8279`。
- 执行时仓库可能已更新：读取当前 `AGENTS.md`、README、相关文档和差异，再适配本计划；不要 reset 到审阅提交。
- 当前公开交付支持证据快照校验，不支持从干净 checkout 完整重跑历史研究链；不得把新导读包装成这一问题已经解决。
- 审阅期间 `python scripts/export_results.py --verify` 成功；当时 pytest 因环境缺少 pytest 未执行，因此不得把历史测试数写成本次实测数。

实施前阅读以下实际源码与文档；链接固定到审阅版本，定位规则以执行时源码为准：

| 内容 | 已核查的入口 |
|---|---|
| 当前研究结论、模型边界 | [README](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/README.md) |
| 数据口径、时点、缺失值 | [docs/data.md](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/docs/data.md) |
| 快照校验与完整回放的区别 | [docs/reproduction.md](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/docs/reproduction.md#L66-L99) |
| 年初重置、相邻季度、报表口径 | [quarterize_ytd](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/src/bankstress/transform/flows.py#L6-L34) |
| 完整组件、平均余额、年化 NCO | [build_credit_panel](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/src/bankstress/transform/panel.py#L182-L268) |
| 已保存的源文件审计摘录 | [metadata/manual_source_audit.csv](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/metadata/manual_source_audit.csv) |
| 同样本 AR/FE 比较 | [run_oos_models](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/src/bankstress/modeling.py#L174-L218) |
| Pinball loss、重排、同分位数比较 | [tail_validation.py](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/src/bankstress/tail_validation.py#L96-L248) |
| 通用递归机制与年度率转季度损失 | [recursive_stress_paths](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/src/bankstress/stress.py#L315-L391) |
| 正式历史路径的模型集合与汇总定义 | [recursive_r4_paths / _summarize_r4](https://github.com/carrey325/us-bank-credit-stress-testing/blob/22886c1d98c21fba191f1ebb1e538825094e8279/src/bankstress/stress.py#L715-L801) |

## 2. Global Constraints

- 仅本仓库；新增恰好三篇研究导读，不扩展到其他项目。
- 所有新增研究正文、图表标签、docstring 和代码注释均用简洁自然的英文；本执行计划用中文。
- 每篇目标为约 600–900 英文词、12–20 个紧凑单元格、1–2 幅必要图表；这是可读性目标，不是机械凑数门槛。
- 每篇独立包含：研究问题、经济理由、证据来源与范围、方法/公式、可执行检查、结果解释、局限和下一篇链接。
- 不增加 Bayesian 拟合、模型重训、样本宇宙重建、幸存者偏差修复、外部大下载或新的经验结论。
- 不改模型规格、历史门控、数据定义、快照、provenance、已发布数字；不把图表重排当成新的研究发现。
- 不制造历史原始报表、相邻贷款余额、真实银行参数、观测级预测或逐季度压力路径。
- 默认离线执行；不得把联网取数、API key、私有缓存或 `outputs/` 历史中间产物作为导读依赖。
- 核心算法调用现有 `src` 接口；单元格可以表达公式和透明的筛选/聚合，但不能再实现一套季度化、估计器或递归模型。
- 保留用户改动；在隔离分支/worktree 实施。完成后可在该分支提交，未经另行授权不 push、不 merge。

## 3. 证据分层与三个 notebook 的规格

### 3.1 所有导读共用的证据标签

| 英文标签 | 可用于什么 | 不得声称什么 |
|---|---|---|
| `Recorded source-audit excerpt` | 读取现有审计 CSV 的字段值、源档案/member、审计结论；重算其能支持的算术 | 本次重新读取并验证了原始 FFIEC archive |
| `Committed research evidence` | 从 `results/evidence/` 重算汇总、比较和已保存统计 | 重新拟合了模型或独立验证了缺失的逐观测预测 |
| `Synthetic demonstration` | 明确虚构的银行、参数、余额、情景，用来解释机制和边界条件 | 真实银行数据、官方情景数据或已发表研究结果 |

- 每篇首段标明使用哪些证据；合成图表标题/表格 caption 必须含 `Synthetic demonstration`。
- 三类证据不得拼成同一条虚构的“真实银行原始数据到最终预测”链。
- 所有经验数字由当前证据动态算出；必要时与 `results/summary.json` 对照，不手抄四舍五入数字作为数据源。

### 3.2 Notebook 1：From Call Reports to Annualized Credit Losses

交付：`notebooks/01_call_reports_to_credit_losses.ipynb`。

- 问题：为什么同一笔季度信用损失会因 YTD、报表口径、分母和缺失处理而被算错？
- 用 `metadata/field_mapping.csv` 与审计摘录展示字段、金额单位、stock/flow、原始代码和源文件 lineage。
- 优先使用审计记录中 `bank_id=12311`、`report_date=2007-12-31`、`segment=CRE` 这一已存在记录；执行时先核对键仍存在且唯一。
- 若该记录不再存在，选择并明确记录另一条完整、可解析记录；不得悄悄保留旧值或编造替代记录。
- 只从该记录保存的 `current_ytd`、`prior_ytd` 和档案季度恢复季度化输入，调用 `quarterize_ytd` 重算 charge-offs、recoveries、NCO，与保存的审计总量相核对。
- 审计 CSV 未提供可靠的相邻贷款余额；它不能单独支持真实历史年化率，也不能凭猜测补 filing form。
- 年化率的完整演示另用虚构银行 `DEMO_CI` 和明确的 041 口径，构造最小标准化输入，调用 `build_credit_panel`。
- 解释公式 `annualized NCO = 4 × (quarterly charge-offs − recoveries) / average adjacent-quarter exposure`；decimal、percent、USD thousands 分开标注。
- 展示至少四种机制：Q1 年度重置；正常 Q2 差分；缺少相邻季度时保持缺失；031/041 口径变化不可跨边界差分/取平均。
- 解释负 NCO 被保留、组件不完整不能当作零；可复用现有测试中的小例子，不能冒充实证样本。
- 结尾指出：审计摘录支持有限原始字段算术，合成演示支持代码行为说明，均不等于重建全部历史面板。

### 3.3 Notebook 2：What the Benchmarks Say About Predictive Value

交付：`notebooks/02_benchmarks_and_forecast_evidence.ipynb`。

- 问题：银行与宏观信息是否在信用损失的持续性之外增加预测价值？
- 从 `configs/model_specs.yaml` 展示四个 expanding windows；解释 forecast origin、target period、已知预测变量和可评分目标的区别。
- 从 `mean_model_comparison.csv` 按 segment/window 配对 AR 与 dynamic FE，核对唯一键、样本数和保存的 common-key 标志，展示全部八组而非只展示赢家。
- 明确：汇总证据只能核对样本数及历史保存的检查状态，无法从这些 CSV 独立重建逐观测共同评分键。
- 从 `tail_metrics.csv` 选择 `tau=0.9`、双方相同 `prediction_version`；主表用 `POST_REARRANGEMENT`，另给简短 pre/post 对照。
- `window=0` 是 pooled OOS，不是第五个窗口；改善率用 `1 − dynamic_loss / AR_loss`，不对窗口改善百分比简单平均。
- 用三个明确合成的 actual/prediction 值调用 `tail_validation.pinball_loss`，解释 0.9 分位数低估的惩罚，并确认完美预测损失为零。
- 解释 quantile rearrangement 是单个预测的分位数排序处理，不是九季度累计损失分布；不重新估计 quantile models。
- 从现有证据计算并陈述负结果：dynamic FE 在均值比较中通常不优于 AR；尾部改善跨窗口不稳定；不得声称显著性。
- 读取 `validation.json`、`bayesian_diagnostics.csv`，简明陈述 Bayesian 未验证、部分宏观变量是 final-vintage fallback、样本为选择后的银行群体。
- 结尾说明此处回答了什么、没有证明什么；不新增 bootstrap、显著性检验或实验筛选。

### 3.4 Notebook 3：Reading a Nine-Quarter C&I Stress Scenario

交付：`notebooks/03_ci_stress_scenario_walkthrough.ipynb`。

- 问题：条件宏观路径如何在静态资产负债表假设下变成季度和累计 C&I 损失？
- 从配置/现有文档确认 2025Q4 jump-off、2026Q1–2028Q1 九季度、固定 exposure 和银行控制变量；官方情景是条件输入，不是发生概率。
- 从 `stress_by_bank.csv` 严格筛选 `segment=CI`、`baseline/severely_adverse`、`ar_mean/dynamic_fe`；避免把研究者敏感性情景重复加进正式结果。
- 按 model/scenario 汇总未四舍五入的 `cumulative_loss_thousands`，除以 1,000,000 显示 USD billions；核对银行计数与 summary。
- 明确：该 CSV 是累计银行级结果，缺少真实逐季度路径；不得将总量均摊九季并声称恢复了历史路径。
- 用 `StressFit`、`recursive_stress_paths` 和一组人工指定、非拟合的 C&I 参数演示九季度递归；bank/model/scenario 名称与表格标题都标明 synthetic。
- 现有 FE 预测接口所需参数为 `predictors`、同序 `beta` 和 `entity_means`；后者索引使用 `DEMO_CI::CI`。可将各 predictor 的人工均值设为零、`nco_rate` 人工均值设为教学截距。必须称作 synthetic parameters supplied to the existing prediction interface，不称为拟合结果。
- `jump_off` 提供实际接口要求的当前状态字段，例如 `npl_rate`，由 `_freeze_controls` 转为 `lagged_noncurrent_ratio`；不要只提供一个 lag 列而忽略当前状态字段。
- 合成示例用同一银行起点、固定余额与控制变量，两条声明为教学假设的宏观路径；展示 raw rate、上一季反馈、aggregation rate、quarterly loss 与 cumulative loss。
- 不调用正式 `recursive_r4_paths`：它要求完整授权模型/分部集合，不能为教学删减门控、伪造 registry 或改写 formal-use 标志。
- 不调用旧 `summarize_stress` 的 `capital_depletion` 命名；展示 `modeled_credit_loss_burden = cumulative loss / starting Tier 1`，解释这不是资本滚动预测。
- 展示 `quarterly loss = max(annualized predicted rate, 0) / 4 × static exposure`；负 raw rate 仍作为递归状态，floor 只影响美元损失汇总。
- 解释 AR 不含情景预测变量因而两条情景总量相同；dynamic FE 只是受限 challenger，较大的情景差异不证明预测更准。
- 结尾列出缺失的 earnings、provisions、tax、distributions、RWA 动态，以及未验证的多期尾部分布。

## 4. 文件边界与 Review Focus

| 操作 | 文件 | 责任 |
|---|---|---|
| 新建 | 上述恰好三篇 `notebooks/*.ipynb` | 完整英文研究导读，保存经执行的紧凑输出 |
| 按需新建 | `src/bankstress/research_guides.py` | 根目录定位、审计摘录解析、合成输入构造；不实现新的研究算法 |
| 新建 | `scripts/check_research_guides.py` | 固定三篇白名单、干净内核执行、失败非零退出、可选写回输出 |
| 按需新建 | `tests/test_research_guides.py` | 仅测试新增解析/计算适配器的实际风险，不为 prose 或 cell 数写测试 |
| 修改 | `pyproject.toml` | 增加隔离的 `[guides]` 可选依赖，现有核心依赖保持不变 |
| 修改 | `README.md`、`docs/reproduction.md` | 阅读顺序、运行命令、证据边界和完整回放限制 |
| 可选新增 | `docs/superpowers/plans/2026-10-24-research-walkthroughs.md` | 本计划的仓库内副本与完成记录 |

五个必须覆盖的审查点：

1. 从仓库根目录或 `notebooks/` 启动都能定位只读输入，不能依赖开发者绝对路径。
2. 源审计字段不能无声解析为零、错误季度或另一个银行；失败要给出键/字段名。
3. 汇总证据与合成样例不得串用；缺少逐观测/逐季度数据时保持明确边界。
4. Q1、gap、scope、负 NCO、年度率除四和单位换算保持现有定义。
5. 导读执行后受保护的 `results/`、`metadata/`、`data/manifests/`、`configs/` 字节不变。

## 5. 执行任务

### Task 1：建立隔离基线和最小 notebook 运行接口

- [x] 在实际仓库读取当前指令、`git status`、HEAD 与相对审阅版本的相关差异；记录用户已有修改，不复制或覆盖无关改动。
- [x] 按当前环境的 worktree/隔离工作流创建实施分支，选择真实可写目录；不在计划中假设机器固定路径。
- [x] 在隔离环境运行现有 `scripts/export_results.py --verify`，记录输出，并对受保护目录文件记录开始时哈希。
- [x] 在 `pyproject.toml` 新增 `guides` extra：`nbformat>=5,<6`、`nbclient>=0.10,<1`、`ipykernel>=6,<8`、`nbconvert>=7,<8`；验证与当前 Python 环境兼容。
- [x] 提供 `check_research_guides.py`：默认只在临时目录执行三篇 notebook；`--write` 仅在三篇都成功后保存执行结果到原 notebook；`--cwd root|notebooks` 选择内核运行目录。
- [x] 每篇使用独立新内核、Python 3、合理的单 cell 超时（120 秒），不允许 error 输出；运行器不联网、不重训、不重写证据。
- [x] Notebook 用仓库相对路径；若需要共享根目录定位，放入 `research_guides.py`，支持根目录与 notebooks 目录，找不到时明确报错。

### Task 2：完成数据定义导读

- [x] 按 3.2 节建立 notebook 的英文问题、证据说明、公式、例子、解释和局限。
- [x] 如需要 `audit_flow_inputs(root, bank_id, report_date, segment) -> DataFrame`，只解析审计中实际保存的字段/值；返回 `quarterize_ytd` 所需列及来源标签，不补不存在的 form。
- [x] 新增解析 helper 时，用选定审计记录的原文和独立手算做一个精确对照；加入缺少 token/重复记录的失败检查，不依靠 helper 自己生成“期望值”。
- [x] 构造独立 synthetic standard rows，调用 `build_credit_panel`；不要把真实审计 NCO 与虚构余额拼成真实银行年化率。
- [x] 复用现有 flows/panel 测试验证边界；notebook 中加入少量关键断言并输出可读的小表，隐藏无关宽列。

### Task 3：完成模型比较导读

- [x] 按 3.3 节从 committed evidence 生成 mean 全窗口对照、Q90 pooled/window 对照及一幅必要比较图。
- [x] 加入唯一键、配对样本数、prediction version、`window=0` 语义的断言；失败时停止，不能自动丢弃不匹配行。
- [x] 用现有 pinball 函数完成小型 synthetic loss 例子；不创建伪造观测级历史 predictions。
- [x] 所有主要数字从 CSV 算出并对照 summary；文字明确汇总层可以和不可以独立验证的内容。
- [x] 保留负结果和既有限制，不新增 Bayesian 运行、p-value、调参或新结果文件。

### Task 4：完成 C&I 情景导读

- [x] 按 3.4 节从真实累计证据生成两模型/两情景结果表，并核对范围、银行数、单位和 totals。
- [x] 如需要 `synthetic_ci_inputs() -> tuple[DataFrame, DataFrame, list[StressFit]]`，只负责构造清楚列出的教学输入；递归和 floor 调用既有函数。
- [x] 使用独立合成模型名和 `scenario_type="Synthetic demonstration"`；不返回任何假装正式授权或历史验证的状态。
- [x] 用九季度输出断言 horizon 为 1–9、余额固定、负值只在汇总阶段被 floor。当前函数不输出全部 lag/controls；根据明确给出的合成系数，独立手算前两期预测并与输出对照，以验证递归反馈和固定控制变量。用于图表的 lag 列由 jump-off 与上一期 raw prediction 构造，并标明它是解释用派生列，不是历史留存路径。
- [x] 用预先声明的简单正率例子独立核对 `rate / 4 × exposure`；负率例子设截距为 0、lag 系数为 0.5、初始率为 -0.02、其他贡献为 0，前两期 raw rates 应为 -0.01/-0.005、美元损失均为 0。这样能暴露把 floor 错用于递归状态的问题；汇总只称 credit-loss burden。
- [x] 若新增 helper 仅构造数据，以上 notebook 断言及现有 stress 测试足够；不要额外实现或测试另一套递归算法。

### Task 5：导航、完整执行与视觉检查

- [x] README 增加三篇阅读顺序与各自回答的问题，维持主研究结论；每篇顶部/底部互链并链接相关 `docs/`。
- [x] `docs/reproduction.md` 增加安装/执行命令，并解释导读离线运行、证据快照、合成机制演示与完整历史回放的区别。
- [x] 在新虚拟环境安装 `python -m pip install -e ".[test,guides]"`，执行下面验收命令；记录真实结果，不预填 passed 数量。
- [x] 从无隐藏状态的新内核顺序执行三篇；随后从 `notebooks/` 工作目录再执行，专门检查相对路径风险。
- [x] 用 `--write` 保存成功执行的紧凑输出，保持顺序 execution counts、稳定 cell IDs，无错误、冗长日志、机器路径或不可复现的临时输出。
- [ ] 导出 HTML 到临时目录并实际打开审读：公式正常、表格不过宽、图例/单位清楚、synthetic 标签醒目、英文自然、代码没有整屏算法堆积。

## 6. 验收命令与完成标准

在仓库根目录执行；以下是实施时待运行的命令，不是本计划已经获得的结果：

```bash
python scripts/export_results.py --verify
python -m pytest -q -p no:cacheprovider
python scripts/check_research_guides.py --cwd root
python scripts/check_research_guides.py --cwd notebooks
python scripts/check_research_guides.py --write
python scripts/export_results.py --verify
git diff --check
```

- [x] 三篇均从干净内核离线执行成功；已有依赖已安装时，无私有目录/网络输入/历史模型二进制依赖。
- [x] 快照校验前后均成功，受保护目录开始/结束哈希一致；核对本次 diff 仅涉及允许的导读和辅助文件。
- [x] 若已有测试因缺少历史 artifact 合理跳过，明确列出原因；不能把 skip 记作完整历史研究重跑。
- [x] 新增 helper 的有意义检查成功；未改研究算法时不新增模仿实现的测试或字数/样式快照测试。
- [x] 三篇均包含独立问题、方法、示例、读数、局限与来源；英文结论和保存的实际输出一致。
- [x] 不因快照不一致而刷新 provenance、覆盖 evidence 或绕开 gate；先定位并报告具体不一致。

## 7. 最后交付

- [x] 在隔离分支提交本次工作，提交说明强调研究可读性、证据边界和离线导读；不 push/merge。
- [x] 交付三篇 notebook 的相对路径、改动文件、实际执行命令/结果、合理 skips、保存输出与 HTML 审阅情况。
- [x] 说明历史快照与核心研究结论保持一致；若有阻塞，准确区分未执行、执行失败、数据不存在，不能声称全面复现。
- [x] 最后再次确认恰好三篇导读；没有新增模型拟合、改变样本、扩大实证结论或触碰其他仓库。


## 8. 本次执行记录（2026-10-24）

- 基线 `df3aa00`，已有干净 linked worktree，创建分支 `enhancement/research-walkthroughs`；保留前一轮模型风险扩展，不 reset 到审阅版本。
- 新增恰好三篇 notebook；依次为 15、16、15 个单元格，英文正文约 650、648、640 词，各一幅图。计算复用现有函数，无新模型拟合或新实证结论。
- 实际执行：`python scripts/export_results.py --verify` 前后均通过，10 个历史证据文件及 summary 通过；58 个受保护文件起止 SHA-256 完全一致。
- 实际执行：`python -m pytest -q -p no:cacheprovider`，审查修复后新虚拟环境中 **150 passed**，208 条依赖相关 warning；本地原历史输入已存在，因此这一运行没有 skip，不等于重新拟合历史研究链。
- 实际执行：`python scripts/check_research_guides.py --cwd root`、`--cwd notebooks`、`--write` 全部通过，每篇独立新内核，临时副本不包含 `outputs/`。原 notebook 已保存顺序执行输出，无 error、stderr 或机器路径输出。
- 解析与运行器 13 项检查覆盖审计原文手算、错误 token、NaN、重复记录、错误季度、工作目录、独立内核、执行失败时保留原 notebook、禁止改动受保护输入。RED→GREEN 过程已执行。
- 新 venv 使用 Python 3.13；原始 `pip install -e ".[test,guides]"` 解析到 pandas 3.1.0，导致原有 `test_unsupported_filing_spine_retains_explicit_segment_placeholders` 的空表 object/datetime merge 失败。将本地验收环境固定到 pandas 2.3.3 后通过；未修改核心依赖声明或研究算法。复现文档说明该限制。
- 三份 HTML 已成功导出到忽略目录 `tmp/guides-html/`；用户全局 nbconvert 配置引用缺失插件，设置 `JUPYTER_NO_CONFIG=1` 后导出成功。浏览器安全策略拒绝本地 file URL，未尝试绕过；完整 HTML 页面视觉验收尚未完成。三幅保存的 PNG 已实际查看，标题、单位、图例与 synthetic 标签可读。
- 临时目录权限问题通过在本地设置 TEMP/TMP 到忽略目录解决；Git 元数据位于旧仓库路径，分支操作经执行权限审核完成。
- Ruling: 复用现有 worktree 并新建分支，避免复制历史输入；代价是新分支包含此前尚未推送的模型风险提交。Bash 技能辅助脚本被系统限制，改用 Python/PowerShell 维护等价任务记录。
- 独立整分支审查完成：发现一项 Important（遗漏季度金额为零的组件仍通过汇总核对），已加失败回归并调用既有 `required_flow_components` 检查完整组件集合；修复后通过。无其他 Critical/Important/Minor。
- 干净无历史输入副本：最终 **142 passed, 8 skipped**，208 条依赖 warning。8 项 skip 分别为报告（1）、压力产物（5）、R3 tail validation（2）；不是完整历史链重跑。
- 全部三种导读执行命令在修复后再次通过；原有测试与历史快照均未改变。
- 首次提交 `ad130a4`；审查修复和收尾记录另行提交，分支 `enhancement/research-walkthroughs`；不 push、不 merge。
- 审查边界决策：审查员未重复会产生文件的测试，由执行者实跑并保留结果；无原始 FFIEC 档案/逐观测预测的新验证；整页 HTML 视觉验收因浏览器策略未完成，保留上方未勾选项。三项边界不扩展研究结论。
