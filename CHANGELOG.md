# Changelog — Legal AI Watch

All notable changes to the leaderboard pipeline and published reports are
recorded here. Entries are appended automatically by the weekly evaluation
workflow and manually when methodology changes.

## Format

Each line follows: `YYYY-MM-DD · <scope> · <summary>`

---

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
- **真实错引仍被捕获**：错引不同条号（如《专利法》第13条 vs 第15条、《公司法》第66条 vs 第43条、第224条 vs 第177条）因条号不同仍判 ✗；不同法域（如《增值税暂行条例》第10条 vs 《营改增试点实施办法》第25条）亦维持 ✗。
- 影响：本版修正后，首轮真实数据中的 Q2(DeepSeek)、Q7(GLM-4) 由误判 ✗MA 转为 ✓；DeepSeek HVI 由 25%→约 12.5%，GLM-4 由 40%→约 30%。需重新运行 Manual Model Evaluation 以刷新榜单。

<!-- NEW ENTRIES APPENDED ABOVE THIS LINE BY THE WEEKLY WORKFLOW -->
