"""领域知识库：文档加载 + 检索（RAG 注入）。

知识文档按产品线沉淀（模块地图 / 编码规范 / 踩坑 FAQ），
各 Agent 构造 prompt 前检索相关片段注入，实现「领域知识 → 生成质量」。
检索默认关键词加权打分，接口保持 retrieve(query, k) 语义，可平滑替换为向量实现。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class KnowledgeDoc:
    doc_id: str
    title: str
    content: str
    path: str


class KnowledgeStore:
    def __init__(self, docs_dir: str | Path):
        self.docs_dir = Path(docs_dir)
        self.docs: list[KnowledgeDoc] = []
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

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        # 英文标识符 + 中文二元组，兼顾模块名与自然语言查询。
        words = re.findall(r"[a-zA-Z_]\w+", text.lower())
        chars = re.findall(r"[一-鿿]", text)
        bigrams = [a + b for a, b in zip(chars, chars[1:], strict=False)]
        return words + bigrams

    def retrieve(self, query: str, k: int = 2) -> list[KnowledgeDoc]:
        """按关键词加权打分返回 top-k 文档；查询为空或无命中时返回空列表。"""
        if not query.strip() or not self.docs:
            return []
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []
        scored = []
        for doc in self.docs:
            d_tokens = self._tokenize(doc.content)
            if not d_tokens:
                continue
            score = sum(1.0 if t in d_tokens else 0.0 for t in set(q_tokens))
            # 标题命中加权，模块地图/规范类文档的标题语义强。
            title_tokens = self._tokenize(doc.title)
            score += sum(2.0 for t in set(q_tokens) if t in title_tokens)
            scored.append((score / (len(d_tokens) ** 0.5), doc))
        scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:k]]

    def format_for_prompt(self, docs: list[KnowledgeDoc]) -> str:
        if not docs:
            return "(无检索命中)"
        return "\n\n".join(f"### {d.title} ({d.doc_id})\n{d.content}" for d in docs)

    def corpus_size(self) -> int:
        return len(self.docs)
