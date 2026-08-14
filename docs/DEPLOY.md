# 部署与运维手册 (DEPLOY)

> 面向维护者。涵盖：推送排错、CI 架构、如何触发评测、取样管线、常见故障。
> 方法论细节见 [METHODOLOGY.md](METHODOLOGY.md)；新增模型见 [HOW_TO_ADD_MODEL.md](HOW_TO_ADD_MODEL.md)。

---

## 1. 仓库架构（务必先读）

```
legal-ai-watch/
├── config/                 # 受版本控制（"纯源码"）
│   ├── models.json          # 被测模型 + enabled 开关
│   ├── model_metadata.json  # 厂商/版本/参数量（Dashboard 元数据来源）
│   ├── questions.json       # 题库（含 prompt_en / acceptable_citations / temporal_trap）
│   ├── prompts.json          # 中英文系统提示词（版本化，不再硬编码）
│   └── statute_equivalence.json  # 规范化引注映射（跨法/跨版本等价 + 废止法清单）
│   └── secrets.example.yml  # 密钥模板
├── scripts/                # 评测/生成/同步/演示脚本
├── .github/workflows/      # manual-eval.yml（手动）/ weekly-eval.yml（每周一）
├── docs/                   # METHODOLOGY / FAQ / HOW_TO_ADD_MODEL / 本文件
├── data/                   # ← 生成物，gitignore，仅存在于本地与 gh-pages
└── dashboard/              # ← 生成物，gitignore，GitHub Pages 源
```

**关键约定：`main` 永远是纯源码。**
`data/` 与 `dashboard/` 是评测生成物，**不提交到 `main`**，只在 CI 里发布到
`gh-pages` 分支。这样：
- 不会出现「workflow 往 main 写生成物 → 本地 push 被拒（fetch first）」的死循环；
- 趋势历史跨周累积靠从 `gh-pages` 拉回 `data/leaderboard_history.json` 再追加。

---

## 2. 本地推送排错（中国大陆 GitHub 访问）

### 症状
```
git push origin main
fatal: unable to access 'https://github.com/...': Empty reply from server
```
或 `LibreSSL SSL_connect: Operation timed out` / `HTTP2 framing layer` 类错误。
多为 GitHub HTTPS 被中间网络 reset / 限速，非账号或协议问题。

### 解法 A（推荐）：SSH 走 443
GitHub 的 SSH 端口 22 常被封，但 443 通常可达。

1. 写 `~/.ssh/config`（Mac 终端执行）：
   ```bash
   cat >> ~/.ssh/config <<'EOF'
   Host github.com
     Hostname ssh.github.com
     Port 443
     User git
   EOF
   chmod 600 ~/.ssh/config
   ```
2. 把仓库 remote 改为 SSH：
   ```bash
   git remote set-url origin git@github.com:vickywu97/legal-ai-watch.git
   ```
3. 验证鉴权（首次会提示把 `ssh.github.com` 加入 known_hosts，输入 yes）：
   ```bash
   ssh -T git@github.com
   # 成功显示：Hi vickywu97! You've successfully authenticated, ...
   ```
4. 推送：
   ```bash
   git push origin main
   ```
   若 `ssh -T` 报 `publickey denied`：把 `~/.ssh/id_ed25519.pub` 内容加到
   GitHub → Settings → SSH and GPG keys（本机无法代登）。

### 解法 B（备选）
- 代理：`git config --global http.proxy http://127.0.0.1:7890`
- 或手机热点（绕开当前网络出口）。

> push 失败**不会丢提交**（仍在本地分支）。先 `git status -sb` 确认 ahead 数，重试即可。

---

## 3. 触发评测（出榜）

### 手动评测（随时）
GitHub → Actions → **Manual Model Evaluation** → **Run workflow**，可选输入：
- `date`：评测日期（留空=今天）
- `models`：逗号分隔的模型 id（留空=全部启用模型）
- `samples`：每题每模型取样次数（默认 3，越高越稳、越慢越贵）

### 每周评测（自动）
`weekly-eval.yml` 定时 `cron: '0 0 * * 1'`（每周一 00:00 UTC = 北京时间 08:00），
也支持 `workflow_dispatch` 手动触发。流程：
1. checkout（含 bench submodule，best-effort）
2. 安装依赖并跑 **`pytest` 回归闸门**（失败则直接阻断部署——避免坏掉的核验器静默污染榜单）
3. `sync_questions.py` 从 submodule 同步题库（best-effort，失败仅跳过）
4. 从 `gh-pages` 拉回历史 → `run_eval.py --samples 3` → 生成 `data/`
5. `generate_dashboard.py` 生成自包含 `dashboard/`（含 `status.json` 新鲜度标记）
6. `peaceiris/actions-gh-pages@v3` 仅发布到 `gh-pages`

> 两个 workflow 都**只部署 gh-pages，不向 main 提交**。
> 评测 job 失败时，会由独立的 `alert-on-failure` job 在仓库开（或追加评论到）一个
> 带 `ci-failure` 标签的 Issue，提醒维护者榜单可能已过期——避免「静默失败、无人知晓」。

