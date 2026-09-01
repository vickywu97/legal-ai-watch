# ✗F（内容忠实度）状态 · 设计草案

> 状态：**PoC 已实现（待评审 / 待 push 后验证）**。基于方案 B 的 stdlib 变体落地（字符二元文法 Jaccard，零依赖、零 API、确定性）。改动：`scripts/faithfulness.py` + `verifier.py`（opt-in）+ `config/article_texts.json`（种子）+ `run_eval.py`（`--check-faithfulness`）+ `generate_dashboard.py`（橙色标注）+ `tests/test_faithfulness.py`。**默认关闭，不计入 HVI**。详见 §7。
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
- 落地采用**方案 B 的 stdlib 变体**：字符二元文法 Jaccard 相似度（非 embedding，零依赖、零 API、完全可复现），契合项目"确定性、可审计"原则。
- 仍是 PoC：语义粒度较粗，仅捕获极端内容失真；后续可升级为本地 embedding 或 LLM 裁判以提升粒度（代价：非确定性 / 外部依赖）。

## 7. 实现状态（2026-09-02 PoC）

### 改动清单
- `scripts/faithfulness.py`（新增，纯 stdlib）：`FaithfulnessChecker` + `jaccard`/`char_bigrams`/`normalize_text`。`is_faithful()` 返回 `True/False/None`（None=无官方正文或作答过短→跳过，绝不误报）。
- `scripts/verifier.py`：新增 `FAITHFULNESS_FAIL="✗F"` 常量（**不在** `HALLUCINATION_STATUSES`，故 HVI 不变）；`verify()` 增加 opt-in 参数 `faithfulness=None`；三条 ✓ 返回路径经 `_emit_ok()` 统一处理——仅当 checker 给出 `False` 才降级为 `✗F`，且结果带 `faithfulness_checked` / `faithfulness_score` 字段。
- `config/article_texts.json`（新增，种子）：键 `law#article` → 官方法条正文；当前覆盖 10 个高频法条（民法典577/181/188/1182/23/71、公司法162/57/23、增值税法22），缺失法条自动跳过。**正文须以官方发布文本核对后再扩写**。
- `scripts/run_eval.py`：导入 `FaithfulnessChecker`；新增 `--check-faithfulness` 开关（默认关闭）；开启时加载 `article_texts.json` 并传入 `verify()`；`_STATUS_PRIORITY` 加入 `✗F`；`aggregate_samples` 增加 `_faithfulness_checked` / `_faithfulness_fail` 计数；`build_leaderboard` 增加独立副指标 `content_fidelity = (checked-fail)/checked`（未开启时为 `null`）。
- `scripts/generate_dashboard.py`：诊断矩阵图例补 `✗F`（橙色 `warn`），`statusClass` 映射 `✗F→warn`，CSS 补 `.cell.warn` / `.lg.warn`。
- `tests/test_faithfulness.py`（新增）：纯函数单测（归一化 / Jaccard 边界 / 忠实-不忠实-跳过 三类判定）。

### 如何启用
```bash
# 默认（关闭 ✗F，行为与此前完全一致）：
python scripts/run_eval.py --date 2026-09-02

# 开启 ✗F 内容忠实度层（零额外依赖 / 零 API）：
python scripts/run_eval.py --date 2026-09-02 --check-faithfulness
```

### 待办 / 开放问题
1. **阈值标定**：默认 `0.15` 为保守初值，需用**标注样本**（正确概括 vs 事实错误）标定；过高误报、过低漏报。
2. **正文扩写**：`article_texts.json` 仅种子 10 条，须核对官方文本并覆盖全部 39 题预期引注。
3. **粒度升级**（可选）：本地 embedding 替代字符二元文法，提升语义捕获能力（引入本地模型依赖）。
4. **测试**：`tests/test_faithfulness.py` 已写，但本次改动未经 Bash 运行验证（沙箱环境受限），待 push 后补跑 `pytest`。
