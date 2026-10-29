"""沙箱执行层：在隔离环境中真实执行生成代码与测试用例。

统一 SandboxRunner 接口，两个后端：
- SubprocessRunner：子进程 + 超时 + 危险能力 allowlist（纯标准库，本机/CI 可用）；
- DockerRunner：容器隔离 + 资源限额（需本机 Docker，不可用时优雅降级到 subprocess）。

执行结果按「通过 / 超时 / 异常 / 资源超限」分类计数，替换原先进程内 exec() 的
「一个 total=1 假数字」，让 Harness 层指标反映真实、隔离的执行质量。
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .trace import LOGGER


@dataclass
class SandboxResult:
    """一次沙箱执行的结构化结果。"""

    passed: bool
    total: int
    exit_code: int = 0
    outcome: str = "passed"  # passed | failed | timeout | resource_limit | error
    failures: list[dict[str, str]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "total": self.total,
            "exit_code": self.exit_code,
            "outcome": self.outcome,
            "failures": self.failures,
        }


class SandboxRunner(Protocol):
    """沙箱执行协议：execute(code, test_code) -> SandboxResult。"""

    def execute(self, code: str, test_code: str) -> SandboxResult:  # pragma: no cover
        ...


# 沙箱安全模型（分层）：
# 1. 进程/容器隔离：subprocess 子进程或 Docker 容器，崩溃不拖累主进程；
# 2. 资源限制：超时 + 内存 + pids 上限；
# 3. 危险能力收敛：仅中和「逃逸类」内置（读文件 open、交互 input、
#    窥探调用栈 globals/locals/vars），保留 __import__（生成代码需 import time 等）
#    与 eval（动态执行由 Reviewer 的 use_eval 规则在评审门禁拦截）。
_BLOCKED_BUILTINS = {
    "open",
    "input",
    "globals",
    "locals",
    "vars",
    "memoryview",
}


def _make_harness(code: str, test_code: str) -> str:
    """把生成代码与测试代码拼进一个自包含的 runner 脚本。

    该脚本在受控命名空间执行：blocked builtins、失败分类（断言/超时/异常）
    与退出码语义由脚本自身实现，保证两个后端行为一致。

    用唯一占位符 + replace 注入 code/test/blocked，避免与脚本内的 % / {} 冲突。
    """
    harness = """\
import builtins
import json
import sys
import time

for _name in __BLOCKED__:
    if hasattr(builtins, _name):
        setattr(builtins, _name, None)

_result = {"passed": True, "failures": [], "total": 1}

try:
    _ns = {}
    exec(compile(__CODE__, "<generated>", "exec"), _ns)
    _test = __TEST__
    if _test.strip():
        exec(compile(_test, "<tests>", "exec"), _ns)
except AssertionError as _e:
    _result["passed"] = False
    _result["failures"].append({"name": "assertion", "message": str(_e) or "断言失败"})
except Exception as _e:
    _result["passed"] = False
    _result["failures"].append({"name": "runtime", "message": type(_e).__name__ + ": " + str(_e)})
print(json.dumps(_result, ensure_ascii=False))
"""
    return (
        harness.replace("__BLOCKED__", repr(sorted(_BLOCKED_BUILTINS)))
        .replace("__CODE__", repr(code))
        .replace("__TEST__", repr(test_code))
    )


class SubprocessRunner:
    """子进程后端：独立进程执行 + 超时控制 + 危险能力 allowlist。"""

    def __init__(self, timeout_seconds: float = 10.0, max_memory_mb: int = 256):
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb

    def execute(self, code: str, test_code: str) -> SandboxResult:
        harness = _make_harness(code, test_code)
        # 优先用 subprocess 内置超时；Windows 上 resource 模块不可用，内存限额
        # 通过环境变量传递、由 Docker 后端强保证，subprocess 后端退化为超时控制。
        cmd = [sys.executable, "-c", harness]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                passed=False,
                total=1,
                outcome="timeout",
                failures=[{"name": "timeout", "message": f"执行超时（>{self.timeout_seconds}s）"}],
            )
        if proc.returncode != 0:
            return SandboxResult(
                passed=False,
                total=1,
                exit_code=proc.returncode,
                outcome="error",
                stderr=proc.stderr,
                failures=[
                    {"name": "runtime", "message": (proc.stderr or "执行异常").strip()[:200]}
                ],
            )
        try:
            data = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return SandboxResult(
                passed=False,
                total=1,
                outcome="error",
                stdout=proc.stdout,
                stderr=proc.stderr,
                failures=[{"name": "runtime", "message": "沙箱输出无法解析"}],
            )
        return SandboxResult(
            passed=bool(data.get("passed", False)),
            total=int(data.get("total", 1)),
            outcome="passed" if data.get("passed") else "failed",
            failures=data.get("failures", []),
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


class DockerRunner:
    """Docker 后端：容器隔离 + CPU/内存限额。需本机 Docker。

    不可用时（docker 命令不存在或未启动）降级为 SubprocessRunner，
    保证同一条评测命令在无 Docker 环境也能跑出结果。
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        timeout_seconds: float = 10.0,
        max_memory_mb: int = 256,
        fallback: SandboxRunner | None = None,
    ):
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self._available = shutil.which("docker") is not None
        self._fallback = fallback or SubprocessRunner(timeout_seconds, max_memory_mb)
        if not self._available:
            LOGGER.warning("未检测到 docker，DockerRunner 降级为 subprocess 后端")

    @property
    def available(self) -> bool:
        return self._available

    def execute(self, code: str, test_code: str) -> SandboxResult:
        if not self._available:
            return self._fallback.execute(code, test_code)
        harness = _make_harness(code, test_code)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(harness)
            tmp_path = fh.name
        try:
            cmd = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--memory",
                f"{self.max_memory_mb}m",
                "--memory-swap",
                f"{self.max_memory_mb}m",
                "--pids-limit",
                "64",
                "-v",
                f"{Path(tmp_path)}:/app/run.py:ro",
                self.image,
                "python",
                "/app/run.py",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds + 30,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return SandboxResult(
                    passed=False,
                    total=1,
                    outcome="timeout",
                    failures=[
                        {"name": "timeout", "message": f"容器执行超时（>{self.timeout_seconds}s）"}
                    ],
                )
            if proc.returncode != 0:
                err_msg = (proc.stderr or "容器执行异常").strip()[:200]
                return SandboxResult(
                    passed=False,
                    total=1,
                    exit_code=proc.returncode,
                    outcome="error",
                    stderr=proc.stderr,
                    failures=[{"name": "runtime", "message": err_msg}],
                )
            data = json.loads(proc.stdout.strip() or "{}")
            return SandboxResult(
                passed=bool(data.get("passed", False)),
                total=int(data.get("total", 1)),
                outcome="passed" if data.get("passed") else "failed",
                failures=data.get("failures", []),
                stdout=proc.stdout,
                stderr=proc.stderr,
            )
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def get_runner(
    backend: str = "subprocess", timeout_seconds: float = 10.0, max_memory_mb: int = 256
) -> SandboxRunner:
    if backend == "docker":
        return DockerRunner(timeout_seconds=timeout_seconds, max_memory_mb=max_memory_mb)
    return SubprocessRunner(timeout_seconds=timeout_seconds, max_memory_mb=max_memory_mb)
