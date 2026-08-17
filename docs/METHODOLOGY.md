# 评测方法论 (METHODOLOGY)

> 版本: v2.0 · 最后更新: 2026-08-14

本文档说明 Legal AI Watch 如何衡量法律大模型的「法条引注幻觉率」。
评测逻辑由本仓库的 [`scripts/verifier.py`](../scripts/verifier.py) 引擎实现，并消费
[`legal-hallucination-bench`](https://github.com/vickywu97/legal-hallucination-bench)
的稳定题库与法条知识库版本。

---

## 1. 核心问题

法律大模型在回答时常引用法条，例如「根据《民法典》第 584 条……」。我们要回答：
**这条引注是否真实存在？内容是否准确？** 这类错误会直接误导法律实务，是
法律 AI 最危险的失效模式之一。

本榜单额外关注两类高频、且内行律师一眼能识别的失效：

- **时态/版本幻觉（✗T）**：题目预期现行法（如《民法典》），模型却援引已被废止的
  《合同法》或已失效的旧法条号。这与「编造法条（✗MA）」本质不同——法条真实存在，
  只是**时效/版本错了**。单列这一维度，才能把「该用新法却引旧法」与「凭空编造」区分开。
- **接口失效（✗ERR）**：API 超时 / 限流 / 鉴权错误的回答。这属于基础设施问题，
  **不混入模型行为指标**，单独以 `api_errors` 报告，并在排行榜标注，避免把
  「接口挂了」误判成「模型未作答（·）」而美化榜单。

## 2. 评测流程

```
题目(question) ──► 模型回答(answer) ──► 引注抽取(extraction)
        │                                          │
        └──────────── 核验(verification) ◄─────────┘
                              │
                      逐条判定状态(status)
                              │
                      聚合 → HVI / CRFI / Coverage / Integrity / Temporal / API错误
```

1. **题目**：从题库抽取「可验证引注」类问题（当前 31 题，双语 `prompt_en`），每题对应一个预期法条（如《民法典》第 584 条）。
2. **作答**：以 `temperature=0` 调用各被测模型的 OpenAI 兼容接口；每题取样 `N` 次以抑制非确定性（默认 3，见 §9）。支持 `--locale {zh,en}` 双语评测（见 §8）。
3. **引注抽取**：正则识别回答中的法条引注，支持中英文两种形态（见 §8）。
4. **核验**：交由 `verifier.py` 引擎，对照权威法条归一化映射逐条判定（见 §7）。
5. **聚合**：按模型统计 HVI、CRFI、Coverage、Integrity、Temporal 与 API 错误，并按法域拆分。

## 3. 指标定义

| 指标 | 公式 | 含义 |
|------|------|------|
| **HVI**（主指标） | `wrong ÷ (correct + wrong)` | 引注幻觉率，**越低越好**。wrong = ✗MA+✗NF+✗F+✗T |
| **CRFI** | `correct ÷ (correct + wrong)` | 可验证引注正确率 |
| **Coverage** | `(correct + wrong) ÷ (correct + wrong + nocite)` | 引注覆盖率 = 有作答的题 ÷ 总题。模型「装死不答」会被看见、被惩罚 |
| **Integrity** | `correct ÷ (correct + wrong + nocite)` | 综合正确率 = 正确 ÷（正确+错引+未作答），更全面地反映可用性 |
| **Temporal** | `temporal ÷ (correct + wrong)` | 时态幻觉率 = 涉时效/版本错误 ÷ 全部有效引注 |
| **API 错误** | `✗ERR 计数` | 接口/基础设施失败次数（单列，**不混入上述任何分母**）|

分母约定：
- HVI / CRFI / Temporal 的分母 = `correct + wrong`（有效引注，即 ✓ 与全部 ✗ 幻觉态），**不含** ✗ERR / ? / ·。
- Coverage / Integrity 的分母 = `correct + wrong + nocite`（engage 总量），`nocite`（`·` 未作答）不再被静默豁免，而是拉低 Coverage 与 Integrity。
- `?`（无法判定，知识库未覆盖）与 `✗ERR`（接口失败）均不计入模型行为分母。

> **HVI 与 CRFI 互补**：HVI 看「错的占比」，CRFI 看「对的占比」，二者不互补（因为分母不含 nocite）。模型若大量「不答」可同时压低 HVI——这正是 Coverage/Integrity 要补上的视角。

## 4. 判定状态 (Status)

| 状态 | 含义 | 计入分母 |
|------|------|----------|
| `✓` | 引注真实且内容正确 | HVI / CRFI / Coverage / Integrity / Temporal |
| `✗MA` | Made-up Article：法条不存在 / 编造 | 同上 |
| `✗NF` | Not Faithful：法条存在但内容不符 | 同上 |
| `✗F` | 事实性错误 | 同上 |
| `✗T` | 时态/版本幻觉：援引已废止 / 旧法（题目预期现行法）| 计入 HVI/CRFI/Integrity 的 wrong 与 Temporal |
| `✗ERR` | API / 基础设施失败（非模型行为）| **不计入**，单列 `api_errors` |
| `?` | 无法判定（知识库未覆盖）| 不计入 |
| `·` | 未作答（未识别到引注）| 仅计入 Coverage/Integrity 分母（拉低），不计入 HVI 分母 |

排序：已作答模型（存在有效引注）排前，按 **HVI 升序 → 引注数降序 → api_errors 升序**；无任何有效引注的模型（全 ✗ERR 或全 ·）HVI 记为 `null`，排末位、无排名。

## 5. 排行榜排序

主排行榜按 **HVI 升序**（幻觉率越低排名越靠前）；HVI 相同时按引注数降序（样本更多者优先），再按 API 错误数升序。

## 6. 局限与免责

- 题库规模与法域覆盖有限，HVI 反映「可验证引注」子集，不代表模型整体能力。
- 模型版本随厂商更新而变化；排行榜标注每次评测的模型版本，跨版本比较需谨慎。
- 本榜单仅用于研究与透明披露，不构成对任何产品的推荐或贬损。
- 演示数据（`seed_demo.py` 产出）**不代表真实表现**，正式数据由真实 API 评测覆盖。

## 7. 等价引注与时态幻觉认定

核验引擎（`verifier.Equivalence`）通过**两层**机制决定「模型引注是否命中预期」，避免把
「实质正确 / 更精准」的引注机械判错。

### 7.1 主机制：`config/statute_equivalence.json`（规范化映射）

这是结构化、可审计的单一事实源，由 `Equivalence` 加载后构建
`(law, article) → 规范化组(canonical)` 的映射。覆盖三类系统性等价：

| 等价类型 | 示例（配置中 provision_groups id） |
|----------|-----------------------------------|
| **跨法等价**（暂行条例 ↔ 试点办法 ↔ 新法） | `vat-input-nondeductible`：增值税暂行条例第10条 ↔ 营改增实施办法第27条 ↔ 增值税法第22条 |
| **跨版本等价**（同法修订前后条号重排） | `company-amend-resolution`：2018 公司法第43条 ↔ 2023 公司法第66条；`company-reduction-creditor`：177条 ↔ 224条；`company-shareholder-information-right`：33条 ↔ 57条；`company-legal-representative`：13条 ↔ 10条 |
| **已废止法律清单**（`repealed_laws`，13 项：合同法、婚姻法、继承法、担保法、物权法、收养法、侵权责任法、涉外民事关系法律适用法旧版、营业税暂行条例、城市房地产税暂行条例等） | 用于识别✗T |

判定逻辑：把预期引注与模型每一条引注都映射到规范化组，组相同即判 `✓`（忽略款/项差异，匹配粒度统一到「法条名 + 条号」）。这样**无需逐题手写等价表**——新增一个等价关系，改一份 JSON 即可全局生效。

### 7.2 次机制：`acceptable_citations`（一次性论证）

对于**无法纳入系统性等价、但经出题人论证确属正确**的个别情形（如 Q5 增值税的特别论证、
Q9/Q10 的特殊推理），每题可携带 `acceptable_citations` 列表作为**逐题覆盖**，每条必须带
`justification`（等价性论证）。模型命中预期、规范化组、或任一 `acceptable` 引注，均判 `✓`。

> 设计原则：`statute_equivalence.json` 解决「同类项」，避免逐题 whack-a-mole；
> `acceptable_citations` 只保留真正偶发、需人工论证的少数特例。两者并集匹配。

### 7.3 时态幻觉（✗T）如何判定

若模型引注命中 `repealed_laws` 中的已废止法，且该废止法**不等于**预期的规范化组
（即预期是现行法），则判 `✗T` 而非 `✗MA`——法条确实「存在」，错在时效/版本。
例如题目预期《民法典》第 584 条，模型引《合同法》第 113 条 → `✗T`。
（`temporal_trap: true` 字段标记了此类陷阱题，便于分维度统计。）

### 7.4 引擎行为可审计

`verifier.verify(question, answer, eq)` 返回 `{status, detail, citations}`，`detail` 记录
命中/未命中的具体法条与规范化组，便于在排行榜审计明细中逐条追溯。

## 8. 中英双语评测（locale）

为支持面向国际读者的评测与模型英文作答能力考察：

- **系统提示词版本化**：`config/prompts.json` 存放 `system_prompt_zh` / `system_prompt_en`
  （纳入版本控制，不再硬编码于脚本）。
- **题目双语**：题库每题含 `prompt_en`；`run_eval.py --locale en` 使用英文题目与英文系统提示词。
- **英文引注解析**：引注抽取同时支持
  - 中文：`《xxx》第N条[第M款]`
  - 英文：`Article N of the Civil Code` 与 `Civil Code Article N`（`EN_LAW_ALIASES` 将
    英文名（须以 Act/Code/Law 结尾）映射到规范化中文法名）
- 英文评测复用**同一套**核验引擎与规范化映射，保证中英文口径一致。

## 9. 多次取样抑制非确定性（方差控制）

即便 `temperature=0`，主流大模型对同一道题的回答仍**非完全确定**（API 侧的
采样/路由抖动、reasoning 路径变化等）。实测中，同一题隔轮重跑，模型可能从
「命中引注」翻成「未作答」，或把某题从「错引」翻成「正确」，导致 HVI 跨轮波动、
损害榜单可信度。

**做法**：每题每模型取样 `N` 次（`--samples`，默认 3），对每次取样独立抽取引注并
核验，得到 `N` 个 status。然后：

- **逐题诊断矩阵**展示 `N` 次取样的**多数判定**（majority verdict）；若 `N` 次无严格
  多数，按 `✗MA > ✗NF > ✗F > ✗T > ✗ERR > ✓ > · > ?` 的保守优先级取代表判定（对「幻觉监测」
  类榜单，宁可显示模型曾出错，也不乐观化）。矩阵 cell 的 tip 标注该状态在 `N` 次取样中的占比。
- **HVI / CRFI / Coverage / Integrity / Temporal** 改为跨**全部**取样汇总：

  ```
  HVI = Σ(错引样本数) / Σ(含有效引注的样本数)   # 跨全部题 × 全部取样
  ```

  即把每题每模型的 1 个样本点，摊薄成 `题目数 × N` 个样本点（当前 31 题 × 3 模型 × 3
  取样 = 279 个样本点），方差随样本量增大而显著收敛，HVI 跨轮稳定。

- **引注数（KPI）** = 多数判定为「含引注」（✓ 或 ✗）的题数，保持 0–31 的直观口径。

> 取舍：取样越多 HVI 越稳，但 API 调用量与耗时线性增长（每周定时任务默认 `N=3`；
> 手动触发可通过 `samples` 输入调高，例如 `5` 以获得更平滑的曲线）。

## 10. 复现

```bash
git clone --recurse-submodules https://github.com/vickywu97/legal-ai-watch.git
cd legal-ai-watch
pip install -r requirements.txt
export DEEPSEEK_API_KEY=...   # 等 3 个密钥（Kimi 已退出评测池）
# 中文评测
python scripts/run_eval.py --date 2026-08-14 --output data/ --samples 3
# 英文评测（可选）
python scripts/run_eval.py --date 2026-08-14 --locale en --output data/ --samples 3
python scripts/generate_dashboard.py --data data/ --output dashboard/
```

回归测试（CI 与本地均会跑，作为部署闸门）：

```bash
pip install pytest
python -m pytest tests/ -q
```
