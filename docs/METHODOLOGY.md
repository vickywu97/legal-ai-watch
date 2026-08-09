# 评测方法论 (METHODOLOGY)

> 版本: v1.0 · 最后更新: 2026-08-08

本文档说明 Legal AI Watch 如何衡量法律大模型的「法条引注幻觉率」。
评测逻辑本身由 [`legal-hallucination-bench`](https://github.com/vickywu97/legal-hallucination-bench)
维护；本仓库只消费其稳定版本。

---

## 1. 核心问题

法律大模型在回答时常引用法条，例如「根据《民法典》第 584 条……」。我们要回答：
**这条引注是否真实存在？内容是否准确？** 这类错误会直接误导法律实务，是
法律 AI 最危险的失效模式之一。

## 2. 评测流程

```
题目(question) ──► 模型回答(answer) ──► 引注抽取(extraction)
        │                                          │
        └──────────── 核验(verification) ◄─────────┘
                              │
                      逐条判定状态(status)
                              │
                      聚合 → HVI / CRFI / 分领域
```

1. **题目**：从题库抽取「可验证引注」类问题，每题对应一个预期法条（如《民法典》第 584 条）。
2. **作答**：以 `temperature=0` 调用各被测模型的 OpenAI 兼容接口。
3. **引注抽取**：用正则识别回答中的法条引注（如 `《xxx》第N条[第M款]`）。
4. **核验**：交由 bench 核验引擎，对照权威法条知识库逐条判定。
5. **聚合**：按模型统计 HVI、CRFI，并按法域拆分。

## 3. 指标定义

| 指标 | 公式 | 含义 |
|------|------|------|
| **HVI** (主指标) | 幻觉引注数 ÷ 有效引注总数 | 引注幻觉率，**越低越好** |
| **CRFI** | 正确引注数 ÷ 有效引注总数 | 可验证引注覆盖率 |
| **时序幻觉率** | 涉及时效/版本的错误 ÷ 该类引注数 | 专门考察「新法替代旧法」类错误 |

有效引注总数 = 状态为 `✓ / ✗MA / ✗NF / ✗F` 的引注之和（`?` 无法判定、`·` 未作答不计入分母）。

## 4. 判定状态 (Status)

| 状态 | 含义 |
|------|------|
| `✓` | 引注真实且内容正确 |
| `✗MA` | Made-up Article：法条不存在 / 编造 |
| `✗NF` | Not Faithful：法条存在但内容不符 |
| `✗F` | 事实性错误 |
| `?` | 无法判定（知识库未覆盖，不计入分母）|
| `·` | 未作答（未识别到引注，不计入分母）|

## 5. 排行榜排序

主排行榜按 **HVI 升序**（幻觉率越低排名越靠前）；HVI 相同时按引注数降序（样本更多者优先）。

## 6. 局限与免责

- 题库规模与法域覆盖有限，HVI 反映「可验证引注」子集，不代表模型整体能力。
- 模型版本随厂商更新而变化；排行榜标注每次评测的模型版本，跨版本比较需谨慎。
- 本榜单仅用于研究与透明披露，不构成对任何产品的推荐或贬损。
- 演示数据（seed_demo.py 产出）**不代表真实表现**，正式数据由真实 API 评测覆盖。

## 7. 复现

```bash
git clone --recurse-submodules https://github.com/vickywu97/legal-ai-watch.git
cd legal-ai-watch
pip install -r requirements.txt
export DEEPSEEK_API_KEY=...   # 等 4 个密钥
python scripts/run_eval.py --date 2026-08-08 --output data/
python scripts/generate_dashboard.py --data data/ --output dashboard/
```
