# 扩题工作流（Benchmark Expansion Playbook）

`legal-ai-watch` 的公开榜单当前 39 题。本文件记录把题库安全扩到百级的**纪律**，
核心是：题目引注必须全部落在 `config/article_texts.json` 的**已核验**条文全文上，
绝不凭记忆撰写法条，也不把未核验文字当真值。

## 状态（2026-09-04）

- 参考库 `article_texts.json`：**82 条、_uncovered=0**。其中 61 条为历史（38 条来自
  legal-hallucination-bench 已核验 KB + 22 条来自用户提供的官方 .doc 原文）；
  **新增 21 条**来自 legal-hallucination-bench 已核验 KB
  （`knowledge_base/laws/statutes.jsonl`，2327 节点全 verified），经
  `scripts/build_article_texts.py --merge-pending` 合并（status=VERIFIED，KB 已律师核验）。
- 候选题目草稿：`config/questions_candidates.draft.json`（**25 道，Q40–Q64，
  `_STATUS=CANDIDATE_UNVERIFIED`**）。待律师逐题核验后并入 `questions.json`。

## 步骤

### 0. 诊断覆盖与扩展容量
```bash
python3 scripts/coverage_report.py
```
输出：每题引注覆盖、未引用锚点（安全出题点）、领域/法条分布、理论扩展上限。
CI 另以 `article_texts` 不变量（条目数 ≥ 60 且 `_uncovered == 0`）做硬门禁。

### 1. 扩充参考库（仅从已核验源）
- **8 部法内**：直接从未公开的 legal-hallucination-bench 已核验 KB 取条文（绝不凭记忆）。
  把目标 `(law, article)` 加入 `config/article_texts_unverified.json["article_texts"]`
  并补 `_pending` 条目 `status=VERIFIED`，再
  `python3 scripts/build_article_texts.py --merge-pending config/article_texts_unverified.json`。
- **范围外规范**（PIPL / 数据安全法 / 反不正当竞争法 / 专项附加扣除等）：须律师从
  官方原文（用户提供 .doc 或 flk.npc.gov.cn / www.gov.cn）逐条抽取填入，标记 VERIFIED 后合并。

### 2. 起草候选题目
- 每题 `expected_citation` 必须指向步骤 1 已入库的条文键（`law#article`）。
- 写入 `config/questions_candidates.draft.json`，**保留 `_STATUS=CANDIDATE_UNVERIFIED`**，
  不得直接改 `questions.json`（后者即基准真值）。

### 3. 律师核验
- 逐题核对：题干事实正确、预期引注准确、无旧法/新法时序错配、领域归类正确。
- 核准的题目从草稿移到 `questions.json`（沿用既有字段：
  `qid/domain/prompt/prompt_en/expected_citation/also_correct/acceptable_citations/verifiable/temporal_trap`）。
- 同步更新 `config/questions_candidates.draft.json` 移除已并入者。

### 4. 回归
```bash
python3 -m pytest tests/ -q          # 含 test_coverage（草稿引注全覆盖 + 不变量）
python3 scripts/coverage_report.py    # 确认新题引注全部命中
```

## 纪律红线
- `questions.json` = 基准真值，须经律师核验签署后方可改动。
- 任何法条正文只能源于：① LHB 已核验 KB；② 用户提供的官方 .doc / 官方站点原文。
  严禁 AI 凭记忆撰写。
- 合并进 `article_texts.json` 的条目必须 `status=VERIFIED` 且正文非空；未核验条目
  被 `--merge-pending` 安全闸跳过。
