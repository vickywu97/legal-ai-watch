"""Tests for run_evaluation's key-handling / fail-fast behavior.

These guard the robustness hardening added so a dead API key does not silently
pollute the public leaderboard with 90 empty ✗ERR rows:
  * missing key  -> model skipped entirely (no API calls)
  * auth error (401/403/404) -> fail-fast for the whole model after 1st call
"""
import json
from pathlib import Path

import pytest

from run_eval import ModelCallError, run_evaluation

KEY_ENVS = ["DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY"]

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
N_MODELS = sum(1 for m in json.loads((CONFIG_DIR / "models.json").read_text(encoding="utf-8"))["models"]
               if m.get("enabled", True))
N_QUESTIONS = len(json.loads((CONFIG_DIR / "questions.json").read_text(encoding="utf-8"))["questions"])


def _set_keys(monkeypatch, values: dict):
    for env in KEY_ENVS:
        monkeypatch.setenv(env, values.get(env, ""))


def test_missing_key_skips_model(tmp_path, monkeypatch):
    """All keys empty -> every model skipped, no API call made, empty leaderboard."""
    calls = []

    def fake_call(model_cfg, prompt, api_key, system_prompt, **kw):
        calls.append(model_cfg["id"])
        return "未引用任何法条的回答。"

    monkeypatch.setattr("run_eval.call_model", fake_call)
    _set_keys(monkeypatch, {e: "" for e in KEY_ENVS})

    results = run_evaluation("2026-08-17", tmp_path, samples=1)

    assert results == []          # 没有可用密钥 -> 榜单为空
    assert calls == []            # 且不应发起任何 API 调用


def test_auth_error_failfast(tmp_path, monkeypatch):
    """A 401 on the first question should abort the model after exactly 1 call,
    and every question should still be recorded as ✗ERR (api_errors == 30)."""
    state = {"n": 0}

    def fake_call(model_cfg, prompt, api_key, system_prompt, **kw):
        state["n"] += 1
        raise ModelCallError(f"{model_cfg['id']} HTTP 401 (auth/config error, not retried)")

    monkeypatch.setattr("run_eval.call_model", fake_call)
    _set_keys(monkeypatch, {e: "dummy" for e in KEY_ENVS})

    results = run_evaluation("2026-08-17", tmp_path, samples=1)

    assert state["n"] == N_MODELS                 # 每模型首题 1 次调用即 fail-fast
    assert all(r["hvi"] is None for r in results)
    assert all(r["api_errors"] == N_QUESTIONS for r in results), results
    assert all(r["rank"] is None for r in results)


def test_429_not_failfast(tmp_path, monkeypatch):
    """A rate-limit (429) should NOT abort the model (transient); every question
    is still attempted and recorded as ✗ERR (api_errors == 30)."""
    state = {"n": 0}

    def fake_call(model_cfg, prompt, api_key, system_prompt, **kw):
        state["n"] += 1
        raise ModelCallError(f"{model_cfg['id']} HTTP 429 after retries")

    monkeypatch.setattr("run_eval.call_model", fake_call)
    _set_keys(monkeypatch, {e: "dummy" for e in KEY_ENVS})

    results = run_evaluation("2026-08-17", tmp_path, samples=1)

    # 全部题 × 全部模型，每题 1 次调用（429 不 fail-fast）
    assert state["n"] == N_MODELS * N_QUESTIONS
    assert all(r["api_errors"] == N_QUESTIONS for r in results)
