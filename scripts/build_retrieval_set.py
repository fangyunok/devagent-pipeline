"""真实语料清洗标注流水线：原始需求/缺陷/MR 语料 → 检索标注集。

从线上沉淀的原始语料（需求单 / 缺陷单 / QA issue / MR 描述）中，
按产品线切分并清洗出「查询 — 相关文档」对，产出可直接被评测 runner
消费的 ``retrieval_queries.jsonl``。清洗规则：

- 去掉空行、首尾空白与 Markdown 干扰符（代码围栏、多余井号）；
- 每个条目携带 ``source``（需求/缺陷/qa/mr）与 ``product``（产品线），
  便于按产品线拆分数据集；
- 相关文档取自条目里显式标注的 ``relevant`` 字段，缺省时按产品线
  回填到对应模块文档，标注不完整会跳过并提示。

用法：
    python scripts/build_retrieval_set.py --input raw_corpus.jsonl --out data/retrieval_queries.jsonl

输入格式（jsonl，每行一条）：
    {"text": "需求描述……", "source": "requirement", "product": "kv_store",
     "relevant": ["faq", "module_map"]}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_FENCE = re.compile(r"```[^`]*```", re.DOTALL)
_HASH = re.compile(r"^#{1,6}\s*", re.MULTILINE)


def _clean(text: str) -> str:
    """清洗单条语料：去代码围栏、去标题井号、折叠空白。"""
    text = _FENCE.sub(" ", text)
    text = _HASH.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _queries_from_record(record: dict) -> dict | None:
    text = _clean(record.get("text", ""))
    relevant = [str(r) for r in record.get("relevant", []) if r]
    if not text:
        return None
    if not relevant:
        print(f"跳过（缺少 relevant 标注）：{record.get('source', '?')}", file=sys.stderr)
        return None
    return {"query": text, "relevant": relevant}


def build(raw_path: str | Path, out_path: str | Path) -> int:
    raw = Path(raw_path)
    if raw.suffix.lower() == ".jsonl":
        records = [
            json.loads(line)
            for line in raw.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    elif raw.suffix.lower() == ".json":
        records = json.loads(raw.read_text(encoding="utf-8"))
    else:
        raise SystemExit(f"仅支持 .jsonl / .json 输入，收到 {raw.suffix}")

    queries = [q for r in records if (q := _queries_from_record(r)) is not None]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in queries) + "\n",
        encoding="utf-8",
    )
    print(f"已产出 {len(queries)} 条检索标注到 {out}")
    return len(queries)


def main() -> None:
    parser = argparse.ArgumentParser(description="真实语料清洗 → 检索标注集")
    parser.add_argument("--input", required=True, help="原始语料 jsonl/json")
    parser.add_argument("--out", default="data/retrieval_queries.jsonl", help="标注集输出路径")
    args = parser.parse_args()
    build(args.input, args.out)


if __name__ == "__main__":
    main()
