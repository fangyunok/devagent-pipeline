"""评审 Agent（ai-review）：任务卡 + 代码 + 编码规范 → 问题定位与门禁结论。"""
from __future__ import annotations

import json

from ..config import Config
from ..knowledge import KnowledgeStore
from ..llm import LLMClient, extract_json
from ..schemas import CodeChange, ReviewReport, TaskCard
from ..trace import LOGGER

SYSTEM = """你是评审 Agent。对照任务卡与 KNOWLEDGE 中的编码规范审查代码。
输出 JSON：{"issues": [{"severity": "critical|major|minor", "category", "location", "message"}], "approved"}。
存在 critical/major 问题时 approved=false。问题需定位到具体函数或位置，禁止泛泛而谈。"""


class ReviewerAgent:
    def __init__(self, llm: LLMClient, knowledge: KnowledgeStore, config: Config | None = None):
        self.llm = llm
        self.knowledge = knowledge
        self.config = config

    def run(self, card: TaskCard, code: CodeChange) -> ReviewReport:
        docs = self.knowledge.retrieve("编码规范 安全 审计 评审", k=2)
        user = (
            "AGENT: reviewer\n"
            f"TASK_CARD:\n{json.dumps(card.to_dict(), ensure_ascii=False)}\n"
            f"CODE:\n{code.content}\n"
            f"KNOWLEDGE:\n{self.knowledge.format_for_prompt(docs)}"
        )
        data = extract_json(self.llm.complete(SYSTEM, user))
        report = ReviewReport(
            task_id=card.task_id,
            issues=data.get("issues", []),
            approved=bool(data.get("approved", True)),
            retrieved_knowledge=[d.doc_id for d in docs],
        )
        LOGGER.info("reviewer: 评审 %s approved=%s issues=%d",
                    card.task_id, report.approved, len(report.issues))
        return report
