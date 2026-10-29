"""质量门禁与历史基线对比。

门禁把「跑出数字」升级为「挡质量退化」：
1. 阈值校验：核心指标低于阈值即判不通过，返回违规项清单。
2. 基线对比：加载历史基线（上一次通过的 summary.json），逐指标对齐，
   标出上涨/下跌/持平，并给出回归判定（指标跌破基线的容忍度）。
3. 门禁结论：结构化输出，供 CI 以非零退出码拦截质量退化。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 核心门禁指标：越低越差。阈值语义为「不得低于」。
_THRESHOLD_KEYS = {
    "field_precision": "field_precision",
    "field_recall": "field_recall",
    "field_f1": "field_f1",
    "test_pass_rate": "test_pass_rate",
    "review_precision": "review_precision",
    "review_recall": "review_recall",
    "gate_accuracy": "gate_accuracy",
    "e2e_success_rate": "e2e_success_rate",
}

# 越界指标：越低越好，回归判定取「上涨超过容忍」。
_LOWER_IS_BETTER = {"abstain_violation_rate"}

# 基线回归容忍度（绝对差值）：跌/涨超过该值视为回归。
_DEFAULT_TOLERANCE = 0.02


def _flat_metrics(model_layer: dict[str, Any], harness_layer: dict[str, Any]) -> dict[str, float]:
    """把双层指标展平为单层 key -> float，供阈值与基线统一处理。"""
    flat: dict[str, float] = {}
    for key in _THRESHOLD_KEYS:
        flat[key] = model_layer.get(key, 0.0)
    for key in _LOWER_IS_BETTER:
        flat[key] = model_layer.get(key, 0.0)
    for key in ("test_pass_rate", "review_precision", "review_recall",
                "gate_accuracy", "e2e_success_rate"):
        flat[key] = harness_layer.get(key, 0.0)
    return flat


def check_thresholds(model_layer: dict[str, Any], harness_layer: dict[str, Any],
                     thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    """阈值校验。thresholds 为 {指标名: 最低值}，缺省用内置默认阈值。"""
    if thresholds is None:
        thresholds = _default_thresholds()
    flat = _flat_metrics(model_layer, harness_layer)
    violations: list[dict[str, Any]] = []
    for key, floor in thresholds.items():
        value = flat.get(key, 0.0)
        if value < floor:
            violations.append({"metric": key, "value": value, "threshold": floor,
                               "delta": round(value - floor, 4)})
    return {
        "passed": not violations,
        "violations": violations,
        "thresholds": thresholds,
    }


def _default_thresholds() -> dict[str, float]:
    """内置保守阈值：为当前基准的实测值留出空间，拦「明显退化」而非卡正常波动。"""
    return {
        "field_precision": 0.80,
        "field_recall": 0.80,
        "field_f1": 0.80,
        "test_pass_rate": 0.70,
        "review_precision": 0.60,
        "review_recall": 0.60,
        "gate_accuracy": 0.80,
        "e2e_success_rate": 0.70,
    }


def load_baseline(path: str | Path) -> dict[str, Any]:
    """加载历史基线 summary.json（上一次通过的评测结果）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def compare_baseline(model_layer: dict[str, Any], harness_layer: dict[str, Any],
                     baseline: dict[str, Any],
                     tolerance: float = _DEFAULT_TOLERANCE) -> dict[str, Any]:
    """与历史基线逐指标对比，给出涨/跌/平与回归判定。"""
    flat = _flat_metrics(model_layer, harness_layer)
    base_flat = _flat_metrics(baseline.get("model_layer", {}),
                              baseline.get("harness_layer", {}))
    diffs: list[dict[str, Any]] = []
    regressions: list[dict[str, Any]] = []
    for key, value in flat.items():
        base = base_flat.get(key)
        if base is None:
            continue
        delta = round(value - base, 4)
        if abs(delta) < 1e-9:
            direction = "flat"
        elif delta > 0:
            direction = "up"
        else:
            direction = "down"
        # 越低越好：涨过容忍即回归；其余：跌过容忍即回归。
        regressed = (
            delta > tolerance if key in _LOWER_IS_BETTER else delta < -tolerance
        )
        entry = {"metric": key, "baseline": base, "current": value,
                 "delta": delta, "direction": direction}
        diffs.append(entry)
        if regressed:
            regressions.append(entry)
    return {
        "baseline_run_id": baseline.get("run_id"),
        "diffs": diffs,
        "regressions": regressions,
        "passed": not regressions,
    }


def write_summary(summary: dict[str, Any], gate: dict[str, Any],
                  out_dir: str | Path) -> Path:
    """把评测 summary + 门禁结论合写为机器可读 summary.json。"""
    path = Path(out_dir) / "summary.json"
    payload = dict(summary)
    payload["gate"] = gate
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
