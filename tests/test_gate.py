"""质量门禁与历史基线对比的单元测试。"""

from __future__ import annotations

from devagent.eval.gate import (
    _flat_metrics,
    check_thresholds,
    compare_baseline,
    load_baseline,
    write_summary,
)


def _sample_layers():
    model = {
        "field_precision": 0.8571,
        "field_recall": 0.8571,
        "field_f1": 0.8571,
        "abstain_violation_rate": 0.0,
    }
    harness = {
        "test_pass_rate": 0.75,
        "review_precision": 0.6667,
        "review_recall": 0.6667,
        "gate_accuracy": 0.875,
        "e2e_success_rate": 0.75,
    }
    return model, harness


def test_flat_metrics_pulls_from_both_layers():
    model, harness = _sample_layers()
    flat = _flat_metrics(model, harness)
    assert flat["field_f1"] == 0.8571
    assert flat["e2e_success_rate"] == 0.75
    assert flat["abstain_violation_rate"] == 0.0


def test_thresholds_pass_when_all_above_floor():
    model, harness = _sample_layers()
    result = check_thresholds(model, harness)
    assert result["passed"] is True
    assert result["violations"] == []


def test_thresholds_fail_and_report_violation():
    model, harness = _sample_layers()
    result = check_thresholds(model, harness, {"e2e_success_rate": 0.9})
    assert result["passed"] is False
    assert len(result["violations"]) == 1
    v = result["violations"][0]
    assert v["metric"] == "e2e_success_rate"
    assert v["value"] == 0.75
    assert v["threshold"] == 0.9


def test_baseline_no_regression_when_identical():
    model, harness = _sample_layers()
    baseline = {"run_id": "abc", "model_layer": model, "harness_layer": harness}
    result = compare_baseline(model, harness, baseline)
    assert result["passed"] is True
    assert result["regressions"] == []
    assert all(d["direction"] == "flat" for d in result["diffs"])


def test_baseline_detects_drop_regression():
    model, harness = _sample_layers()
    baseline = {"run_id": "abc", "model_layer": model, "harness_layer": harness}
    # 当前 e2e 成功率从 0.75 跌到 0.60，超过容忍度 0.02。
    degraded_harness = dict(harness, e2e_success_rate=0.60)
    result = compare_baseline(model, degraded_harness, baseline)
    assert result["passed"] is False
    assert any(r["metric"] == "e2e_success_rate" for r in result["regressions"])


def test_baseline_detects_abstain_increase_regression():
    model, harness = _sample_layers()
    baseline = {"run_id": "abc", "model_layer": model, "harness_layer": harness}
    # 弃答违例率从 0.0 涨到 0.5，越低越好指标上涨即回归。
    degraded_model = dict(model, abstain_violation_rate=0.5)
    result = compare_baseline(degraded_model, harness, baseline)
    assert result["passed"] is False
    assert any(r["metric"] == "abstain_violation_rate" for r in result["regressions"])


def test_write_summary_embeds_gate(tmp_path):
    model, harness = _sample_layers()
    gate = check_thresholds(model, harness)
    summary = {"run_id": "x", "model_layer": model, "harness_layer": harness}
    path = write_summary(summary, gate, tmp_path)
    data = load_baseline(path)
    assert data["gate"]["passed"] is True
    assert data["run_id"] == "x"
