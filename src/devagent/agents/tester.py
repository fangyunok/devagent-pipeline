"""测试 Agent：在沙箱中真实执行生成的代码与测试用例。

Harness 层指标必须来自真实执行，而不是模型自述「测试通过」。
benchmark 模式下执行基准公开测试；generate_tests() 支持由 LLM 生成用例。
（阶段二将接入容器隔离执行，本类保持接口不变。）
"""
from __future__ import annotations

import traceback

from ..config import Config
from ..llm import LLMClient, extract_json
from ..schemas import CodeChange, TaskCard, TestReport
from ..trace import LOGGER

GEN_SYSTEM = """你是测试 Agent。根据任务卡与代码生成 Python 断言式测试用例（不使用 pytest 框架），
覆盖正常路径与边界条件。输出 JSON：{"test_code": "..."}。"""


class TesterAgent:
    def __init__(self, llm: LLMClient | None = None, config: Config | None = None):
        self.llm = llm
        self.config = config

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
        namespace: dict = {}
        try:
            exec(compile(code.content, "<generated>", "exec"), namespace)
            if test_code.strip():
                exec(compile(test_code, "<tests>", "exec"), namespace)
            return TestReport(task_id=card.task_id, passed=True, total=1,
                              generated_tests=test_code)
        except AssertionError as exc:
            return TestReport(task_id=card.task_id, passed=False, total=1,
                              failures=[{"name": "assertion", "message": str(exc) or "断言失败"}],
                              generated_tests=test_code)
        except Exception:
            return TestReport(task_id=card.task_id, passed=False, total=1,
                              failures=[{"name": "runtime", "message": traceback.format_exc(limit=2)}],
                              generated_tests=test_code)
