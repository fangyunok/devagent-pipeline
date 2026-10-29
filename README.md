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
pytest -q                                # 35 条单元/集成测试
```

产物：`report.md`（双层指标 + 归因 + 失分样例）、`metrics.json`、`summary.json`（机器可读指标 + 门禁结论）、`traces.json`（全链路 trace）、`trace.jsonl`（结构化事件流水：run_id、各阶段耗时、字段）、`knowledge_candidates.md`（评测反哺的知识候选）。

运行日志输出到 stdout（`DEVAGENT_LOG_LEVEL` 可调级别），全链路事件与耗时落盘为 `trace.jsonl`，用于评测回溯与跨版本耗时对比。

切换真实模型（同一套 prompt 与指标）：

```bash
export OPENAI_API_KEY=... OPENAI_BASE_URL=... OPENAI_MODEL=...
python scripts/run_eval.py --backend openai
```

真实模型后端内置**重试 + 指数退避 + 429 限流处理 + 超时收敛**，模型输出解析失败抛结构化异常；相关参数可用 `DEVAGENT_LLM_MAX_RETRIES` / `DEVAGENT_LLM_TIMEOUT` / `DEVAGENT_LLM_BACKOFF` 调整。

## 沙箱执行层

测试环节在**隔离沙箱**中真实执行生成代码，结果按「通过 / 超时 / 异常」分类计数。分层安全模型：

1. 进程/容器隔离：`subprocess` 子进程或 Docker 容器，崩溃不拖累主进程；
2. 资源限制：超时 + 内存上限（Docker 后端额外限 pids）；
3. 危险能力收敛：中和逃逸类内置（读文件 / 交互输入 / 调用栈窥探），动态执行由评审门禁的 `use_eval` 规则拦截。

两个后端共用 `SandboxRunner` 接口，环境无 Docker 时自动降级到 `subprocess`，保证同一条评测命令在任意环境可复现：

```bash
DEVAGENT_SANDBOX_BACKEND=docker python scripts/run_eval.py   # 有 Docker 时容器隔离
DEVAGENT_SANDBOX_BACKEND=subprocess python scripts/run_eval.py  # 默认，纯标准库
```

## 质量门禁与历史基线

评测结果不仅产出报告，更是一道**可拦截质量退化的门禁**：核心指标低于阈值即判不通过，与历史基线（上一次通过的 `summary.json`）逐指标对比，标出涨/跌/平并判定回归。

```bash
# 阈值门禁：核心指标低于阈值即非零退出
python scripts/run_eval.py --threshold e2e_success_rate=0.7 --fail-on-regression

# 基线对比：较历史基线回归即非零退出
python scripts/run_eval.py --baseline reports/latest/summary.json --fail-on-regression
```

内置阈值（`src/devagent/eval/gate.py`）为基准实测值留出空间，拦「明显退化」而非卡正常波动；`summary.json` 内含结构化门禁结论（通过与否 + 违规项 + 阈值 + 基线差异），供 CI 与外部看板直接消费。

## 配置

统一配置层（`src/devagent/config.py`），优先级：代码默认值 < `DEVAGENT_*` 环境变量 < 显式传参。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DEVAGENT_BACKEND` | mock | LLM 后端（mock / openai） |
| `DEVAGENT_LLM_MAX_RETRIES` | 3 | LLM 调用最大重试次数 |
| `DEVAGENT_LLM_TIMEOUT` | 120 | 单次调用超时（秒） |
| `DEVAGENT_LOG_LEVEL` | INFO | 日志级别 |
| `DEVAGENT_TRACE` | true | 是否落盘 trace.jsonl |
| `DEVAGENT_KNOWLEDGE_DIR` | knowledge_docs | 知识库目录 |
| `DEVAGENT_SANDBOX_BACKEND` | subprocess | 沙箱后端（subprocess / docker） |
| `DEVAGENT_SANDBOX_TIMEOUT` | 10 | 沙箱执行超时（秒） |
| `DEVAGENT_SANDBOX_MAX_MEMORY_MB` | 256 | 沙箱内存上限（MB） |

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

35 条测试覆盖：指标口径（幻觉双罚 / 弃答同分母 / 评审召回）、全链路集成（正常任务通过、危险代码被门禁拦截、需求漏提取沿链路传播并正确归因、TTL 边界归因 codegen）、知识库检索相关性、评测 runner 端到端数字一致性、工程底座（配置优先级、trace 落盘与耗时聚合、LLM 重试与结构化异常）、沙箱执行层（隔离、超时、危险能力收敛、结果分类、后端降级）、质量门禁（阈值通过/违规、基线无回归/涨跌回归/弃答越界回归、summary 落盘）。

GitHub Actions 两道流水线：
- **lint**：ruff 静态检查 + 格式检查 + mypy 类型检查；
- **test**：Python 3.10/3.11/3.12 矩阵跑测试（带覆盖率）+ 离线评测（`--fail-on-regression` 门禁，指标跌破阈值即红），报告作为 artifact 上传。

## Roadmap

- 检索层：接入向量检索后端（FAISS / Milvus）与 reranker，保持 `retrieve(query, k)` 接口不变，补齐 Recall@k / MRR 检索指标。
- 基准扩容：接入真实需求 / 缺陷 / MR 语料的清洗与标注流水线，按产品线拆分数据集。
- 执行层：多文件 MR 与增量评审。
- 门禁演进：固定基线快照接入 CI（将本次通过结果固化为下一轮的对比基准），按产品线拆分阈值。
