"""失败归因：沿链路找「最早引入失败的环节」，而不是只记录失败在哪暴露。

例：写操作留痕要求在需求阶段被漏提取，直到测试断言/评审才暴露，
根因仍记 requirement，并保留证据链（任务卡缺字段 → 代码无 audit_log → 断言失败）。
"""

from __future__ import annotations

from ..schemas import PipelineResult


def attribute_failure(task: dict, result: PipelineResult) -> dict | None:
    """对 e2e 失败样本返回 {stage, evidence, suggestion}；成功返回 None。"""
    expected = task.get("expected_card", {})
    expected_issues = task.get("expected_issues", [])
    actual_issues = [i["category"] for i in result.review.issues]
    gate_correct = (not result.review.approved) if expected_issues else result.review.approved
    e2e_success = result.tests.passed and gate_correct
    if e2e_success:
        return None

    # 1) 需求阶段：受控字段缺失/错误是最早引入点
    if expected.get("requires_audit_log") and not result.card.requires_audit_log:
        return {
            "stage": "requirement",
            "evidence": "任务卡 requires_audit_log=false（期望 true）→ 代码未接入 audit_log → "
            f"测试/评审暴露（test_passed={result.tests.passed}）",
            "suggestion": "知识库沉淀「留痕/日志/审计同义，写操作必须显式声明审计要求」",
        }
    if expected.get("target_module") and result.card.target_module != expected["target_module"]:
        return {
            "stage": "requirement",
            "evidence": (
                f"target_module={result.card.target_module!r}（期望 {expected['target_module']!r}）"
            ),
            "suggestion": "模块地图补充该模块的别名与归属描述",
        }
    # 2) 编码阶段：任务卡正确但代码未通过真实执行
    if not result.tests.passed:
        detail = "; ".join(f["message"] for f in result.tests.failures)[:200]
        return {
            "stage": "codegen",
            "evidence": f"沙箱执行失败：{detail}",
            "suggestion": "将失败断言语义沉淀为踩坑 FAQ（边界条件/异常路径）",
        }
    # 3) 评审阶段：测试通过但门禁决策错误
    if not gate_correct:
        missed = sorted(set(expected_issues) - set(actual_issues))
        return {
            "stage": "review",
            "evidence": f"门禁决策与期望不符，漏检类别={missed}",
            "suggestion": "评审规范补充对应检查项，或调整 issue 严重级别映射",
        }
    return {"stage": "unknown", "evidence": "需人工检查 trace", "suggestion": "补充归因规则"}
