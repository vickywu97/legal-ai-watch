# 如何新增一个被测模型 (HOW_TO_ADD_MODEL)

本指南面向维护者。新增模型只需改一个配置文件 + 触发一次评测。

---

## 步骤 1：在 `config/models.json` 添加模型

复制下面模板，填入新模型信息。关键是 `provider` / `api_base` / `model` /
`api_key_env` 四项，需与该模型的 **OpenAI 兼容** 接口一致。

```json
{
  "id": "My-Legal-LLM",
  "display_name": "My-Legal-LLM",
  "vendor": "厂商名",
  "provider": "openai-compatible",
  "api_base": "https://api.example.com/v1/chat/completions",
  "model": "model-id",
  "api_key_env": "MY_LLM_API_KEY",
  "context_window": 32768,
  "enabled": true
}
```

> `run_eval.py` 目前对所有 provider 统一走 OpenAI 兼容的 `/chat/completions`
> 协议。若某厂商协议不同，请在 `call_model()` 中扩展分支。

## 步骤 2：配置 API Key

二选一：

- **GitHub Actions（推荐，用于正式周榜）**：仓库
  `Settings → Secrets and variables → Actions → New repository secret`，
  名称填 `MY_LLM_API_KEY`（即上一步的 `api_key_env`），值为密钥。
- **本地**：将 `config/secrets.example.yml` 复制为 `config/secrets.yml`
  （已被 gitignore），在对应行填入；或在 shell 中 `export MY_LLM_API_KEY=...`。

## 步骤 3：触发评测

- 正式加入周榜：提交 `models.json` 改动到 `main`，下个周一自动纳入；或立即在
  Actions 页面手动运行 **Manual Model Evaluation**。
- 仅本地验证：
  ```bash
  export MY_LLM_API_KEY=...
  python scripts/run_eval.py --date 2026-08-08 --output data/
  python scripts/generate_dashboard.py --data data/ --output dashboard/
  ```

## 步骤 4：更新元数据（可选但推荐）

在 `data/model_metadata.json` 补充厂商 / 版本 / 参数量 / 上下文窗口，
Dashboard 排行榜会展示这些信息。

## 步骤 5：记录变更

在 `CHANGELOG.md` 追加一行，例如：
```
2026-08-15 · model · 新增 My-Legal-LLM 进入周榜评测
```

---

## 社区请求通道

普通用户无需直接改仓库：在 GitHub Issues 使用 **Add Model Request** 模板提交，
由维护者按上述流程加入。请在模板中说明 API 接入方式，**切勿在公开 Issue 中粘贴密钥**。
