"""Tests for call_model's retry / backoff policy.

Guarantees (this is what previously killed Kimi and could silently distort
any model's weekly data):
  * 429 / 5xx are RETRIED with backoff (not fail-fast)
  * 401 / 403 / 404 are FAIL-FAST (auth/config, no point retrying)
  * network errors (ReadTimeout) are RETRIED
  * non-JSON body is RETRIED (transient gateway glitch)
  * exhaustion raises ModelCallError (caller then records an explicit ✗ERR)
"""
from unittest import mock
from requests.exceptions import ReadTimeout

from run_eval import ModelCallError, call_model


def _cfg():
    return {"id": "T", "model": "m", "api_base": "http://x", "api_key_env": "X",
            "max_tokens": 2048}


def _ok(text="hi"):
    m = mock.Mock()
    m.status_code = 200
    m.headers = {}
    m.json.return_value = {"choices": [{"message": {"content": text}}]}
    return m


def _resp(status, headers=None):
    m = mock.Mock()
    m.status_code = status
    m.headers = headers or {}
    m.json.return_value = {"choices": [{"message": {"content": "x"}}]}
    return m


def test_429_retries_then_succeeds():
    cfg = _cfg()
    with mock.patch("requests.post", side_effect=[_resp(429), _resp(429), _ok("ok")]) as mp, \
         mock.patch("run_eval.time.sleep"):
        out = call_model(cfg, "p", "k", "sys", max_retries=5)
    assert out == "ok"
    assert mp.call_count == 3


def test_5xx_retries_then_succeeds():
    cfg = _cfg()
    with mock.patch("requests.post", side_effect=[_resp(503), _ok("ok")]) as mp, \
         mock.patch("run_eval.time.sleep"):
        out = call_model(cfg, "p", "k", "sys", max_retries=5)
    assert out == "ok"


def test_401_fail_fast():
    cfg = _cfg()
    with mock.patch("requests.post", return_value=_resp(401)), \
         mock.patch("run_eval.time.sleep"):
        try:
            call_model(cfg, "p", "k", "sys")
            assert False, "expected ModelCallError"
        except ModelCallError as e:
            assert "401" in str(e)


def test_404_fail_fast():
    cfg = _cfg()
    with mock.patch("requests.post", return_value=_resp(404)), \
         mock.patch("run_eval.time.sleep"):
        try:
            call_model(cfg, "p", "k", "sys")
            assert False, "expected ModelCallError"
        except ModelCallError as e:
            assert "404" in str(e)


def test_network_error_retries():
    cfg = _cfg()
    with mock.patch("requests.post", side_effect=[ReadTimeout(), _ok("ok")]) as mp, \
         mock.patch("run_eval.time.sleep"):
        out = call_model(cfg, "p", "k", "sys", max_retries=5)
    assert out == "ok"
    assert mp.call_count == 2


def test_non_json_body_retries():
    cfg = _cfg()
    bad = _resp(200)
    bad.json.side_effect = ValueError("not json")
    with mock.patch("requests.post", side_effect=[bad, _ok("ok")]) as mp, \
         mock.patch("run_eval.time.sleep"):
        out = call_model(cfg, "p", "k", "sys", max_retries=5)
    assert out == "ok"
    assert mp.call_count == 2


def test_exhaustion_raises():
    cfg = _cfg()
    with mock.patch("requests.post", side_effect=[_resp(429), _resp(429), _resp(429)]), \
         mock.patch("run_eval.time.sleep"):
        try:
            call_model(cfg, "p", "k", "sys", max_retries=3)
            assert False, "expected ModelCallError"
        except ModelCallError:
            pass


def test_missing_api_key_raises():
    cfg = _cfg()
    with mock.patch("run_eval.time.sleep"):
        try:
            call_model(cfg, "p", "", "sys")
            assert False, "expected ModelCallError"
        except ModelCallError as e:
            assert "API key" in str(e)
