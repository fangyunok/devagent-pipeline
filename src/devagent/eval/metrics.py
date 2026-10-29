"""双层评测指标。

Model 层（结构化产出质量）：
- 字段级 micro P/R/F1。precision 分母 = 模型实际吐出的字段数，
  幻觉字段计入假阳性；值不匹配同时计假阳性与漏检。
- 幻觉字段清单：actual 中存在而 expected 未定义的字段。
- 弃答违例：expected 为空的用例中，实际吐出任何字段即违例（分子分母同口径）。

Harness 层（端到端运行质量，全部来自真实执行/真实评审输出）：
- test_pass_rate：沙箱执行断言通过率。
- review_precision/recall：评审检出类别与基准期望类别比对。
- gate_accuracy：评审门禁决策与期望一致率（该拦的拦、该放的放）。
- e2e_success_rate：测试通过 且 门禁决策正确。
"""

from __future__ import annotations

from typing import Any


def flatten_card(card: dict[str, Any]) -> dict[str, Any]:
    """把任务卡展平为参与评分的字段集合（空值不视为吐出）。"""
    fields: dict[str, Any] = {}
    if card.get("target_module"):
        fields["target_module"] = card["target_module"]
    if card.get("requires_audit_log"):
        fields["requires_audit_log"] = True
    for key, value in (card.get("extra") or {}).items():
        fields[f"extra.{key}"] = value
    return fields


def compare_fields(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    tp = fp = fn = 0
    hallucinated, missing, mismatched = [], [], []
    for key, value in actual.items():
        if key in expected and expected[key] == value:
            tp += 1
        else:
            fp += 1
            if key not in expected:
                hallucinated.append(key)
            else:
                mismatched.append(key)
    for key in expected:
        if key not in actual:
            fn += 1
            missing.append(key)
        elif actual[key] != expected[key]:
            fn += 1
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "hallucinated": hallucinated,
        "missing": missing,
        "mismatched": mismatched,
    }


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def summarize_model(records: list[dict[str, Any]]) -> dict[str, Any]:
    """records: [{task_id, expected, actual, comparison, abstain_case, abstain_violation}]"""
    tp = sum(r["comparison"]["tp"] for r in records)
    fp = sum(r["comparison"]["fp"] for r in records)
    fn = sum(r["comparison"]["fn"] for r in records)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    abstain = [r for r in records if r["abstain_case"]]
    violations = [r["task_id"] for r in abstain if r["abstain_violation"]]
    return {
        "field_precision": round(precision, 4),
        "field_recall": round(recall, 4),
        "field_f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "hallucination_fields": sorted(
            {f for r in records for f in r["comparison"]["hallucinated"]}
        ),
        "abstain_cases": len(abstain),
        "abstain_violations": violations,
        "abstain_violation_rate": round(safe_div(len(violations), len(abstain)), 4),
    }


def recall_at_k(hits: list[str], relevant: list[str], k: int) -> float:
    """Recall@k：前 k 个命中里命中的相关文档数 / 相关文档总数。"""
    if not relevant:
        return 0.0
    return safe_div(len(set(hits[:k]) & set(relevant)), len(relevant))


def mrr(hits: list[str], relevant: list[str]) -> float:
    """MRR：第一个相关文档出现在命中列表位置的倒数（位置从 1 起）。"""
    for i, doc_id in enumerate(hits, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def summarize_retrieval(records: list[dict[str, Any]], k: int = 3) -> dict[str, Any]:
    """records: [{query, relevant, hits}]，hits 为按相似度降序的文档 id 列表。"""
    n = len(records)
    return {
        "queries": n,
        "recall_at_k": round(
            safe_div(sum(recall_at_k(r["hits"], r["relevant"], k) for r in records), n), 4
        ),
        "mrr": round(safe_div(sum(mrr(r["hits"], r["relevant"]) for r in records), n), 4),
    }


def summarize_harness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """records: [{task_id, test_passed, expected_issues, actual_issues,
    gate_correct, e2e_success}]"""
    n = len(records)
    expected_total = sum(len(r["expected_issues"]) for r in records)
    actual_total = sum(len(r["actual_issues"]) for r in records)
    hit = sum(len(set(r["expected_issues"]) & set(r["actual_issues"])) for r in records)
    return {
        "tasks": n,
        "test_pass_rate": round(safe_div(sum(r["test_passed"] for r in records), n), 4),
        "review_precision": round(safe_div(hit, actual_total), 4),
        "review_recall": round(safe_div(hit, expected_total), 4),
        "gate_accuracy": round(safe_div(sum(r["gate_correct"] for r in records), n), 4),
        "e2e_success_rate": round(safe_div(sum(r["e2e_success"] for r in records), n), 4),
        "expected_issue_total": expected_total,
        "actual_issue_total": actual_total,
        "issue_hit": hit,
    }
