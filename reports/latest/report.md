# 评测报告（Harness + Model 双层）

## 指标口径
- 字段级 P/R/F1：micro 汇总；precision 分母为模型实际吐出字段数，幻觉字段计假阳性，值不匹配同时计假阳性与漏检。
- 弃答违例率：以 expected 为空的用例为分母，实际吐出任何字段即违例。
- test_pass_rate：生成代码在沙箱中真实执行断言的通过率（非模型自述）。
- review P/R：评审检出类别与基准期望类别比对；gate_accuracy：门禁决策与期望一致率。
- e2e_success：测试通过 且 门禁决策正确。

## 运行配置
- LLM 后端：mock；知识库文档：3 篇
- 全链路任务：8 条（需求/缺陷/QA issue/历史 MR）；Model 层探针：6 条

## Model 层（结构化产出质量）
| 指标 | 值 |
|---|---|
| 字段级 Precision | 0.8571 |
| 字段级 Recall | 0.8571 |
| 字段级 F1 | 0.8571 |
| TP / FP / FN | 12 / 2 / 2 |
| 幻觉字段 | extra.admin, extra.user_id |
| 弃答违例 | 0 / 3 |

## Harness 层（端到端运行质量）
| 指标 | 值 |
|---|---|
| 测试通过率（真实执行） | 0.7500 |
| 评审 Precision / Recall | 1.0000 / 0.6667 |
| 门禁准确率 | 0.8750 |
| 端到端成功率 | 0.7500 |

## 失败案例与归因（最早引入点）
| 任务 | 来源 | 归因环节 | 证据链 |
|---|---|---|---|
| DEF-003 | defect | requirement | 任务卡 requires_audit_log=false（期望 true）→ 代码未接入 audit_log → 测试/评审暴露（test_passed=False） |
| QA-005 | qa_issue | codegen | 沙箱执行失败：ttl<=0 必须立即过期 |

## Model 层失分样例
### DEF-003
- 期望字段：`{"target_module": "kv_store", "requires_audit_log": true}`
- 实际字段：`{"target_module": "kv_store"}`
- 幻觉=[] 缺失=['requires_audit_log'] 值不匹配=[]

## 知识库沉淀建议（量 → 反馈 → 沉淀 → 再量）
本轮评测产出 3 条候选知识条目，见 knowledge_candidates.md。
将候选条目合入 knowledge_docs/ 后重跑同一命令，对比报告即可量化知识库调优收益。
