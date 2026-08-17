#!/usr/bin/env python3
"""
test_provider_key.py — 本地快速验证各模型 API 密钥是否有效（刷新 GitHub Secret 前自测用）。

为什么需要它：
  本仓库的 GitHub Actions 评测依赖 4 个密钥（DEEPSEEK_API_KEY / ZHIPU_API_KEY /
  DASHSCOPE_API_KEY / MOONSHOT_API_KEY）。若其中某个密钥过期或额度用尽，评测会整轮
  失败（✗ERR）。本脚本在「你自己的 Mac」上用同样的 models.json 配置发一次最小调用，
  直接告诉你哪个密钥 OK、哪个 401/429/404，省得盲跑一轮 Actions 才发现问题。

用法:
  # 设置环境变量后运行（变量名与 CI 完全一致）
  export DASHSCOPE_API_KEY="sk-xxxx"
  export DEEPSEEK_API_KEY="sk-xxxx"
  python scripts/test_provider_key.py
  # 只测某个供应商
  DASHSCOPE_API_KEY=sk-xxxx python scripts/test_provider_key.py --only qwen
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

try:
    import requests
except ImportError:
    print("需要 requests: pip install requests")
    sys.exit(2)


def load_models():
    return json.loads((CONFIG_DIR / "models.json").read_text(encoding="utf-8"))["models"]


def test_one(model: dict, api_key: str) -> tuple[str, str]:
    """返回 (status, message)。status in {OK, MISSING, HTTP_xxx, ERR}。"""
    if not api_key:
        return "MISSING", f"环境变量 {model['api_key_env']} 未设置"
    payload = {
        "model": model["model"],
        "messages": [{"role": "user", "content": "你好，请只回复“OK”两个字。"}],
        "temperature": 0.0,
        "max_tokens": 16,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        resp = requests.post(model["api_base"], json=payload, headers=headers, timeout=30)
        if resp.status_code == 200:
            try:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                txt = resp.text[:60]
            return "OK", f"HTTP 200，模型返回: {txt[:40]!r}"
        return f"HTTP_{resp.status_code}", f"HTTP {resp.status_code}: {resp.text[:160]}"
    except Exception as e:
        return "ERR", f"请求异常: {e}"


def main():
    ap = argparse.ArgumentParser(description="本地验证模型 API 密钥有效性")
    ap.add_argument("--only", default="", help="只测 id 含该关键字的模型（如 qwen）")
    args = ap.parse_args()

    models = [m for m in load_models() if m.get("enabled", True)]
    if args.only:
        models = [m for m in models if args.only.lower() in m["id"].lower()]
    if not models:
        print("没有匹配的已启用模型。")
        return

    print(f"将测试 {len(models)} 个模型的密钥（变量名与 CI 一致）...\n")
    all_ok = True
    for m in models:
        env = m["api_key_env"]
        key = os.environ.get(env, "")
        status, msg = test_one(m, key)
        if status == "OK":
            tag = "✅"
        elif status == "MISSING":
            tag = "⚠️ "
            all_ok = False
        else:
            tag = "❌"
            all_ok = False
        print(f"{tag} {m['id']:14s} [{env}] -> {status}: {msg}")
    print()
    if all_ok:
        print("全部密钥有效 ✅ 可直接在 GitHub Actions 重跑评测。")
    else:
        print("存在无效/缺失密钥 ⚠️  请到对应厂商控制台复核，并更新 GitHub 仓库")
        print("Settings -> Secrets -> Actions 中的对应 Secret，再重跑评测。")


if __name__ == "__main__":
    main()
