"""指标口径单测：幻觉双罚、弃答同口径、评审检出与门禁。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devagent.eval.metrics import compare_fields, flatten_card, summarize_harness, summarize_model


def test_hallucinated_field_counts_as_false_positive():
    expected = {"target_module": "kv_store"}
    actual = {"target_module": "kv_store", "extra.user_id": "42"}
    c = compare_fields(expected, actual)
    assert c["tp"] == 1 and c["fp"] == 1 and c["fn"] == 0
    assert c["hallucinated"] == ["extra.user_id"]


def test_mismatched_value_counts_both_fp_and_fn():
    c = compare_fields({"target_module": "kv_store"}, {"target_module": "sql_parser"})
    assert c["tp"] == 0 and c["fp"] == 1 and c["fn"] == 1


def test_flatten_card_ignores_empty_and_keeps_extra():
    card = {"target_module": "", "requires_audit_log": False, "extra": {"admin": "true"}}
    assert flatten_card(card) == {"extra.admin": "true"}


def test_abstention_rate_uses_same_denominator():
    records = [
        {
            "task_id": "A",
            "comparison": {"tp": 0, "fp": 0, "fn": 0, "hallucinated": []},
            "abstain_case": True,
            "abstain_violation": False,
        },
        {
            "task_id": "B",
            "comparison": {"tp": 0, "fp": 1, "fn": 0, "hallucinated": ["x"]},
            "abstain_case": True,
            "abstain_violation": True,
        },
    ]
    m = summarize_model(records)
    assert m["abstain_cases"] == 2
    assert m["abstain_violations"] == ["B"]
    assert m["abstain_violation_rate"] == 0.5


def test_harness_review_recall_and_gate():
    records = [
        {
            "task_id": "T1",
            "test_passed": True,
            "expected_issues": ["use_eval"],
            "actual_issues": ["use_eval"],
            "gate_correct": True,
            "e2e_success": True,
        },
        {
            "task_id": "T2",
            "test_passed": False,
            "expected_issues": ["missing_audit_log"],
            "actual_issues": [],
            "gate_correct": False,
            "e2e_success": False,
        },
    ]
    h = summarize_harness(records)
    assert h["review_recall"] == 0.5
    assert h["review_precision"] == 1.0
    assert h["gate_accuracy"] == 0.5
    assert h["e2e_success_rate"] == 0.5
