"""领域知识库：文档加载 + 向量检索（RAG 注入）。

知识文档按产品线沉淀（模块地图 / 编码规范 / 踩坑 FAQ），
各 Agent 构造 prompt 前检索相关片段注入，实现「领域知识 → 生成质量」。
检索走向量相似度（见 ``retrieval.py``），接口保持 ``retrieve(query, k)`` 语义；
向量后端按环境自动选择（有 faiss 用 faiss，否则纯标准库哈希编码）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .retrieval import VectorIndex, build_index


@dataclass
class KnowledgeDoc:
    doc_id: str
    title: str
    content: str
    path: str


class KnowledgeStore:
    def __init__(
        self, docs_dir: str | Path, index_backend: str = "auto", index_dim: int = 256
    ) -> None:
        self.docs_dir = Path(docs_dir)
        self.docs: list[KnowledgeDoc] = []
        self._index: VectorIndex = build_index(index_backend, index_dim)
        self._load()

    def _load(self) -> None:
        for path in sorted(self.docs_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = next(
                (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")),
                path.stem,
            )
            self.docs.append(
                KnowledgeDoc(doc_id=path.stem, title=title, content=text, path=str(path))
            )
            # 标题 + 正文 token 共同入库，标题语义与正文语义都参与向量编码。
            tokens = self._tokenize(title) + self._tokenize(text)
            self._index.add(path.stem, tokens)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # 英文标识符 + 中文二元组，兼顾模块名与自然语言查询。
        words = re.findall(r"[a-zA-Z_]\w+", text.lower())
        chars = re.findall(r"[一-鿿]", text)
        bigrams = [a + b for a, b in zip(chars, chars[1:], strict=False)]
        return words + bigrams

    def retrieve(self, query: str, k: int = 2) -> list[KnowledgeDoc]:
        """按向量相似度返回 top-k 文档；查询为空或无命中时返回空列表。"""
        if not query.strip() or not self.docs:
            return []
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []
        hits = self._index.retrieve(q_tokens, k)
        by_id = {d.doc_id: d for d in self.docs}
        return [by_id[h.doc_id] for h in hits if h.doc_id in by_id]

    def format_for_prompt(self, docs: list[KnowledgeDoc]) -> str:
        if not docs:
            return "(无检索命中)"
        return "\n\n".join(f"### {d.title} ({d.doc_id})\n{d.content}" for d in docs)

    def corpus_size(self) -> int:
        return len(self.docs)
