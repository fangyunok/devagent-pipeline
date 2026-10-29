"""沙箱执行层单测：隔离、超时、危险能力 allowlist、结果分类、后端降级。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devagent.sandbox import (
    SubprocessRunner,
    DockerRunner,
    SandboxResult,
    get_runner,
    _make_harness,
)


def test_passing_code():
    r = SubprocessRunner()
    result = r.execute("def add(a, b):\n    return a + b", "assert add(1, 2) == 3")
    assert result.passed is True
    assert result.outcome == "passed"
    assert result.failures == []


def test_assertion_failure_classified():
    r = SubprocessRunner()
    result = r.execute("def add(a, b):\n    return a + b", "assert add(1, 2) == 99")
    assert result.passed is False
    assert result.outcome == "failed"
    assert result.failures[0]["name"] == "assertion"


def test_timeout_is_caught():
    r = SubprocessRunner(timeout_seconds=0.5)
    result = r.execute("while True:\n    pass", "")
    assert result.passed is False
    assert result.outcome == "timeout"
    assert result.failures[0]["name"] == "timeout"


def test_blocked_builtins_are_neutralized():
    r = SubprocessRunner()
    # open 被置空，调用应抛异常并归为 runtime 失败，而非逃逸读文件
    result = r.execute("", "open('/etc/hosts')")
    assert result.passed is False
    assert result.outcome == "failed"
    assert result.failures[0]["name"] == "runtime"


def test_runtime_error_classified():
    r = SubprocessRunner()
    result = r.execute("def boom():\n    raise ValueError('x')", "boom()")
    assert result.passed is False
    assert result.failures[0]["name"] == "runtime"


def test_harness_embeds_code_and_test():
    harness = _make_harness("def f():\n    return 1", "assert f() == 1")
    assert '"def f():\\n    return 1"' in harness or "def f():" in harness
    assert "assert f() == 1" in harness


def test_get_runner_defaults_to_subprocess():
    runner = get_runner()
    assert isinstance(runner, SubprocessRunner)


def test_docker_runner_falls_back_when_unavailable(monkeypatch):
    monkeypatch.setattr("devagent.sandbox.shutil.which", lambda *a, **k: None)
    runner = DockerRunner()
    assert runner.available is False
    result = runner.execute("def f():\n    return 1", "assert f() == 1")
    assert result.passed is True  # 降级到 subprocess 仍能出结果
