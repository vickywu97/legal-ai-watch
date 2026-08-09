# ⚖️ Legal AI Watch

> 中国法律大模型「法条引注幻觉率」每周自动监测排行榜
> **Automated weekly benchmark of Chinese legal LLMs' citation-hallucination rates**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Live Dashboard](https://img.shields.io/badge/Dashboard-GitHub%20Pages-blue)](https://vickywu97.github.io/legal-ai-watch)
[![Updated](https://img.shields.io/badge/updated-weekly-brightgreen)](https://github.com/vickywu97/legal-ai-watch/actions)

**Legal AI Watch** 全自动、零成本、每周更新地评测主流国产法律大模型的
「法条引注幻觉率」（HVI），公开排行榜、追踪趋势变化，并生成可视化报告。
整个流程由 GitHub Actions 驱动，零人工干预。

🌐 **Live Dashboard:** https://vickywu97.github.io/legal-ai-watch

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
| **HVI** | 引注幻觉率 = 幻觉引注数 / 总引注数（主排行榜指标，越低越好）|
| **CRFI** | 可验证引注覆盖率（Correct & Retrievable Fraction of Citations）|
| **时序幻觉率** | 涉及生效时间/修订版本的引注中出错的比例 |
| **引注数** | 该模型本轮被抽样的有效法条引注总数 |

判定子类（逐题矩阵中使用）：
- `✓` 引注真实且内容正确
- `✗MA` 法条不存在 / 编造（Made-up Article）
- `✗NF` 法条存在但内容不符（Not Faithful）
- `✗F` 事实性错误
- `?` 无法判定（知识库未覆盖）
- `·` 未作答

---

## 🏗️ 与 `legal-hallucination-bench` 的关系

| 仓库 | 职责 |
|------|------|
| [`legal-hallucination-bench`](https://github.com/vickywu97/legal-hallucination-bench) | 评测引擎、知识库、题库、评分逻辑 |
| **`legal-ai-watch`（本仓库）** | 自动运行评测、生成 Dashboard、发布排行榜、运营 |

本仓库作为 **git submodule** 引入 bench 引擎，只消费其稳定版本，不修改评测逻辑。

---

## 🚀 本地运行（无需 API Key 也能看 Dashboard）

```bash
# 1. 克隆（含 submodule）
git clone --recurse-submodules https://github.com/vickywu97/legal-ai-watch.git
cd legal-ai-watch

# 2. 安装依赖
pip install -r requirements.txt   # 或：pip install openai requests

# 3. 生成演示数据（12 周样本，无需任何 API Key）
python scripts/seed_demo.py

# 4. 生成 Dashboard
python scripts/generate_dashboard.py --data data/ --output dashboard/

# 5. 打开 dashboard/index.html 即可查看
open dashboard/index.html
```

### 真实评测（需配置 API Key）

```bash
export DEEPSEEK_API_KEY=...
export ZHIPU_API_KEY=...
export DASHSCOPE_API_KEY=...
export MOONSHOT_API_KEY=...
python scripts/run_eval.py --date 2026-08-08 --output data/
python scripts/generate_dashboard.py --data data/ --output dashboard/
```

---

## 📁 仓库结构

```
legal-ai-watch/
├── .github/workflows/        # 每周 & 手动评测 CI
├── config/                   # models.json / questions.json / secrets.example.yml
├── scripts/                  # run_eval / generate_dashboard / sync / social / seed
├── data/                     # answers/, leaderboard_history.json, model_metadata.json
├── dashboard/                # 生成的静态站点（GitHub Pages 源）
├── docs/                     # METHODOLOGY / FAQ / HOW_TO_ADD_MODEL
└── archive/                  # 历史报告归档
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
