# Changelog — Legal AI Watch

All notable changes to the leaderboard pipeline and published reports are
recorded here. Entries are appended automatically by the weekly evaluation
workflow and manually when methodology changes.

## Format

Each line follows: `YYYY-MM-DD · <scope> · <summary>`

---

## 2026-09-01 · eval-domain · 评测域拓宽（模型轴 × 题型轴双轴）

- **模型轴：评测池 4 → 10 卡槽**。`config/models.json` 在原有 DeepSeek-R1 / Qwen-Max / GLM-4（在榜）+ Kimi-K2（限流暂停）基础上，预置 6 个国产模型卡槽并默认 `enabled:false`：**文心一言 ERNIE-4.5（百度千帆）、腾讯混元 Hunyuan-Turbo、豆包 Doubao-Pro（字节火山方舟）、阶跃 Step-2、MiniMax ABAB、百川 Baichuan4**。调用层为纯 OpenAI 兼容泛型（只 POST `api_base` + Bearer），故新增模型零代码改动，填对应 `api_key_env` Secret 并置 `enabled:true` 即自动并入评测池与排行榜。
- **题型轴：题库 31 → 39 题**。新增 qid 32–39，重点补齐此前覆盖不足的陷阱类型：**跨法张冠李戴 ×3**（公司/专利问题被错引至民法典 → `✗MA`）、**旧法时序陷阱 ×2**（《合同法》第107条 / 《民法通则》第135条诱导 → `✗T`，二者均在 `statute_equivalence.json` 的 `repealed_laws` 中）、**硬幻觉·不存在条号 ×1**（《公司法》第999条 → `✗MA`）、**超范围法律 ×2**（援引 8 部法之外的法律作答 → `✗MA`）。
- **安全校验**：全部 8 道新题的 `expected_citation` 均经 `legal-hallucination-bench` / compliance-triangle 同款 2327 节点 KB 核实真实存在；并用 `scripts/verifier.py` 本地双路径干跑——正确回答→`✓`、陷阱回答→`✗MA`/`✗T`，17 项断言全绿，未污染既有 31 题。
- **文档同步**：README 模型/题型计数（31→39、5/31→5/39）、「请求评测新模型」段补预置模型说明；`run_eval.py` 重新编译通过，无测试写死旧数量。

## 2026-08-30 · ci · gh-pages 结构重建 + footer 修正 + eval 失败兜底硬化
- **gh-pages 部署结构污染修复（真实缺陷）**：旧工作流 `cp -r data dashboard/data` 与 `generate_dashboard.py`（早已把 data/ 嵌入 dashboard/data/）冲突，造成 `dashboard/data/data/` 嵌套并泄漏 scripts/、tests/；root index.html 的相对链接 `data/`、`data/answers/` 全 404。重建 gh-pages 为干净 flatten（index.html / style.css / dashboard.js / data/ / status.json / .nojekyll），移除冗余 `cp`，并在 `generate_dashboard.py` 落 `.nojekyll`。
- **footer 意图修正**：看板页脚原误写「开源仓库 · MIT」，与 README（729fa0b）矛盾——LHB 实为**私有仓库 · 需授权访问**（license: MIT 仅指许可，非可见性）；`generate_dashboard.py` 改为 `legal-hallucination-bench（私有仓库 · 需授权访问 · Private — license: MIT）`。
- **eval 失败仍部署（韧性硬化，提交 3cf3797）**：weekly-eval.yml / manual-eval.yml 改造——评估步骤 `continue-on-error`；评估前 `git archive origin/gh-pages data` 取 last-good 兜底；失败则还原兜底并开 `eval-failed` Issue；连兜底都无 → `exit 1` 走 `alert-on-failure` 开 `ci-failure` Issue。成功路径不变，已有 12 周历史不受影响。
- 教训：跨分支操作前须 `git status` 确认工作树干净（曾因 dirty checkout 误把 flatten 提交到 main，已 `reset --hard origin/main` 恢复）。

