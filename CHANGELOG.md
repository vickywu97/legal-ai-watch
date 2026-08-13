# Changelog — Legal AI Watch

All notable changes to the leaderboard pipeline and published reports are
recorded here. Entries are appended automatically by the weekly evaluation
workflow and manually when methodology changes.

## Format

Each line follows: `YYYY-MM-DD · <scope> · <summary>`

---

## 2026-08-13 · docs · 全局一致性排查 + DEPLOY.md
- **新增 docs/DEPLOY.md**：推送排错（SSH-over-443）、CI 架构（只发 gh-pages）、手动/每周触发、取样管线、等价引注闸门、本地预览、常见故障表、密钥清单，一页式运维手册。
- **全局一致性修复（一次性，不再打补丁）**：
  - 修正 `model_metadata.json` 位置文档错误：README 与 HOW_TO_ADD_MODEL 原写 `data/`，实际在 `config/`（Dashboard 读 config/ 并内联）。
  - `seed_demo.py` 移除已退出的 Kimi，演示模型集与线上启用集（3 模型）对齐。
  - `sync_questions.py` 新增本地策展保留：同步上游题库时按 qid 合并回 `acceptable_citations`/`verifiable`，避免无声覆盖我们手搓的等价引注论证（Q5/Q9/Q10）。
  - `generate_dashboard.py` 标题「近 12 周 HVI 趋势」改为「HVI 趋势」（线上历史仅 2 周，避免误导）。
  - FAQ Q7、METHODOLOGY §2 补多次取样交叉引用（对齐 §8）。
  - README 移除不存在的 `archive/` 目录说明；`run_eval` 示例补 `--samples 3`；MOONSHOT 变量标注 Kimi 已退出。
- 已本地非破坏性验证：seed 仅生成 3 模型/12 周；sync 合并后 acceptable_citations 保留。

## 2026-08-13 · fix · 公司法旧条号等价引注（Q9/Q10 假阳性修复）
- **问题**：GLM-4 在 Q9 引《公司法》第四十三条、Q10 引第一百七十七条，均为 2018 旧公司法条号，但实质与 2023 新法第66条（修改章程特别决议2/3）、第224条（减资债权人保护30日）完全相同；旧口径以「新法条号唯一正解」把它们记成 ✗MA，致 GLM HVI 虚高约 20 个百分点。
- **修复**：仿 Q5 给 Q9、Q10 补 `acceptable_citations`（旧条号 + justification，论证条号版本差异而非幻觉），`verify_local` 的 `{expected} ∪ {acceptable}` 并集匹配自动放过。真错（如 Q8 引专利法第15条）不受影响，仍判 ✗MA。
- 已本地验证：GLM 旧条号回答判 ✓，错引（Q9 第99条 / Q10 第50条）仍 ✗MA，无过度放行。
- METHODOLOGY §7.3 新增「条号版本差异」等价类型。

## 2026-08-13 · methodology · 多次取样抑制非确定性 + Kimi 退出评测池
- **多次取样方差控制**：每题每模型取样 N 次（默认 3，`--samples` 可调），逐题展示多数判定、矩阵 cell 标注取样占比；HVI/CRFI/分领域 HVI 改为跨全部取样汇总（错引样本数 ÷ 含引注样本数），把跨轮非确定性（实测同题隔轮 HVI 波动）摊薄，提升榜单可复现性。见 METHODOLOGY §8。
- **Kimi-K2 退出评测池**：Moonshot API 持续 429 限流、难以获得稳定回答，于 `config/models.json` 置 `enabled:false`；`model_metadata.json` 同步移除。新一期历史模型列表仅含 DeepSeek-R1 / Qwen-Max / GLM-4。
- 工作流新增 `samples` 输入（manual）并显式传参（weekly 固定 3）；其余 CI 行为不变。

## 2026-08-08 · launch · Project v1.0 went live
- Initial public leaderboard published with 4 models: DeepSeek-R1, Qwen-Max, GLM-4, Kimi-K2.
- HVI (Hallucination of Verifiable Citations Index) methodology v1.0 adopted.
- Automated weekly GitHub Actions workflow enabled (Mondays 08:00 Beijing time).
- Demo dashboard generated from seeded sample data pending first live API run.

