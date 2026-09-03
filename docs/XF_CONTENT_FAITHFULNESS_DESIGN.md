# ✗F（内容忠实度）状态 · 设计草案

> 状态：**已落地 + 已标定 + 测试全绿（待 push）**。指标基于方案 B 的 stdlib 变体，已从字符二元文法 Jaccard **切换为 containment**（containment = |A∩B|/|A|，对参考长度不敏感），默认阈值经 8 组标注样本标定至 **0.45**。零依赖、零 API、确定性、可复现。改动：`scripts/faithfulness.py` + `verifier.py`（opt-in）+ `config/article_texts.json`（**38 条全文，取自已核验 KB**）+ `run_eval.py`（`--check-faithfulness` / `--faithfulness-metric` / `--faithfulness-threshold`）+ `generate_dashboard.py`（橙色标注）+ `tests/test_faithfulness.py`。**默认关闭，不计入 HVI**。详见 §7。
> 关联：`METHODOLOGY.md` §4 状态体系、`scripts/verifier.py`。

---

## 0. 背景与动机

当前 `verifier.py` 只做两层判定：

1. **引注存在性 / 合法性** —— 条号是否真实、是否编造（`✓` / `✗MA` / `✗NF`）。
2. **时态有效性** —— 是否援引已废止 / 旧版本法条（`✗T`）。

**盲区**：模型**引对了条号**，但对该条**内容的表述与官方条文实质不符**（概括失真、关键要件遗漏、要件错配、事实陈述错误）→ 当前判定为 `✓`，不扣分。

典型命中（来自用户 sign-off 复核的边界讨论）：

- **Q33（正当防卫）**：模型引《民法典》第181条第1款（条号正确），但解释为"正当防卫不适用于防卫过当"——事实有误，条号对，当前不捕获。
- **Q34（违约责任）**：模型只引第584条（损害赔偿），未覆盖第577条的继续履行 / 采取补救措施——这是**条号级**漏覆盖，当前通过 `also_correct` 设计有意放行；但若模型引第577条却把"继续履行"曲解为"仅赔钱"，则属内容失真，当前不捕获。

引入 `✗F` 的目标：在**不破坏确定性主基线**的前提下，把"引注对但内容错"这类幻觉从 `✓` 中分离出来。

---

## 1. 术语与状态定义

新增状态：

| 状态 | 含义 |
|------|------|
| `✗F` | **Faithfulness fail**：引注条号真实、未废止、存在，但**模型对该法条内容的表述与官方条文实质不符**（概括失真 / 要件遗漏 / 要件错配 / 事实陈述错误）。 |

与既有状态的关系（互斥分层）：

| 状态 | 触发条件 |
|------|----------|
| `✓` | 引注真实 + 内容忠实 |
| `✗MA` | 引注本身错（编造 / 错引条号） |
| `✗T` | 引注已废止旧法（非等价） |
| `✗NF` | 引注条号不存在 |
| `✗F` | 引注条号对，但**内容表述不忠实** |

**关键不变量**：`✗F` 只在"确定性四态已判 `✓`"之后才进入判定。即 `✗F` 与 `✗MA / ✗T / ✗NF` **互斥**（条号都不对，谈不上内容忠实度），故优先级冲突仅在"内容层"内部。

---

## 2. 判定方案（三选一或组合）

### 方案 A：LLM 裁判（rubric-based）
- **输入**：官方条文全文（从 KB 取 canonical 条文）+ 模型作答文本 + rubric（是否遗漏关键要件 / 是否曲解 / 是否有事实错误）。
- **输出**：`✓` / `✗F` + 结构化理由。
- ✅ 语义级、可捕捉概括失真。
- ❌ 非确定性、需 API key；与项目"可复现、不依赖主观裁判"的设计原则冲突；有成本；可复现性差。

### 方案 B：嵌入相似度阈值（推荐 PoC）
- 对"模型关于该条的陈述"做句向量，与"官方条文"向量算余弦相似度；低于阈值 → `✗F`。
- ✅ 确定性、可本地化（零 API、可复现）；实现简单。
- ❌ 阈值难标定为"正确但换种说法"与"实质失真"的边界；需 embedding 模型（本地或轻量 API）。

### 方案 C：结构化要件抽取 + 事实比对
- KB 为每条预标注"关键要件"列表；模型作答抽取要件，与 KB 比对缺失 / 错配 → `✗F`。
- ✅ 最可解释、确定性最强。
- ❌ 需为每条建要件标注（与现有 2327 节点规模不匹配，短期人工成本不可行）。

---

## 3. 推荐落地方式

- **默认 OFF**：仅当显式 `--check-faithfulness` 且配置了 judge（A 或 B）时启用。
- **确定性基线永远运行**：`✓ / ✗MA / ✗T / ✗NF` 四态不受 `✗F` 开关影响；`✗F` 是**叠加增强层**。
- **不污染主榜单**：`✗F` 不计入默认 HVI（`HVI = ✗MA + ✗T + ✗NF` 保持不变）。
- **独立副指标**：启用时单独报告 `Content Fidelity Rate`（忠实率），与主 HVI 并列展示。
- **优先级**：`verify()` 中先跑确定性四态；仅当确定性给 `✓` 且开启 faithfulness 时，再跑 `✗F` 判定。
- **短期 PoC 优先方案 B**（本地 embedding，零 API、可复现），作为可选实验开关。

