"""编码 Agent：任务卡 + 检索到的编码规范/踩坑 FAQ → 代码变更（MR）。"""

from __future__ import annotations

import json

from ..config import Config
from ..knowledge import KnowledgeStore
from ..llm import LLMClient, extract_json
from ..schemas import CodeChange, TaskCard
from ..trace import LOGGER

SYSTEM = """你是编码 Agent。根据任务卡与 KNOWLEDGE 中的编码规范、踩坑 FAQ 生成代码。
输出 JSON：{"files": [{"path", "content"}], "summary"}。
必须遵守规范中的安全条款（禁止硬编码口令、禁止 eval），写操作按任务卡要求记录审计日志。"""


class CoderAgent:
    def __init__(self, llm: LLMClient, knowledge: KnowledgeStore, config: Config | None = None):
        self.llm = llm
        self.knowledge = knowledge
        self.config = config

    def run(self, card: TaskCard, original_input: str = "") -> CodeChange:
        query = f"{card.target_module} 编码规范 踩坑 {original_input}"
        docs = self.knowledge.retrieve(query, k=3)
        user = (
            "AGENT: coder\n"
            f"TASK_CARD:\n{json.dumps(card.to_dict(), ensure_ascii=False)}\n"
            f"KNOWLEDGE:\n{self.knowledge.format_for_prompt(docs)}\n"
            f"ORIGINAL_INPUT:\n{original_input}"
        )
        LOGGER.info("coder: 生成代码 模块=%s（注入 %d 篇知识）", card.target_module, len(docs))
        data = extract_json(self.llm.complete(SYSTEM, user))
        return CodeChange(
            task_id=card.task_id,
            files=data.get("files", []),
            summary=data.get("summary", ""),
            retrieved_knowledge=[d.doc_id for d in docs],
        )