## 2026-08-10 · fix · 核验器归一化与“未作答”排名修复
- **法条名归一化**：核验逻辑现在把《民法典》≡《中华人民共和国民法典》等"全称/简称"视为同一条法律，并支持汉字条号（第十条≡第10条）与带款号的精确比对。修复了首版把"模型正确援引全称法条"误判为幻觉（✗MA）的缺陷。
- **“未作答”不再误标最佳**：某模型若一轮零引注（status `·`），其 HVI 标记为 `null`（页面显示"未作答"，灰标排末位），不再被算成 0% 最优。
- **不可验证题诚实处理**：`verifiable:false` 或无 `expected_citation` 的题目判为 `?`，不计入幻觉率分母。
- 确认 bench 仓库当前未打包为可导入模块（`legal_hallucination_bench/verify.py` 不存在），故线上实际运行的是已加固的 `verify_local`；`run_eval.py` 顶部说明已同步更新。
- 影响：需重新运行一次 Manual Model Evaluation 以用修正后的核验器覆盖首版（含误报）的真实数据。

## 2026-08-11 · fix · 匹配粒度降至“法条名+条号”，忽略款/项差异
- **款/项精度不再误判**：`citation_key` 现仅取「法条名#条号」做匹配，忽略「第X款/项」差异。模型援引《民法典》第496条第2款而预期为《民法典》第496条、或援引《专利法》第二十三条而预期为第23条第1款，均判为命中（✓），不再误标 ✗MA。
- **真实错引仍被捕获**：错引不同条号（如《专利法》第13条 vs 第15条、《公司法》第66条 vs 第43条、第224条 vs 第177条）仍判 ✗；《营改增试点实施办法》第25条系「准予抵扣」正向列举、与第10条方向相反非等价，维持 ✗；而第27条（「不得抵扣」负面清单）为第10条等价引注，见下方 acceptable_citations 条目。
- 影响：本版修正后，首轮真实数据中的 Q2(DeepSeek)、Q7(GLM-4) 由误判 ✗MA 转为 ✓；DeepSeek HVI 由 25%→约 12.5%，GLM-4 由 40%→约 30%。需重新运行 Manual Model Evaluation 以刷新榜单。

## 2026-08-11 · feature · acceptable_citations：等价引注认定（方案B）
- **题库新增 `acceptable_citations` 字段**：每题除首选 `expected_citation` 外，可列出经论证的等价引注，每条须带 `justification`（等价性论证门槛）。以 Q5 为例，接受《营改增试点实施办法》第27条作为《增值税暂行条例》第10条的等价替代（第27条以负面清单逐项列举「不得抵扣」情形，与第10条规制对象相同；第25条系「准予抵扣」正向列举，方向相反，不纳入等价）。
- **引擎改为并集匹配**：`verify_local` 现对 `{expected_citation} ∪ {acceptable_citations}` 取并集，命中任一即判 ✓；审计明细附 `justification` 以便追溯。空 `acceptable_citations` 退化为单预期。
- **方法论补 §7 等价引注认定标准**：明确三种可认定等价的情形（法律渊源替换 / 新旧法替换 / 法条拆合）与 justification 必填要求，将"专业判断"固化为评测设计的一部分。
- 影响：DeepSeek-R1 在 Q5 命中等价引注 → HVI 由约 12.5%→**0%**（完全干净，证明其在税法域引注精准且更贴近现行细则）。需重新运行 Manual Model Evaluation 以刷新榜单。

## 2026-08-12 · fix · 纠正 Q5 等价引注条号（第25条 → 第27条）
- **条号笔误纠正**：Q5 的 `acceptable_citations` 原误写为《营改增试点实施办法》**第25条**，但该条系「准予抵扣」正向列举，与题目「不得抵扣」方向相反，实为反义而非等价。正确的等价引注是**第27条**（「不得抵扣」负面清单，与《增值税暂行条例》第10条规制对象完全相同）。该笔误源自已采纳的 Q5 设计示例，本轮一并修正。
- **连带纠正**：`docs/METHODOLOGY.md` §7.2 示例与 §7.3 表格中的「第25条」同步改为「第27条」；`run_eval.py` 文档引用的章节号由 §8 修正为 §7。`docs/METHODOLOGY.md` 版本日期同步更新为 2026-08-12。
- **本地验证**：Q5 模型引第27条 → ✓（带 justification）；引第25条 → 维持 ✗MA（真实错误）；引 target 直接命中 → ✓。
- 影响：上一轮真实评测中 Qwen-Max 引《营改增试点实施办法》第27条被错杀为 ✗MA，本版修正后该题为 ✓，Qwen HVI 由 30%→**20%**（与 DeepSeek 并列最佳档）。需重新运行 Manual Model Evaluation 以刷新榜单。

<!-- NEW ENTRIES APPENDED ABOVE THIS LINE BY THE WEEKLY WORKFLOW -->
