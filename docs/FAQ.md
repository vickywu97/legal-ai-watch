# 常见问题 (FAQ)

### Q1. HVI 是什么？为什么越低越好？
HVI = Hallucination of Verifiable Citations Index（引注幻觉率），即模型给出的法条引注中
「不存在（✗MA）/ 时态版本错误（✗T）」的比例。比例越低，说明模型援引法条越可信，因此越低越好。
`✗ERR`（接口失败）不计入 HVI，单独报告。详见 [METHODOLOGY §3](METHODOLOGY.md#3-指标定义)。

### Q2. 这能代表模型的整体法律能力吗？
不能，也不试图代表。HVI 只衡量**可验证法条引注**这一个高风险子集。一个模型可能 HVI 很低但
推理能力一般，反之亦然。我们把指标严格限定在「可被客观核验」的范围内，以保证可复现。

### Q3. 为什么演示数据和真实数据不一样？
`scripts/seed_demo.py` 仅用于本地预览 Dashboard，是**随机生成的演示数据**，不代表任何模型真实表现。
正式数据由 GitHub Actions 调用真实模型 API（`run_eval.py`）产生并覆盖。

### Q4. 题库多久更新一次？
跟随 [`legal-hallucination-bench`](https://github.com/vickywu97/legal-hallucination-bench) 的题库。
更新后运行 `scripts/sync_questions.py` 同步，再触发一次评测即可。

### Q5. 如何新增一个被测模型？
见 [HOW_TO_ADD_MODEL.md](HOW_TO_ADD_MODEL.md)，或在 GitHub Issues 提交「Add Model Request」模板。

### Q6. 数据公开吗？可以引用吗？
全部公开（MIT）。原始回答、核验记录、评测脚本均在 `data/` 与 `scripts/` 中。引用请注明来源
**Legal AI Watch**。

### Q7. 模型厂商可以「刷榜」吗？
评测以 `temperature=0` 固定作答，且题库与核验引擎独立于本榜单维护，厂商无法通过本仓库干预结果。
为抑制「同题隔轮回答不一致」带来的 HVI 波动，每题每模型取样 `N` 次（默认 3，详见方法论文档 §8），
HVI / CRFI / 分领域 HVI 跨全部取样汇总，榜单可复现。若某模型版本更新导致分数变化，会在
CHANGELOG 与排行榜版本标注中体现。

### Q8. 成本是多少？
零成本。所有被测模型均有免费额度；GitHub Actions 与 GitHub Pages 均免费。详见主仓库 README。

### Q9. 支持英文评测吗？
支持。题库每题含 `prompt_en`，`run_eval.py --locale en` 使用英文题目与英文系统提示词
（`config/prompts.json` 中的 `system_prompt_en`）评测模型的英文作答；英文引注
（如 "Article 584 of the Civil Code"）会被归一化到同一套法条映射，与中文口径一致。

### Q10. 评测失败了会怎样？
评测 job 失败时，GitHub Actions 会开一个带 `ci-failure` 标签的 Issue（若已存在则追加评论），
提醒维护者榜单可能已过期。排行榜页面也会在超过 14 天未成功出榜时显示「数据已过期」提示。
可据此排查是密钥失效、模型 API 限流还是代码回归（CI 的 `pytest` 闸门会在部署前拦住代码回归）。