## 2026-08-31 · docs · 可见性反转（LHB 与本仓库均改为公开）
- 用户决定 `legal-hallucination-bench` 与 `legal-ai-watch` 两个仓库**均设为公开（Public）**。
- 反转历史条目（2026-08-30「footer 意图修正」将 LHB 标为私有）：现 LHB 已公开，页脚与 README 的「私有仓库 · 需授权访问 · Private」改为「开源仓库 · MIT」。bench 仓库自身的推广/访谈文档始终以「开源基准」叙事，与此一致。
- 注：仓库可见性开关仅在 GitHub 网页 Settings 操作，本提交仅修正代码与文档中的可见性措辞；公开后评测脚本、data/、METHODOLOGY 均对外可读。

## 2026-08-17 · questions · 新增 qid31 + 核验引擎修复 + 文档计数同步
- **题库 30 → 31 题**：新增 qid 31（有限责任公司股权对外转让）——修正旧版「须经多少股东同意」题（题干沿用 2018 公司法第71条旧规则，与新法第84条已删除该前置程序不符）；新题问「其他股东享有什么权利」，预期引《公司法》第84条（书面通知 + 优先购买权），旧法第71条作 `acceptable_citations` 容错；`config/statute_equivalence.json` 新增 `company-equity-transfer` 等价组（第71条 → 第84条）。
- **核验引擎修复（真实缺陷）**：`scripts/verifier.py` 的 `acceptable_citations` 分支原逻辑「只要题目配置了可接受旧条号（Q9 第43条 / Q10 第177条 / Q31 第71条），无论模型实际引注为何均判 ✓」，掩盖幻觉、压低 HVI；改为必须模型**实际引注**该可接受条文（或归一化到其 canonical）才判 ✓。新增 2 个回归测试锁定（共 18 个 verifier 测试通过）。
- **文档计数同步（30 → 31）**：README、VERIFICATION_CHECKLIST（补第 31 行）、GROUND_TRUTH_REVIEW 结论、METHODOLOGY（样本点 270 → 279、KPI 口径 0–31）统一更新；`dashboard/status.json` 与 `dashboard/data/` 由 `generate_dashboard.py` 按 `len(questions)` 自动生成，无需手改。
- 提交：`241af25`（已推送 origin/main）。

## 2026-08-13 · docs · 全局一致性排查 + DEPLOY.md
- **新增 docs/DEPLOY.md**：推送排错（SSH-over-443）、CI 架构（只发 gh-pages）、手动/每周触发、取样管线、等价引注闸门、本地预览、常见故障表、密钥清单，一页式运维手册。
- **全局一致性修复（一次性，不再打补丁）**：
  - 修正 `model_metadata.json` 位置文档错误：README 与 HOW_TO_ADD_MODEL 原写 `data/`，实际在 `config/`（Dashboard 读 config/ 并内联）。
  - `seed_demo.py` 移除已退出的 Kimi，演示模型集与线上启用集（3 模型）对齐。
  - `sync_questions.py` 新增本地策展保留：同步上游题库时按 qid 合并回 `acceptable_citations`/`verifiable`，避免无声覆盖我们手搓的等价引注论证（Q5/Q9/Q10）。
  - `generate_dashboard.py` 标题「近 12 周 HVI 趋势」改为「HVI 趋势」（线上历史仅 2 周，避免误导）。
  - FAQ Q7、METHODOLOGY §2 补多次取样交叉引用（对齐 §8）。
  - README 移除不存在的 `archive/` 目录说明；`run_eval` 示例补 `--samples 3`；MOONSHOT 变量标注 Kimi 已退出。
- 已本地非破坏性验证：seed 仅生成 3 模型/12 周；sync 合并后 acceptable_citations 保留。

