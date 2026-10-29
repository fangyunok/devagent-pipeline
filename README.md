# devagent-pipeline

[![CI](https://github.com/fangyunok/devagent-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/fangyunok/devagent-pipeline/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)

多智能体「需求 → 编码 → 测试 → 评审」全链路 Pipeline，配套 **Harness + Model 双层评测 Harness** 与 **领域知识库 RAG 闭环**。

面向真实研发链路（需求 / 缺陷 / QA issue / 历史 MR）建设评测基准：每个环节的产出都是结构化 artifact，测试环节在沙箱中**真实执行**生成代码，评审环节作为质量门禁拦截危险变更；失败案例沿链路归因到「最早引入点」，归因结果自动转为知识库候选条目，形成 **量 → 反馈 → 沉淀 → 再量** 闭环。

零三方依赖、开箱即用；LLM 后端可插拔（内置离线后端复现评测数字，同一套 prompt 一键切换真实模型）。

## 架构

```
                 ┌──────────────────────────────────────────────┐
                 │           领域知识库（knowledge_docs/）        │
                 │   模块地图 · 编码规范 · 踩坑 FAQ（可持续更新）   │
                 └───────────────▲──────────────────────────────┘
                                 │ 检索注入（RAG）
 需求/缺陷/QA issue/历史 MR        │
        │                       │
        ▼                       │
 ┌─────────────┐   TaskCard  ┌──┴───────┐  CodeChange  ┌──────────┐
 │ Requirement │ ──────────► │  Coder   │ ───────────► │  Tester  │
 │    Agent    │             │  Agent   │              │  Agent   │
 └─────────────┘             └──────────┘              └────┬─────┘
      结构化任务卡                代码变更（MR）                │ 沙箱真实执行
                                                             ▼
                                                      ┌──────────────┐
                                                      │ Reviewer     │  问题定位 + 门禁
                                                      │ Agent        │  （ai-review）
                                                      └──────┬───────┘
                                                             ▼
                              双层评测 Harness（eval/）
                Model 层：字段级 P/R/F1 · 幻觉 · 弃答 · 注入/身份伪造探针
                Harness 层：执行通过率 · 评审 P/R · 门禁准确率 · e2e 成功率
                                                             │
                                          失败归因（最早引入点）+ 评测报告
                                                             ▼
                                          知识库候选条目 → 合入后重跑对比
```

## 快速开始

```bash
pip install -e ".[dev]"
python scripts/run_eval.py --explain 5   # 跑双层评测，报告写入 reports/latest/
pytest -q                                # 11 条单元/集成测试
```

产物：`report.md`（双层指标 + 归因 + 失分样例）、`metrics.json`、`traces.json`（全链路 trace）、`knowledge_candidates.md`（评测反哺的知识候选）。

切换真实模型（同一套 prompt 与指标）：

```bash
export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
python scripts/run_eval.py --backend openai
```

## 评测基准设计

`data/eval_tasks.jsonl`：8 条全链路任务，来源覆盖需求、缺陷、QA issue、历史 MR 回放，每条带期望任务卡、公开测试（真实执行）、期望评审检出类别。

`data/model_probes.jsonl`：6 条 Model 层探针，按风险类别标注——显式标识、隐式缺失、纯弃答、身份伪造（`user_id=42`）、提示注入（伪造系统指令 `admin=true`）。身份与指令类内容一律不得进入任务卡字段，身份以服务端会话为准。

## 指标口径与实测（内置离线后端，可复现）

**Model 层**：micro 字段级 P/R/F1，precision 分母为模型实际吐出字段数（幻觉计假阳性，值不匹配双罚）；弃答违例率以「期望为空」用例为分母，分子分母同口径。

| 指标 | 实测值 |
|---|---|
| 字段级 Precision / Recall / F1 | 0.8571 / 0.8571 / 0.8571（TP 12 · FP 2 · FN 2） |
| 幻觉字段 | `extra.user_id`、`extra.admin`（身份伪造与注入探针捕获） |
| 弃答违例 | 0 / 3 |

**Harness 层**：来自沙箱真实执行与评审实际输出。

| 指标 | 实测值 |
|---|---|
| 测试通过率（沙箱真实执行） | 0.7500 |
| 评审 Precision / Recall | 1.0000 / 0.6667 |
| 门禁准确率 | 0.8750 |
| 端到端成功率（测试通过 且 门禁正确） | 0.7500 |

## 失败归因示例（定位到最早引入点，而非暴露点）

- **DEF-003（缺陷单）→ 归因 requirement**：需求写「写操作留痕」，任务卡漏提取审计要求 → 代码未接入 `audit_log` → 测试断言与评审在下游才暴露。证据链完整记录在报告与 trace 中。
- **QA-005（QA issue）→ 归因 codegen**：任务卡正确，但生成代码把 `ttl<=0` 当作永不过期，沙箱断言 `get("z") is None` 失败。

两条失败 + 两个幻觉探针自动转化为知识库候选条目（见 `reports/latest/knowledge_candidates.md`），合入 `knowledge_docs/` 后重跑同一命令即可量化调优收益——评测结果反向优化知识库的闭环由此成立。

## 测试与 CI

11 条测试覆盖：指标口径（幻觉双罚 / 弃答同分母 / 评审召回）、全链路集成（正常任务通过、危险代码被门禁拦截、需求漏提取沿链路传播并正确归因、TTL 边界归因 codegen）、知识库检索相关性、评测 runner 端到端数字一致性。

GitHub Actions：Python 3.10/3.11/3.12 矩阵跑测试 + 离线评测，报告作为 artifact 上传。

## Roadmap

- 检索层：接入向量检索后端（FAISS / Milvus）与 reranker，保持 `retrieve(query, k)` 接口不变，补齐 Recall@k / MRR 检索指标。
- 基准扩容：接入真实需求 / 缺陷 / MR 语料的清洗与标注流水线，按产品线拆分数据集。
- 质量门禁：固定基准 + 阈值门禁接入 CI，指标跌破即红。
- 执行层：沙箱资源限额与超时控制、多文件 MR 与增量评审。
