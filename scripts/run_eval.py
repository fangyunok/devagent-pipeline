"""一条命令跑双层评测 + 质量门禁。

用法：
    python scripts/run_eval.py [--backend mock|openai] [--explain N]
        [--threshold METRIC=VALUE ...] [--baseline path/to/summary.json] [--fail-on-regression]

门禁失败（阈值不满足或较基线回归）时以非零退出码退出，供 CI 拦截质量退化。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from devagent.eval.runner import run_evaluation  # noqa: E402


def _parse_thresholds(items: list[str]) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for item in items:
        key, _, value = item.partition("=")
        if not key or not value:
            raise SystemExit(f"阈值格式错误：{item!r}，应为 METRIC=VALUE")
        thresholds[key.strip()] = float(value)
    return thresholds


def main() -> None:
    parser = argparse.ArgumentParser(description="需求→编码→测试→评审 全链路双层评测 + 质量门禁")
    parser.add_argument("--backend", default="mock", choices=["mock", "openai"])
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--knowledge-dir", default=str(ROOT / "knowledge_docs"))
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "latest"))
    parser.add_argument(
        "--explain", type=int, default=0, help="报告中最多展示 N 条 Model 层失分样例，0 为全部"
    )
    parser.add_argument(
        "--threshold",
        action="append",
        default=[],
        help="核心指标最低阈值，如 --threshold e2e_success_rate=0.7（可重复）",
    )
    parser.add_argument(
        "--baseline", default=None, help="历史基线 summary.json，用于跨版本回归对比"
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="门禁不通过（阈值不足或较基线回归）时以非零退出码退出",
    )
    parser.add_argument(
        "--retrieval-k", type=int, default=3, help="检索评测 Recall@k 的 k 值，默认 3"
    )
    args = parser.parse_args()

    summary = run_evaluation(
        args.knowledge_dir,
        args.data_dir,
        args.out_dir,
        backend=args.backend,
        explain=args.explain,
        thresholds=_parse_thresholds(args.threshold) or None,
        baseline=args.baseline,
        retrieval_k=args.retrieval_k,
    )

    gate = summary.get("gate", {})
    print(json.dumps(summary["model_layer"], ensure_ascii=False, indent=2))
    print(json.dumps(summary["harness_layer"], ensure_ascii=False, indent=2))
    print(json.dumps(summary.get("retrieval_layer", {}), ensure_ascii=False, indent=2))
    print(f"失败案例 {len(summary['failures'])} 条，报告已写入 {args.out_dir}/report.md")

    if "thresholds" in gate or "baseline" in gate:
        print("\n== 质量门禁 ==")
        if "thresholds" in gate:
            if gate["passed"]:
                print("阈值校验：通过")
            else:
                print("阈值校验：不通过")
                for v in gate["violations"]:
                    print(f"  - {v['metric']}: {v['value']} < {v['threshold']} (Δ{v['delta']})")
        if "baseline" in gate:
            b = gate["baseline"]
            if b["passed"]:
                print(f"基线对比（{b['baseline_run_id']}）：无回归")
            else:
                print(f"基线对比（{b['baseline_run_id']}）：存在回归")
                for r in b["regressions"]:
                    print(f"  - {r['metric']}: {r['baseline']} -> {r['current']} (Δ{r['delta']})")

    if args.fail_on_regression:
        passed = True
        if "thresholds" in gate:
            passed = passed and gate["passed"]
        if "baseline" in gate:
            passed = passed and gate["baseline"]["passed"]
        if not passed:
            print("\n质量门禁不通过，以退出码 1 退出。", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
