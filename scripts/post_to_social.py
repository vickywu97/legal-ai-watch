#!/usr/bin/env python3
"""
post_to_social.py — (可选) 每周评测后自动发布社交媒体摘要

默认禁用。配置好对应密钥 (见 config/secrets.example.yml) 后, 在 weekly-eval.yml
末尾增加一步调用本脚本即可。

支持目标 (按环境变量开关):
  - Twitter/X  : 需要 TWITTER_API_KEY / TWITTER_API_SECRET (v2 需 bearer + access token)
  - LinkedIn   : 需要 LINKEDIN_ACCESS_TOKEN
  - 知乎        : 需要 ZHIHU_COOKIE (非官方接口, 稳定性不保证, 谨慎使用)

本脚本只负责「拼装并发送一条文本摘要」, 不存储任何凭证, 凭证全部来自环境变量。

Usage:
  python scripts/post_to_social.py --date 2026-08-08 --data data/ --platforms twitter,linkedin
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data"


def build_summary(data_root: Path, eval_date: str) -> str:
    history_path = data_root / "leaderboard_history.json"
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {"history": []}
    latest = None
    for h in history.get("history", []):
        if h["date"] == eval_date:
            latest = h
            break
    if latest is None and history.get("history"):
        latest = history["history"][-1]
    if not latest:
        return "Legal AI Watch: 本周评测数据暂未生成。"

    lb = latest["leaderboard"]
    lines = [f"⚖️ Legal AI Watch 周报 ({latest['date']}) — 法律大模型法条引注幻觉率 HVI:", ""]
    for r in lb:
        lines.append(f"  #{r['rank']} {r['model']}: HVI {r['hvi']*100:.0f}% (引注 {r['citations']})")
    lines.append("")
    lines.append("完整排行榜与趋势: https://vickywu97.github.io/legal-ai-watch")
    lines.append("#法律AI #大模型评测 #LegalAIWatch")
    return "\n".join(lines)


def post_twitter(text: str):
    key = os.environ.get("TWITTER_API_KEY")
    if not key:
        print("[social] TWITTER_API_KEY 未配置, 跳过 Twitter。")
        return False
    # NOTE: Twitter v2 API requires OAuth2 bearer + access token. This is a stub
    # that documents the integration point; implement per your app's auth flow.
    print("[social] [stub] would post to Twitter:\n" + text)
    return True


def post_linkedin(text: str):
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        print("[social] LINKEDIN_ACCESS_TOKEN 未配置, 跳过 LinkedIn。")
        return False
    print("[social] [stub] would post to LinkedIn:\n" + text)
    return True


def post_zhihu(text: str):
    cookie = os.environ.get("ZHIHU_COOKIE")
    if not cookie:
        print("[social] ZHIHU_COOKIE 未配置, 跳过知乎。")
        return False
    print("[social] [stub] would post to 知乎 (非官方接口):\n" + text)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--platforms", default="twitter,linkedin", help="comma-separated")
    args = ap.parse_args()

    summary = build_summary(Path(args.data), args.date)
    print("==== Weekly summary ====")
    print(summary)
    print("=======================")

    targets = {p.strip().lower() for p in args.platforms.split(",") if p.strip()}
    if "twitter" in targets:
        post_twitter(summary)
    if "linkedin" in targets:
        post_linkedin(summary)
    if "zhihu" in targets:
        post_zhihu(summary)


if __name__ == "__main__":
    main()
