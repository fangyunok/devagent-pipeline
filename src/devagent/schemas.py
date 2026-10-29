"""全链路结构化 artifact 定义。

各 Agent 之间只通过这些 schema 传递结果，保证：
1. 每个环节的产出可被独立评测（Model 层字段级指标）；
2. 失败案例可定位到具体环节（归因分析）；
3. artifact 可落盘为评测样本，回流为新的评测数据。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskCard:
    """需求解析环节的结构化产出（任务卡）。"""

    task_id: str
    title: str = ""
    target_module: str = ""
    language: str = "python"
    acceptance_criteria: list[str] = field(default_factory=list)
    requires_audit_log: bool = False
    # 模型吐出的、不在受控字段集合内的内容会进入 extra，用于幻觉检测。
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskCard:
        known = {
            "task_id", "title", "target_module", "language",
            "acceptance_criteria", "requires_audit_log",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = dict(data.get("extra") or {})
        # 模型若在顶层输出了未定义字段，统一归入 extra（幻觉口径：实际吐出即计入）。
        for k, v in data.items():
            if k not in known and k != "extra":
                extra[k] = v
        kwargs["extra"] = extra
        kwargs.setdefault("task_id", "")
        return cls(**kwargs)


@dataclass
class CodeChange:
    """编码环节产出：一次变更（可视为一个 MR 的最小表示）。"""

    task_id: str
    files: list[dict[str, str]] = field(default_factory=list)  # [{path, content}]
    summary: str = ""
    retrieved_knowledge: list[str] = field(default_factory=list)  # 注入的知识文档 id

    @property
    def content(self) -> str:
        return "\n".join(f.get("content", "") for f in self.files)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestReport:
    """测试环节产出：真实沙箱执行结果（非模型自述）。"""

    task_id: str
    passed: bool
    total: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)  # [{name, message}]
    generated_tests: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewReport:
    """评审环节产出（ai-review）：问题定位 + 门禁结论。"""

    task_id: str
    issues: list[dict[str, str]] = field(default_factory=list)
    # issue: {severity: critical/major/minor, category, location, message}
    approved: bool = True
    retrieved_knowledge: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineResult:
    """一次全链路运行的完整 trace，归因与报告都从这里取数。"""

    task_id: str
    card: TaskCard
    code: CodeChange
    tests: TestReport
    review: ReviewReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "card": self.card.to_dict(),
            "code": self.code.to_dict(),
            "tests": self.tests.to_dict(),
            "review": self.review.to_dict(),
        }
