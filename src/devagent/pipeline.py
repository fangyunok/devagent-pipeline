"""Orchestrator：串联 需求→编码→测试→评审，沉淀全链路 trace。"""
from __future__ import annotations

from pathlib import Path

from .agents import CoderAgent, RequirementAgent, ReviewerAgent, TesterAgent
from .knowledge import KnowledgeStore
from .llm import get_llm
from .schemas import PipelineResult


class DevPipeline:
    def __init__(self, knowledge_dir: str | Path, backend: str = "mock"):
        self.llm = get_llm(backend)
        self.knowledge = KnowledgeStore(knowledge_dir)
        self.requirement = RequirementAgent(self.llm, self.knowledge)
        self.coder = CoderAgent(self.llm, self.knowledge)
        self.tester = TesterAgent(self.llm)
        self.reviewer = ReviewerAgent(self.llm, self.knowledge)

    def run_task(self, task: dict) -> PipelineResult:
        """task: {task_id, source, input, test_code?}；expected_* 字段只用于评测，不进入链路。"""
        card = self.requirement.run(task)
        code = self.coder.run(card, original_input=task["input"])
        tests = self.tester.run(card, code, task.get("test_code", ""))
        review = self.reviewer.run(card, code)
        return PipelineResult(task_id=task["task_id"], card=card, code=code,
                              tests=tests, review=review)
