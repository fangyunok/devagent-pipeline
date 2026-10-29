"""Orchestrator：串联 需求→编码→测试→评审，沉淀全链路 trace。

接入统一配置与结构化 trace：每个阶段记录起止与耗时，
运行产出 JSON Lines trace（供评测回溯、耗时分析、跨版本对比）。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from .agents import CoderAgent, RequirementAgent, ReviewerAgent, TesterAgent
from .config import Config, load_config
from .knowledge import KnowledgeStore
from .llm import get_llm
from .schemas import PipelineResult
from .trace import LOGGER, Trace, configure_logging


class DevPipeline:
    def __init__(
        self,
        knowledge_dir: str | Path | None = None,
        backend: str | None = None,
        config: Config | None = None,
    ):
        self.config = config or load_config()
        configure_logging(self.config.log_level)
        if backend is not None:
            self.config.backend = backend
        if knowledge_dir is not None:
            self.config.knowledge_dir = str(knowledge_dir)
        self.llm = get_llm(self.config.backend, self.config)
        self.knowledge = KnowledgeStore(self.config.knowledge_dir)
        self.requirement = RequirementAgent(self.llm, self.knowledge, self.config)
        self.coder = CoderAgent(self.llm, self.knowledge, self.config)
        self.tester = TesterAgent(self.llm, self.config)
        self.reviewer = ReviewerAgent(self.llm, self.knowledge, self.config)
        LOGGER.info(
            "DevPipeline 就绪：backend=%s knowledge_docs=%d",
            self.config.backend,
            self.knowledge.corpus_size(),
        )

    def run_task(self, task: dict, trace: Trace | None = None) -> PipelineResult:
        """task: {task_id, source, input, test_code?}；expected_* 字段只用于评测，不进入链路。"""
        if trace is None:
            trace = Trace(run_id=task["task_id"], enabled=self.config.trace_enabled)
        tid = task["task_id"]
        trace.record("task_start", task_id=tid, source=task.get("source", ""))

        trace.stage_start("requirement", task_id=tid)
        card = self.requirement.run(task)
        trace.stage_end(
            "requirement",
            task_id=tid,
            target_module=card.target_module,
            requires_audit_log=card.requires_audit_log,
        )

        trace.stage_start("codegen", task_id=tid)
        code = self.coder.run(card, original_input=task["input"])
        trace.stage_end(
            "codegen",
            task_id=tid,
            files=[f["path"] for f in code.files],
            retrieved_knowledge=code.retrieved_knowledge,
        )

        trace.stage_start("test", task_id=tid)
        tests = self.tester.run(card, code, task.get("test_code", ""))
        trace.stage_end("test", task_id=tid, passed=tests.passed)

        trace.stage_start("review", task_id=tid)
        review = self.reviewer.run(card, code)
        trace.stage_end(
            "review", task_id=tid, approved=review.approved, issue_count=len(review.issues)
        )

        trace.record("task_end", task_id=tid, passed=tests.passed, approved=review.approved)
        return PipelineResult(task_id=tid, card=card, code=code, tests=tests, review=review)


def new_run_id() -> str:
    """生成一次评测运行的唯一 id（短 uuid）。"""
    return uuid.uuid4().hex[:12]