## 2026-08-13 · fix · 公司法旧条号等价引注（Q9/Q10 假阳性修复）
- **问题**：GLM-4 在 Q9 引《公司法》第四十三条、Q10 引第一百七十七条，均为 2018 旧公司法条号，但实质与 2023 新法第66条（修改章程特别决议2/3）、第224条（减资债权人保护30日）完全相同；旧口径以「新法条号唯一正解」把它们记成 ✗MA，致 GLM HVI 虚高约 20 个百分点。
- **修复**：仿 Q5 给 Q9、Q10 补 `acceptable_citations`（旧条号 + justification，论证条号版本差异而非幻觉），`verify_local` 的 `{expected} ∪ {acceptable}` 并集匹配自动放过。真错（如 Q8 引专利法第15条）不受影响，仍判 ✗MA。
- 已本地验证：GLM 旧条号回答判 ✓，错引（Q9 第99条 / Q10 第50条）仍 ✗MA，无过度放行。
- METHODOLOGY §7.3 新增「条号版本差异」等价类型。

## 2026-08-13 · methodology · 多次取样抑制非确定性 + Kimi 退出评测池
- **多次取样方差控制**：每题每模型取样 N 次（默认 3，`--samples` 可调），逐题展示多数判定、矩阵 cell 标注取样占比；HVI/CRFI/分领域 HVI 改为跨全部取样汇总（错引样本数 ÷ 含引注样本数），把跨轮非确定性（实测同题隔轮 HVI 波动）摊薄，提升榜单可复现性。见 METHODOLOGY §8。
- **Kimi-K2 退出评测池**：Moonshot API 持续 429 限流、难以获得稳定回答，于 `config/models.json` 置 `enabled:false`；`model_metadata.json` 同步移除。新一期历史模型列表仅含 DeepSeek-R1 / Qwen-Max / GLM-4。
- 工作流新增 `samples` 输入（manual）并显式传参（weekly 固定 3）；其余 CI 行为不变。

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
- **真实错引仍被捕获**：错引不同条号（如《专利法》第13条 vs 第15条、《公司法》第66条 vs 第43条、第224条 vs 第177条）仍判 ✗；《营改增试点实施办法》第25条系「准予抵扣」正向列举、与第10条方向相反非等价，维持 ✗；而第27条（「不得抵扣」负面清单）为第10条等价引注，见下方 acceptable_citations 条目。
- 影响：本版修正后，首轮真实数据中的 Q2(DeepSeek)、Q7(GLM-4) 由误判 ✗MA 转为 ✓；DeepSeek HVI 由 25%→约 12.5%，GLM-4 由 40%→约 30%。需重新运行 Manual Model Evaluation 以刷新榜单。

## 2026-08-11 · feature · acceptable_citations：等价引注认定（方案B）
- **题库新增 `acceptable_citations` 字段**：每题除首选 `expected_citation` 外，可列出经论证的等价引注，每条须带 `justification`（等价性论证门槛）。以 Q5 为例，接受《营改增试点实施办法》第27条作为《增值税暂行条例》第10条的等价替代（第27条以负面清单逐项列举「不得抵扣」情形，与第10条规制对象相同；第25条系「准予抵扣」正向列举，方向相反，不纳入等价）。
- **引擎改为并集匹配**：`verify_local` 现对 `{expected_citation} ∪ {acceptable_citations}` 取并集，命中任一即判 ✓；审计明细附 `justification` 以便追溯。空 `acceptable_citations` 退化为单预期。
- **方法论补 §7 等价引注认定标准**：明确三种可认定等价的情形（法律渊源替换 / 新旧法替换 / 法条拆合）与 justification 必填要求，将"专业判断"固化为评测设计的一部分。
- 影响：DeepSeek-R1 在 Q5 命中等价引注 → HVI 由约 12.5%→**0%**（完全干净，证明其在税法域引注精准且更贴近现行细则）。需重新运行 Manual Model Evaluation 以刷新榜单。

