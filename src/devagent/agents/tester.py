"""测试 Agent：在隔离沙箱中真实执行生成的代码与测试用例。

Harness 层指标必须来自真实、隔离的执行，而非模型自述「测试通过」。
执行由 SandboxRunner 完成（subprocess 或 docker 后端，见 ../sandbox.py），
结果按「通过 / 超时 / 异常 / 资源超限」分类计数。
"""
from __future__ import annotations

from ..config import Config
from ..llm import LLMClient, extract_json
from ..sandbox import SandboxResult, SandboxRunner, get_runner
from ..schemas import CodeChange, TaskCard, TestReport
from ..trace import LOGGER

GEN_SYSTEM = """你是测试 Agent。根据任务卡与代码生成 Python 断言式测试用例（不使用 pytest 框架），
覆盖正常路径与边界条件。输出 JSON：{"test_code": "..."}。"""


class TesterAgent:
    def __init__(self, llm: LLMClient | None = None, config: Config | None = None,
                 runner: SandboxRunner | None = None):
        self.llm = llm
        self.config = config
        if runner is not None:
            self.runner = runner
        elif config is not None:
            self.runner = get_runner(
                backend=config.sandbox_backend,
                timeout_seconds=config.sandbox_timeout_seconds,
                max_memory_mb=config.sandbox_max_memory_mb)
        else:
            self.runner = get_runner()

    def generate_tests(self, card: TaskCard, code: CodeChange) -> str:
        if self.llm is None:
            raise RuntimeError("生成测试需要配置 LLM 后端")
        user = f"AGENT: tester\nTASK_CARD:\n{card.to_dict()}\nCODE:\n{code.content}"
        return extract_json(self.llm.complete(GEN_SYSTEM, user)).get("test_code", "")

    def run(self, card: TaskCard, code: CodeChange, test_code: str = "") -> TestReport:
        if not test_code and self.llm is not None:
            test_code = self.generate_tests(card, code)
        if not code.content.strip():
            return TestReport(task_id=card.task_id, passed=False, total=1,
                              failures=[{"name": "codegen", "message": "未生成任何代码"}],
                              generated_tests=test_code)
        result: SandboxResult = self.runner.execute(code.content, test_code)
        LOGGER.info("tester: 执行 %s outcome=%s total=%d",
                    card.task_id, result.outcome, result.total)
        return TestReport(
            task_id=card.task_id,
            passed=result.passed,
            total=result.total,
            failures=result.failures,
            generated_tests=test_code,
        )
