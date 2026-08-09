#!/usr/bin/env python3
"""
sync_questions.py — 从 legal-hallucination-bench 同步最新题库到 config/questions.json

支持两种来源:
  1. 本地 submodule: 读取 ../legal-hallucination-bench/.../questions.json(或 .jsonl)
  2. 远程: 通过 GitHub raw URL 拉取(需网络)

同步后运行 generate_dashboard.py 重新生成即可。本脚本只更新 config 与
data 中的题库快照, 不修改任何评测逻辑。

Usage:
  python scripts/sync_questions.py --source submodule
  python scripts/sync_questions.py --source https://raw.githubusercontent.com/vickywu97/legal-hallucination-bench/main/questions.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
SUBMODULE = ROOT / "legal-hallucination-bench"


def load_submodule_questions() -> dict | None:
    if not SUBMODULE.exists():
        return None
    # common locations inside the bench repo
    candidates = [
        SUBMODULE / "questions.json",
        SUBMODULE / "config" / "questions.json",
        SUBMODULE / "data" / "questions.json",
        SUBMODULE / "questions.jsonl",
    ]
    for c in candidates:
        if c.exists():
            if c.suffix == ".jsonl":
                rows = [json.loads(l) for l in c.read_text(encoding="utf-8").splitlines() if l.strip()]
                return {"version": "synced", "questions": rows}
            return json.loads(c.read_text(encoding="utf-8"))
    return None


def load_remote_questions(url: str) -> dict:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=30) as r:  # nosec - user-provided trusted URL
            data = r.read().decode("utf-8")
    except Exception as e:
        sys.exit(f"Failed to fetch remote questions: {e}")
    if url.endswith(".jsonl"):
        rows = [json.loads(l) for l in data.splitlines() if l.strip()]
        return {"version": "synced", "questions": rows}
    return json.loads(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="submodule",
                    help="submodule | <url> | <local path>")
    args = ap.parse_args()

    if args.source == "submodule":
        data = load_submodule_questions()
        if data is None:
            sys.exit("Submodule not found. Run `git submodule update --init` first, "
                     "or pass --source <url>.")
    elif args.source.startswith("http://") or args.source.startswith("https://"):
        data = load_remote_questions(args.source)
    else:
        p = Path(args.source)
        if not p.exists():
            sys.exit(f"Local questions file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))

    out = CONFIG / "questions.json"
    backup = CONFIG / "questions.json.bak"
    if out.exists():
        shutil.copy(out, backup)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n = len(data.get("questions", []))
    print(f"[sync] wrote {n} questions to {out}" + (f" (backup: {backup})" if out.exists() else ""))


if __name__ == "__main__":
    main()
