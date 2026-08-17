# ⚖️ Legal AI Watch

> 中国法律大模型「法条引注幻觉率」每周自动监测排行榜
> **Automated weekly benchmark of Chinese legal LLMs' citation-hallucination rates**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Repo](https://img.shields.io/badge/Repo-GitHub-blue)](https://github.com/vickywu97/legal-ai-watch)
[![Data](https://img.shields.io/badge/data-synthetic%20%2F%20demo-orange)](https://github.com/vickywu97/legal-ai-watch)

**Legal AI Watch** 全自动、零成本、每周更新地评测主流国产法律大模型的
「法条引注幻觉率」（HVI），公开排行榜、追踪趋势变化，并生成可视化报告。
整个流程由 GitHub Actions 驱动，零人工干预。

🌐 **看板**：本项目通过 GitHub Pages 托管在线看板（<https://vickywu97.github.io/legal-ai-watch>，审计报告等原始数据链接随部署一并发布）；若国内访问 GitHub Pages 不稳定，也可直接打开仓库内 `dashboard/index.html` 本地预览（默认附带的为演示样本，见上方数据说明）。

> ⚠️ **数据性质说明（务必先读）**：本仓库默认随附的数据是 **`scripts/seed_demo.py` 生成的 12 周合成演示样本**，**并非真实模型评测结果**。页面上展示的排行榜、趋势、HVI 数值均为**演示用途（synthetic / demo）**。要进行真实评测，请按下方「真实评测（需配置 API Key）」用你自己的密钥运行 `run_eval.py`；真实结果不会自动公开，需自行托管。GitHub Actions 的"每周定时"工作流也仅在配置好密钥的仓库中才会产出真实数据。

---

## ⚠️ 法律准确性与免责声明（务必先读）

本仓库是**技术评测工具**，不是法律意见来源。使用前请知悉以下边界，以免产生不准确材料或涉诉风险：

1. **引注基准（ground truth）由 AI 策展生成，并经内部复核。** 题库中每题的 `expected_citation` / `acceptable_citations` / `also_correct` 均为 AI 生成、可能存在错误或遗漏，本复核**不署名、不构成执业背书或专业责任归属**，亦非法律意见。对外引用任何 HVI / CRFI 等数值或结论时，请自行判断风险并注明「AI 策展，未经执业背书」。
2. **本榜单度量的是"模型引注与策展基准条文（curator baseline）的一致性"，不等同于对模型法律正确性的全面评价。** 模型可能引注了其他同样正确的条文而被记为"不一致"（尽管已通过 `also_correct` 机制接纳多数并存正确引注，仍无法穷尽所有正确写法）。
3. **本仓库内容不构成法律意见**，不得用于任何实际法律决策；如有具体法律问题，请咨询执业律师。
4. **默认随附数据为合成演示（seed_demo），非真实评测**；真实评测结果由使用者自行运行、自行承担使用与引用责任。
5. 软件按 MIT 许可证「按原样（AS IS）」提供，**作者对数据 / 结论的准确性不作任何明示或暗示担保，亦不对因使用本仓库产生的任何后果负责。**
6. **复核记录（非执业背书）**：31 题逐题复核清单见 [`docs/VERIFICATION_CHECKLIST.md`](docs/VERIFICATION_CHECKLIST.md)；内部复核记录（不署名、非执业背书）见 [`docs/GROUND_TRUTH_SIGN-OFF.md`](docs/GROUND_TRUTH_SIGN-OFF.md)。本仓库数值为 AI 策展 + 内部复核结果，**非专业鉴证**；对外引用请注明「AI 策展，未经执业背书」，风险由引用方自行承担。

---

## 📊 这是什么 / What is this

当法律大模型回答"根据《民法典》第 584 条……"时，这条引注真的存在吗？内容真的对吗？
Legal AI Watch 用一套**可验证引注核验引擎**来回答这个问题，并给每个模型打出一个
**HVI（Hallucination of Verifiable Citations Index，引注幻觉率，越低越好）**。

- **数据本身即内容**：「某模型法条幻觉率 50%」这类结论极易被媒体、论文、产品选型引用。
- **完全自动化**：每周一定时触发，从调用模型 → 核验引注 → 生成 Dashboard → 发布，全流程无人值守。
- **透明可复现**：原始回答、核验结果、评测脚本、模型版本全部公开。
- **自带传播力**：排行榜变动、新模型加入、新法域测试都能成为话题。

---

## 🧮 核心指标

| 指标 | 含义 |
|------|------|
| **HVI** | 引注幻觉率 = 错引数 ÷ 有效引注数（主指标，越低越好）|
| **CRFI** | 可验证引注正确率 = 正确引注 ÷ 有效引注 |
| **Coverage** | 引注覆盖率 = 有作答题 ÷ 总题（「装死不答」会被看见、被惩罚）|
| **Integrity** | 综合正确率 = 正确 ÷（正确+错引+未作答），更全面反映可用性 |
| **Temporal** | 时态幻觉率 = 涉时效/版本错误 ÷ 有效引注（如该用《民法典》却引已废止《合同法》）|
| **API 错误** | 接口/基础设施失败次数（单列，不混入模型行为指标）|

判定子类（逐题矩阵中使用）：
- `✓` 引注真实且内容正确
- `✗MA` 法条不存在 / 编造（Made-up Article）
- `✗NF` 法条存在但内容不符（Not Faithful）
- `✗F` 事实性错误
- `✗T` 时态/版本幻觉：援引已废止 / 旧法（题目预期现行法）
- `✗ERR` API / 基础设施失败（非模型行为，单列）
- `?` 无法判定（知识库未覆盖）
- `·` 未作答

> 核验引擎为 [`scripts/verifier.py`](scripts/verifier.py)，配合
> [`config/statute_equivalence.json`](config/statute_equivalence.json) 的规范化引注映射；
> 详细方法论见 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)。

🌐 **支持中英双语评测**：题库每题含 `prompt_en`，`run_eval.py --locale en` 可跑英文题 +
英文系统提示词（系统提示词版本化存于 [`config/prompts.json`](config/prompts.json)），
中英文复用同一套核验口径。

---

## 🏗️ 与 `legal-hallucination-bench` 的关系

| 仓库 | 职责 |
|------|------|
| [`legal-hallucination-bench`](https://github.com/vickywu97/legal-hallucination-bench)（私有仓库，需授权访问） | 评测引擎、知识库、题库、评分逻辑 |
| **`legal-ai-watch`（本仓库）** | 自动运行评测、生成 Dashboard、发布排行榜、运营 |

本仓库的**实际评测与看板生成完全不依赖 submodule**：题库来自本仓库自带的 [`config/questions.json`](config/questions.json)，核验引擎 [`scripts/verifier.py`](scripts/verifier.py) 为本仓库自带的官方方法学实现。`legal-hallucination-bench` 仅作为**可选的题库上游源**被 [`scripts/sync_questions.py`](scripts/sync_questions.py) 引用（用于把上游最新题库同步进本仓库）；它是**私有仓库**，未授权者 `git clone` 时无需也无法拉取它，演示与评测照常可跑。

---

## 🚀 本地运行（无需 API Key 也能看 Dashboard）

```bash
# 1. 克隆（无需 submodule 即可运行演示与评测）
git clone https://github.com/vickywu97/legal-ai-watch.git
cd legal-ai-watch

# 2. 安装依赖
pip install -r requirements.txt   # 或：pip install openai requests

# 3. 生成演示数据（12 周样本，无需任何 API Key）
python scripts/seed_demo.py

# 4. 生成 Dashboard
python scripts/generate_dashboard.py --data data/ --output dashboard/

# 5. 打开 dashboard/index.html 即可查看（⚠️ 此处为 seed_demo 生成的演示数据，非真实评测）
open dashboard/index.html
```

### 真实评测（需配置 API Key）

```bash
export DEEPSEEK_API_KEY=...
export ZHIPU_API_KEY=...
export DASHSCOPE_API_KEY=...
export MOONSHOT_API_KEY=...   # Kimi 当前已退出评测池（config/models.json 置 enabled:false），此变量保留以备重新启用
python scripts/run_eval.py --date 2026-08-08 --output data/ --samples 3
python scripts/generate_dashboard.py --data data/ --output dashboard/

# 英文评测（可选，复用同一套核验引擎与规范化映射）
python scripts/run_eval.py --date 2026-08-08 --locale en --output data/ --samples 3
```

### 省钱预检流程（避免盲跑全量烧 token）

全量评测 = 题数 × 模型数 × 取样数 次**真模型 API 调用**，每次都花钱。请按下面顺序，**前两步免费/极便宜**，只有最后一步才花全量钱：

1. **本地回归门禁（免费）**：`python -m pytest tests/ -q`。CI 在付费调用前也会自动跑这一关，逻辑 bug 在本地就能抓出。
2. **密钥预检（每密钥仅 1 次极简调用）**：`python scripts/test_provider_key.py`。直接告诉你哪个密钥 401/429/缺失，**不等到跑完 279 次调用才发现**。
   - 在 Mac 上跑需先 `export` 对应密钥；或在 GitHub Actions 用下一步的 smoke 代替。
3. **smoke 烟雾测试（约 5/31 成本，不污染看板）**：在 `Actions → Manual Model Evaluation → Run workflow` 里把 **`scope` 选 `smoke`**（只跑前 5 题，真·API 端到端验证密钥+管线，但**不部署、不更新公开排行榜**）。确认各模型都拿到真实分数（而非 ✗ERR）后再走第 4 步。
4. **全量评测（full，唯一花全量钱的步骤）**：`scope` 选 `full`（默认），或本地 `python scripts/run_eval.py --date <日期> --output data/ --samples 3`。

> 经验：换密钥/加模型后，**先 smoke 再 full**，最多两次付费运行即可确认无误；不要直接盲跑 full。

---

## 📁 仓库结构

```
legal-ai-watch/
├── .github/workflows/        # 每周 & 手动评测 CI
├── config/                   # models.json / questions.json / prompts.json / statute_equivalence.json / secrets.example.yml
├── scripts/                  # run_eval / generate_dashboard / sync / social / seed
├── data/                     # answers/, leaderboard_history.json（model_metadata.json 在 config/）
├── dashboard/                # 生成的静态站点（GitHub Pages 源）
├── docs/                     # METHODOLOGY / FAQ / HOW_TO_ADD_MODEL / DEPLOY
```

---

## ➕ 请求评测新模型

在 GitHub Issues 中使用 **"Add Model Request"** 模板提交，维护者审核后加入
`config/models.json` 并手动触发一次评测。详见 [docs/HOW_TO_ADD_MODEL.md](docs/HOW_TO_ADD_MODEL.md)。

---

## 📜 许可证

[MIT](LICENSE) — 数据与方法论可自由引用，引用请注明来源 **Legal AI Watch**。

---

<p align="center">
  Built with ⚖️ by Vicky Wu · 律师 / 税务师 / 专利代理师 → AI 法律产品
</p>
