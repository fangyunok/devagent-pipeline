"""工程化底座单测：配置、trace、LLM 重试与结构化报错。"""
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devagent.config import Config, load_config
from devagent.llm import LLMError, LLMOutputError, extract_json
from devagent.trace import Trace


def test_extract_json_strips_code_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('前缀 {"a": 1} 后缀') == {"a": 1}


def test_extract_json_raises_structured_error_on_bad_output():
    with pytest.raises(LLMOutputError):
        extract_json("这不是 JSON")
    with pytest.raises(LLMOutputError):
        extract_json("[1, 2, 3]")  # 顶层非对象


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("DEVAGENT_BACKEND", "openai")
    monkeypatch.setenv("DEVAGENT_LLM_MAX_RETRIES", "5")
    cfg = load_config()
    assert cfg.backend == "openai"
    assert cfg.llm_max_retries == 5


def test_config_override_dict_wins():
    cfg = load_config({"backend": "openai", "llm_timeout_seconds": 7.5})
    assert cfg.backend == "openai"
    assert cfg.llm_timeout_seconds == 7.5


def test_trace_records_and_aggregates_durations(tmp_path, monkeypatch):
    t = Trace(run_id="r1", enabled=True)
    t.stage_start("req", task_id="t1")
    t.stage_end("req", task_id="t1")
    t.record("task_end", passed=True)
    out = tmp_path / "trace.jsonl"
    t.write(out)
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "stage_start"
    assert lines[-1]["event"] == "task_end"
    assert "req" in t.stage_durations_ms()


def test_trace_disabled_writes_nothing(tmp_path):
    t = Trace(run_id="r1", enabled=False)
    t.record("x")
    out = tmp_path / "t.jsonl"
    t.write(out)
    assert not out.exists()


class _FakeResponse:
    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _make_client(max_retries=1):
    from devagent.llm import OpenAICompatibleClient
    return OpenAICompatibleClient(api_key="sk-test", base_url="https://example.com",
                                  model="m", timeout=1.0, max_retries=max_retries,
                                  backoff_base=0.01)


def test_openai_client_retries_then_raises(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 500, "err", None, None)

    monkeypatch.setattr("devagent.llm.urllib.request.urlopen", fake_urlopen)
    client = _make_client(max_retries=2)
    with pytest.raises(LLMError) as ei:
        client.complete("s", "u")
    assert ei.value.retryable is True
    assert calls["n"] == 3  # 1 次原始 + 2 次重试


def test_openai_client_does_not_retry_4xx(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 400, "bad", None, None)

    monkeypatch.setattr("devagent.llm.urllib.request.urlopen", fake_urlopen)
    client = _make_client(max_retries=3)
    with pytest.raises(LLMError):
        client.complete("s", "u")
    assert calls["n"] == 1  # 4xx 不重试


def test_openai_client_returns_content(monkeypatch):
    payload = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    def fake_urlopen(req, timeout):
        return _FakeResponse(payload)

    monkeypatch.setattr("devagent.llm.urllib.request.urlopen", fake_urlopen)
    assert _make_client().complete("s", "u") == "ok"