---

## 4. 与现有度量的关系

| 指标 | 公式 | 是否受 ✗F 影响 |
|------|------|----------------|
| **HVI**（主指标） | `wrong ÷ (correct + wrong)`，其中 `wrong = ✗MA + ✗T + ✗NF` | **不变**（✗F 不计入） |
| **Content Fidelity**（副指标，仅启用时） | `faithful ÷ (faithful + ✗F)` | 新增 |
| 看板 | `✗F` 图例（建议橙色 `warn`），`statusClass` 显式映射 | 新增图例 |

> 设计原则：主榜单保持"确定性、零 API、可复现"；`✗F` 永远是**可选叠加**，关闭时行为与 `a10c0dd` 完全一致。

---

## 5. 风险与开放问题

1. **成本 / 可复现性**（方案 A）：破坏确定性基线，需 Secrets 与 API 配额。
2. **阈值标定**（方案 B）："正确换种说法" vs "实质失真"的边界需人工标注样本标定。
3. **要件标注成本**（方案 C）：与 2327 节点规模不匹配，短期不可行。
4. **与"不启用新模型"约束的关系**：`✗F` 的 judge 是独立的小模型 / embedding 服务，**不等于**启用 6 张评测卡；但若用方案 A 仍需 Secrets，与"暂不启用新模型"的口径需显式区分（judge 用于**校验**，不是**被评测对象**）。

---

## 6. 结论与下一步

- `✗F` 已作为**可选增强层**实现，默认关闭，绝不破坏现有确定性基线（不计入 HVI/CRFI）。
- 落地采用**方案 B 的 stdlib 变体**：字符二元文法相似度（非 embedding，零依赖、零 API、完全可复现），契合项目"确定性、可审计"原则。
- **指标实测后由 Jaccard 切换为 containment**：Jaccard 的分母含并集，官方正文越长分数被系统性压低，导致"答对的简洁回答被误判 ✗F"且判别力崩塌（详见 §7 标定记录）；containment = |A∩B|/|A| 对参考长度不敏感，且更贴合"模型说的话有没有官方依据"的语义。`jaccard` 仍保留为 ablation 对照指标。
- 仍是 PoC：语义粒度较粗，仅捕获极端内容失真；后续可升级为本地 embedding 或 LLM 裁判以提升粒度（代价：非确定性 / 外部依赖）。

## 7. 实现状态（2026-09-02 PoC）

### 改动清单
- `scripts/faithfulness.py`（新增，纯 stdlib）：`FaithfulnessChecker` + `containment`/`jaccard`/`char_bigrams`/`normalize_text`。默认指标 `containment`（阈值 0.45），`jaccard` 保留为 ablation 对照；`is_faithful()` 返回 `True/False/None`（None=无官方正文或作答过短→跳过，绝不误报）。
- `scripts/verifier.py`：新增 `FAITHFULNESS_FAIL="✗F"` 常量（**不在** `HALLUCINATION_STATUSES`，故 HVI 不变）；`verify()` 增加 opt-in 参数 `faithfulness=None`；三条 ✓ 返回路径经 `_emit_ok()` 统一处理——仅当 checker 给出 `False` 才降级为 `✗F`，且结果带 `faithfulness_checked` / `faithfulness_score` 字段。
- `config/article_texts.json`（**已扩至 60 条，_uncovered=0**）：键 `law#article` → 官方条文**全文**。其中 38 条逐条取自 legal-hallucination-bench 的 `knowledge_base/laws/statutes.jsonl`（2327 条，verification_status 全 `verified`，源自全国人大/中国政府网官方文本）；**另有 22 条范围外规范的官方全文由用户提供的官方 .doc 原文（flk.npc.gov.cn / www.gov.cn 下载件）逐条抽取填入并标记 VERIFIED**（个人所得税专项附加扣除暂行办法 #5–#22、个人信息保护法 #38/#54、反不正当竞争法 #6、数据安全法 #27）。**全部不凭记忆撰写**；39 题的全部引注均已纳入 ✗F 覆盖，无遗漏。
  - **重新生成**：`python scripts/build_article_texts.py`（自动探测 LHB 的 `statutes.jsonl`；`--dry-run` 仅预览；`--kb` 显式指定路径；幂等——KB/题目不变则产物不变）。脚本只从已核验 KB 抽取，绝不凭记忆撰写条文。
  - **范围外规范（22 条缺口）人工核验工作流（已完成）**：38 条之外，39 题还引用了 22 个 8 部法之外的法条（个人所得税专项附加扣除暂行办法 #5–#22、个人信息保护法 #38/#54、反不正当竞争法 #6、数据安全法 #27），这些**不在 LHB KB 内**，须律师从官方原文逐条核对填入。工作流：`--emit-pending config/article_texts_unverified.json` 生成留空模板（幂等，带 `cited_by`/`official_source`/`status`）；用户于 2026-09-03 提供 4 份官方 .doc 下载件，22 条已逐条抽取填入并标记 `VERIFIED`，经 `--merge-pending` 合并进主库（仅接受 VERIFIED 且非空者，主库 `_uncovered` 归零，合并条目在普通 regen 时被 `old_texts` 保留）。⚠️ 反不正当竞争法为用户提供的 **2025 修订版**，其第 6 条已重排为「社会监督」，旧法「混淆行为」移至第 7 条——若 Q27 预期「混淆行为」内容，其引注应改为 #7（基准题目层面时序一致性问题，不在 ✗F 文本层解决）。详见 `docs/ARTICLE_TEXTS_PENDING.md`。