---

## 4. 取样管线（抑制非确定性）

即便 `temperature=0`，主流大模型同题跨轮仍可能从「命中引注」翻成「未作答」或「错引」，
导致 HVI 波动。做法（详见 METHODOLOGY §8）：

- 每题每模型取样 `N` 次（默认 3）；
- 逐题诊断矩阵展示**多数判定**，cell tip 标注「k/n 取样正确/错引」；
- HVI / CRFI / 分领域 HVI 跨**全部**取样汇总，方差摊薄、跨轮稳定。

本地复现：
```bash
export DEEPSEEK_API_KEY=... ZHIPU_API_KEY=... DASHSCOPE_API_KEY=...
python scripts/run_eval.py --date 2026-08-13 --output data/ --samples 3
python scripts/generate_dashboard.py --data data/ --output dashboard/
```

---

## 5. 等价引注与时态幻觉认定

核验引擎为 `scripts/verifier.py`，通过两层机制决定「模型引注是否命中预期」，避免把
「实质正确 / 更精准」的引注机械判错（详细见 METHODOLOGY §7）：

1. **主机制 — `config/statute_equivalence.json`（规范化映射）**：结构化、可审计的单一事实源。
   覆盖跨法等价（增值税暂行条例第10条 ↔ 营改增实施办法第27条 ↔ 增值税法第22条）、
   跨版本等价（2018 公司法 43/177/33/13 条 ↔ 2023 公司法 66/224/57/10 条）以及
   13 项已废止法律清单（合同法、婚姻法等，用于识别时态幻觉 ✗T）。新增一个等价关系改一份
   JSON 即可全局生效，无需逐题手写。
2. **次机制 — `config/questions.json` 的 `acceptable_citations`**：仅保留无法纳入系统性等价、
   但经出题人论证确属正确的偶发特例，每条须带 `justification`。逐题覆盖，与规范化映射取并集。

**重要**：`weekly-eval.yml` 会跑 `sync_questions.py` 同步上游题库。该脚本已做
**本地策展保留**——同步时自动把现有 `acceptable_citations` / `verifiable` /
`prompt_en` / `temporal_trap` 按 qid 合并回去，不会因同步上游而丢失我们手搓的等价引注论证。

> 不再存在「bench 核验器缺失 → 回退到仓库内 `verify_local`」的分支：本仓库的
> `verifier.py` 即为线上实际运行的确定性核验引擎，与 bench 知识库版本保持一致。

---

## 6. 本地预览（无需 API Key）

```bash
python scripts/seed_demo.py                 # 生成 12 周演示数据（含 3 个启用模型）
python scripts/generate_dashboard.py --data data/ --output dashboard/
open dashboard/index.html
```
演示数据**不代表真实表现**，仅用于本地看页面。正式数据由 CI 调真实 API 覆盖。

---

## 7. 常见故障

| 现象 | 原因 | 处理 |
|------|------|------|
| `Empty reply from server` / timeout | GitHub HTTPS 被 reset | 见 §2 切 SSH-over-443 |
| `fetch first` 后 push 被拒 | 旧 workflow 往 main 写生成物 | 已通过「只发 gh-pages」根除；不要改回向 main 提交 |
| `Node.js 20 is deprecated` 警告 | action 被 runner 强制跑 Node 24 | **无害**，构建成功；等 action 作者升级声明即消失，我侧无开关 |
| Kimi 全题 429 / 未作答 | Moonshot 持续限流 | Kimi 已 `enabled:false` 退出评测池；`MOONSHOT_API_KEY` 保留以备重新启用 |
| 某题被判 ✗MA 但引用看起来对 | 可能条号版本差异/等价源 | 在 `config/statute_equivalence.json` 加规范化组（§5），或给该题补 `acceptable_citations`，重跑 |
| `pytest` 闸门失败、未部署 | 核验/指标/重试逻辑回归 | 看 pytest 输出，修正 `scripts/verifier.py` / `run_eval.py` / `tests/`，再重跑 Manual Model Evaluation |
| 出现带 `ci-failure` 标签的 Issue | 评测 job 失败 | 看对应 Actions run 日志；修复后重跑，Issue 会自动追加评论 |
| Dashboard 顶部「数据已过期」 | 超过 14 天未成功出榜 | 检查 `alert-on-failure` Issue 与 weekly 工作流是否失败 |
| Dashboard 趋势图空 | 历史仅 1 周 | 正常，≥2 周才出折线 |

---

## 8. 密钥（GitHub Actions Secrets）

仓库 `Settings → Secrets and variables → Actions` 需配置：
`DEEPSEEK_API_KEY` / `ZHIPU_API_KEY` / `DASHSCOPE_API_KEY`
（Kimi 退出后 `MOONSHOT_API_KEY` 可留空）。

可选社交发布：`POST_SOCIAL=true` + `TWITTER_API_KEY` / `LINKEDIN_ACCESS_TOKEN`
（当前 `post_to_social.py` 为 stub，仅打印摘要，未真实发帖）。
