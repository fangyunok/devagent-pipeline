"""全链路集成测试：真实执行、门禁拦截、错误传播归因、知识库检索。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from devagent.eval.attribution import attribute_failure
from devagent.eval.runner import run_evaluation
from devagent.knowledge import KnowledgeStore
from devagent.pipeline import DevPipeline


@pytest.fixture(scope="module")
def pipeline():
    return DevPipeline(ROOT / "knowledge_docs", backend="mock")


def _task(task_id, input_text, test_code="", expected_card=None, expected_issues=None):
    return {
        "task_id": task_id,
        "source": "requirement",
        "input": input_text,
        "test_code": test_code,
        "expected_card": expected_card or {},
        "expected_issues": expected_issues or [],
    }


def test_normal_task_passes_end_to_end(pipeline):
    task = _task("T-OK", "在 kv_store 模块新增带 TTL 的 put 接口，所有写操作记录审计日志",
                 'put("a", 1)\nassert get("a") == 1\nassert ("put", "a") in AUDIT')
    result = pipeline.run_task(task)
    assert result.card.target_module == "kv_store"
    assert result.card.requires_audit_log is True
    assert result.tests.passed is True
    assert result.review.approved is True
    assert result.code.retrieved_knowledge  # RAG 确实注入了知识


def test_dangerous_code_is_blocked_by_review_gate(pipeline):
    task = _task("T-EVAL", "在 sql_parser 模块支持动态执行表达式以简化调试",
                 'assert parse_where("select 1") == {}')
    result = pipeline.run_task(task)
    assert result.tests.passed is True  # 代码能跑，但必须被门禁拦下
    assert result.review.approved is False
    assert "use_eval" in [i["category"] for i in result.review.issues]


def test_requirement_miss_propagates_and_is_attributed_to_requirement(pipeline):
    task = _task("T-DEF", "修复 kv_store 模块 put 接口的日志缺失问题，要求所有写操作留痕",
                 'put("w", 1)\nassert AUDIT',
                 expected_card={"target_module": "kv_store", "requires_audit_log": True},
                 expected_issues=["missing_audit_log"])
    result = pipeline.run_task(task)
    assert result.card.requires_audit_log is False  # 需求阶段漏提取
    assert result.tests.passed is False             # 测试阶段才暴露
    failure = attribute_failure(task, result)
    assert failure["stage"] == "requirement"        # 归因到最早引入点，而非暴露点


def test_ttl_boundary_failure_attributed_to_codegen(pipeline):
    task = _task("T-TTL", "在 kv_store 模块，TTL 小于等于零时键必须立即过期",
                 'put("z", 1, ttl=0)\nassert get("z") is None',
                 expected_card={"target_module": "kv_store"})
    result = pipeline.run_task(task)
    assert result.tests.passed is False
    assert attribute_failure(task, result)["stage"] == "codegen"


def test_knowledge_retrieval_relevance_and_empty_query():
    store = KnowledgeStore(ROOT / "knowledge_docs")
    docs = store.retrieve("kv_store TTL 过期", k=2)
    assert docs and any(d.doc_id in ("faq", "module_map", "coding_standards") for d in docs)
    assert store.retrieve("", k=2) == []
    assert store.corpus_size() == 3


def test_evaluation_runner_produces_consistent_metrics(tmp_path):
    summary = run_evaluation(ROOT / "knowledge_docs", ROOT / "data", tmp_path, backend="mock")
    h = summary["harness_layer"]
    assert h["tasks"] == 8
    assert h["e2e_success_rate"] == 0.75       # 8 条中 DEF-003 / QA-005 失败
    assert h["review_recall"] == round(2 / 3, 4)  # DEF-003 漏检
    assert {f["stage"] for f in summary["failures"]} == {"requirement", "codegen"}
    m = summary["model_layer"]
    assert set(m["hallucination_fields"]) == {"extra.user_id", "extra.admin"}
    assert m["abstain_cases"] == 3 and m["abstain_violation_rate"] == 0.0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "knowledge_candidates.md").exists()
