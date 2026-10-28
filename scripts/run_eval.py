"""一条命令跑双层评测：python scripts/run_eval.py [--backend mock|openai] [--explain N]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from devagent.eval.runner import run_evaluation  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="需求→编码→测试→评审 全链路双层评测")
    parser.add_argument("--backend", default="mock", choices=["mock", "openai"])
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    parser.add_argument("--knowledge-dir", default=str(ROOT / "knowledge_docs"))
    parser.add_argument("--out-dir", default=str(ROOT / "reports" / "latest"))
    parser.add_argument("--explain", type=int, default=0, help="报告中最多展示 N 条 Model 层失分样例，0 为全部")
    args = parser.parse_args()

    summary = run_evaluation(args.knowledge_dir, args.data_dir, args.out_dir,
                             backend=args.backend, explain=args.explain)
    print(json.dumps(summary["model_layer"], ensure_ascii=False, indent=2))
    print(json.dumps(summary["harness_layer"], ensure_ascii=False, indent=2))
    print(f"失败案例 {len(summary['failures'])} 条，报告已写入 {args.out_dir}/report.md")


if __name__ == "__main__":
    main()
