"""检索层测试：向量索引、检索指标、语料清洗流水线。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from devagent.eval.metrics import mrr, recall_at_k, summarize_retrieval
from devagent.knowledge import KnowledgeStore
from devagent.retrieval import HashingVectorIndex, build_index


def test_hashing_index_retrieves_similar_docs():
    idx = HashingVectorIndex(dim=128)
    idx.add("audit", ["audit", "log", "write", "trace"])
    idx.add("sql", ["sql", "where", "parse", "quote"])
    idx.add("ttl", ["ttl", "expire", "kv", "cache"])
    hits = idx.retrieve(["ttl", "expire", "cache"], k=2)
    assert [h.doc_id for h in hits][0] == "ttl"  # 最相关文档排在首位
    assert hits[0].score > hits[1].score  # 相似度严格降序


def test_hashing_index_empty_query_and_empty_index():
    idx = HashingVectorIndex(dim=64)
    assert idx.retrieve([], k=3) == []
    assert idx.retrieve(["x"], k=3) == []
    idx.add("a", ["hello"])
    assert idx.retrieve([], k=3) == []


def test_build_index_falls_back_to_hashing_without_faiss():
    # 本机无 faiss 时，auto 后端必须退回纯标准库实现，保证零依赖可跑。
    idx = build_index("auto", dim=64)
    assert isinstance(idx, HashingVectorIndex)
    idx.add("doc", ["token"])
    assert idx.retrieve(["token"], k=1)[0].doc_id == "doc"


def test_knowledge_store_uses_vector_retrieval():
    store = KnowledgeStore(ROOT / "knowledge_docs", index_backend="hashing")
    docs = store.retrieve("kv_store 写操作审计日志", k=2)
    assert docs and any(d.doc_id in ("faq", "module_map", "coding_standards") for d in docs)
    assert store.retrieve("", k=2) == []
    assert store.corpus_size() == 3


def test_recall_at_k_and_mrr():
    assert recall_at_k(["a", "b", "c"], ["a", "b"], k=3) == 1.0
    assert recall_at_k(["a", "x", "y"], ["a", "b"], k=3) == 0.5
    assert recall_at_k(["x", "y"], ["a"], k=3) == 0.0
    assert mrr(["x", "a", "b"], ["a"]) == 0.5  # 相关文档在第 2 位
    assert mrr(["a", "b"], ["a"]) == 1.0
    assert mrr(["x", "y"], ["a"]) == 0.0


def test_summarize_retrieval_aggregates():
    records = [
        {"query": "q1", "relevant": ["a"], "hits": ["a", "b"]},
        {"query": "q2", "relevant": ["c"], "hits": ["x", "c"]},
    ]
    s = summarize_retrieval(records, k=2)
    assert s["queries"] == 2
    assert s["recall_at_k"] == 1.0
    assert s["mrr"] == 0.75  # (1.0 + 0.5) / 2


def test_build_retrieval_set_cleans_and_filters(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_retrieval_set import build  # noqa: E402

    raw = tmp_path / "raw.jsonl"
    raw.write_text(
        "\n".join(
            [
                '{"text": "### 需求\\n```python\\nx=1\\n```\\n\\n 在 kv_store 加 TTL put ",'
                ' "source": "requirement", "relevant": ["faq"]}',
                '{"text": "", "source": "requirement", "relevant": ["faq"]}',  # 空文本应被跳过
                '{"text": "无标注的条目", "source": "defect", "relevant": []}',  # 缺标注应被跳过
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"
    n = build(raw, out)
    assert n == 1
    line = out.read_text(encoding="utf-8").strip().splitlines()[0]
    import json

    obj = json.loads(line)
    assert "kv_store" in obj["query"]
    assert "```" not in obj["query"]  # 代码围栏已被清洗
    assert "###" not in obj["query"]  # 井号标题已被清洗
    assert obj["relevant"] == ["faq"]