- `scripts/run_eval.py`：导入 `FaithfulnessChecker`；新增 `--check-faithfulness` 开关（默认关闭）+ `--faithfulness-metric`（`containment`/`jaccard`，默认 containment）+ `--faithfulness-threshold`（默认 0.45）；开启时加载 `article_texts.json` 并传入 `verify()`；`_STATUS_PRIORITY` 加入 `✗F`；`aggregate_samples` 增加 `_faithfulness_checked` / `_faithfulness_fail` 计数；`build_leaderboard` 增加独立副指标 `content_fidelity = (checked-fail)/checked`（未开启时为 `null`）。
- `scripts/generate_dashboard.py`：诊断矩阵图例补 `✗F`（橙色 `warn`），`statusClass` 映射 `✗F→warn`，CSS 补 `.cell.warn` / `.lg.warn`。
- `tests/test_faithfulness.py`（新增）：纯函数单测（归一化 / Jaccard 边界 / 忠实-不忠实-跳过 三类判定）+ `TestCalibrationProbe`（用真实 `article_texts.json` 锁住 containment+0.45 的分离性质：忠实样本全 ≥ 阈值、不忠实样本全 < 阈值、两簇间存在干净空隙，作为回归护栏）。

### 如何启用
```bash
# 默认（关闭 ✗F，行为与此前完全一致）：
python scripts/run_eval.py --date 2026-09-02

# 开启 ✗F 内容忠实度层（零额外依赖 / 零 API）：
python scripts/run_eval.py --date 2026-09-02 --check-faithfulness
```

### 待办 / 开放问题
1. **阈值标定（已完成）**：默认阈值经 `TestCalibrationProbe` 的 8 组标注样本标定至 **0.45**（containment 指标下，忠实样本 0.538–0.857、不忠实样本 0.129–0.387，空隙 (0.387, 0.538)）。样本量仍小，后续可用更大标注集收紧；`--faithfulness-threshold` 可临时扫描。
2. **正文扩写（已完成）**：`article_texts.json` 已从 10 条种子扩到 **60 条官方全文**（38 条来自已核验 KB + 22 条来自用户提供的官方 .doc），覆盖 39 题**全部**预期引注（`_uncovered=0`），无凭记忆撰写。
3. **粒度升级**（可选）：本地 embedding 替代字符二元文法，提升语义捕获能力（引入本地模型依赖）。
4. **测试（已绿）**：`pytest -q` → 62 passed（含 `TestCalibrationProbe`），无 error。
5. **范围外规范覆盖（已完成）**：22 条 8 部法之外缺口已由用户提供的官方 .doc 原文逐条抽取填入并 `VERIFIED`，经 `--merge-pending` 合并进主库，`_uncovered` 归零。⚠️ 反不正当竞争法为用户提供的 **2025 修订版**，其第 6 条已重排为「社会监督」（旧「混淆行为」移至第 7 条）——若 Q27 预期「混淆行为」内容，引注应改为 #7（基准题目层面时序一致性问题，不在 ✗F 文本层解决）。模板与工作流保留供后续扩展。

### 标定记录（为何从 Jaccard 0.15 切到 containment 0.45）
- 旧方案 Jaccard（阈值 0.15）以**节选**参考测出"答对 0.203、答错 0.028"的分离；但换成**官方全文**作参考后：
  - 公司法#162「答对」样本 Jaccard 被长文本压到 **0.093 → 误判 ✗F**；
  - 且该「答对」(0.093) **低于**「答错」(0.108)，**判别力崩塌**。
- 改用 **containment = |A∩B|/|A|**（对参考长度不敏感）后，同一批全文参考：
  - 忠实样本 0.538–0.857，不忠实样本 0.129–0.387，空隙干净；
  - 默认 0.45 落在空隙内、偏不忠实侧（更好召回真实失真），距最低忠实样本仍有 0.088 余量（宁可漏报、不可误报）。
- 注：不忠实样本最高分 0.387（民法典#188「二十年」错答）源于全文含"二十年"等词带来的虚假重合——这正是 containment 优于 Jaccard 但仍需阈值留余量的原因；0.45 已将其正确判为 ✗F。