## 2026-08-12 · fix · 纠正 Q5 等价引注条号（第25条 → 第27条）
- **条号笔误纠正**：Q5 的 `acceptable_citations` 原误写为《营改增试点实施办法》**第25条**，但该条系「准予抵扣」正向列举，与题目「不得抵扣」方向相反，实为反义而非等价。正确的等价引注是**第27条**（「不得抵扣」负面清单，与《增值税暂行条例》第10条规制对象完全相同）。该笔误源自已采纳的 Q5 设计示例，本轮一并修正。
- **连带纠正**：`docs/METHODOLOGY.md` §7.2 示例与 §7.3 表格中的「第25条」同步改为「第27条」；`run_eval.py` 文档引用的章节号由 §8 修正为 §7。`docs/METHODOLOGY.md` 版本日期同步更新为 2026-08-12。
- **本地验证**：Q5 模型引第27条 → ✓（带 justification）；引第25条 → 维持 ✗MA（真实错误）；引 target 直接命中 → ✓。
- 影响：上一轮真实评测中 Qwen-Max 引《营改增试点实施办法》第27条被错杀为 ✗MA，本版修正后该题为 ✓，Qwen HVI 由 30%→**20%**（与 DeepSeek 并列最佳档）。需重新运行 Manual Model Evaluation 以刷新榜单。

## 2026-08-14 · refactor · v2.0 核验引擎与指标体系统一重构
- **确定性核验引擎 `scripts/verifier.py`（取代 `verify_local` / bench 回退分支）**：线上实际运行的是本仓库自带的确定性引擎，与 bench 知识库版本一致，不再有「bench 缺失→回退」的不确定性。引注解析支持中文 `《xxx》第N条` 与英文 `Article N of the Civil Code` / `Civil Code Article N` 两种形态（英文法名须以 Act/Code/Law 结尾并归一化到中文法名）。
- **规范化引注映射 `config/statute_equivalence.json`**：单一事实源，覆盖跨法等价（增值税暂行条例第10条 ↔ 营改增27条 ↔ 增值税法22条）、跨版本等价（2018 公司法 43/177/33/13 ↔ 2023 公司法 66/224/57/10）与 13 项已废止法律清单。新增等价关系改一份 JSON 全局生效，`acceptable_citations` 退居「偶发特例」的逐题覆盖角色，每条仍须带 `justification`。
- **指标体系统一重构**：HVI = wrong/(correct+wrong)、CRFI = correct/(correct+wrong)；**新增 Coverage / Integrity**（分母纳入 `nocite`，「装死不答」不再被静默豁免）、**Temporal**（✗T ÷ 有效引注）；API 失败（✗ERR）单列 `api_errors`，不混入任何模型行为分母。
- **时态幻觉 ✗T 单列**：模型引已废止法（如该用《民法典》却引《合同法》）判 `✗T`，区别于「编造法条」✗MA；题库以 `temporal_trap: true` 标记陷阱题分维度统计。
- **中英双语评测**：`config/prompts.json` 版本化存放中英文系统提示词；题库每题含 `prompt_en`；`run_eval.py --locale {zh,en}` 切换；中英文复用同一套核验口径。
- **题库扩充**：10 → 30 题，覆盖民法/刑法/税法/专利/公司法/数据合规/竞争法，全题双语，含 3 道时态陷阱题。
- **调用健壮性**：`call_model` 加 429/5xx/网络/非 JSON → 指数退避重试（尊重 Retry-After），401/403/404 快速失败；耗尽 → `ModelCallError` → ✗ERR。
- **回归测试 + CI 闸门**：新增 `tests/`（verifier / metrics / retry，27 项）；workflow 在跑 API 前先跑 `pytest`，失败阻断部署；新增 `alert-on-failure` job，评测失败时开（或追加评论到）`ci-failure` 标签 Issue。
- **Dashboard 增强**：输出 `status.json` 新鲜度标记（>14 天过期提示）、与上期对比 diff 视图、矩阵 cell 点击展开逐题原始回答下钻。
- **修复**：Temporal 指标分母曾把 ✗T 重复计入（`temporal/(total_cited+temporal)`），修正为 `temporal/total_cited`，并补专项测试锁定。
- 影响：需重新运行 **Manual Model Evaluation**（30 题）以用新引擎/新指标刷新榜单；历史周数据会因指标定义变化而不可与新口径直接比较。

<!-- NEW ENTRIES APPENDED ABOVE THIS LINE BY THE WEEKLY WORKFLOW -->
