"""可插拔 LLM 后端（工程化版）。

- LLMError：统一异常，携带阶段与可重试标记；
- MockLLM：确定性规则后端，离线/CI 可复现；
- OpenAICompatibleClient：重试 + 指数退避 + 429 限流 + 超时收敛；
- extract_json：失败抛 LLMOutputError（结构化报错，而非裸抛 JSONDecodeError）。

所有 Agent 只依赖 complete(system, user)，换后端不改业务代码。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Protocol

from .trace import LOGGER


class LLMError(RuntimeError):
    """LLM 调用失败。retryable 为 True 时调用方/客户端可重试。"""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLMOutputError(LLMError):
    """模型输出不符合预期结构（如 JSON 解析失败）。"""


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str:  # pragma: no cover - 协议定义
        ...


def extract_json(text: str) -> dict:
    """从模型输出中容错提取 JSON 对象；失败抛 LLMOutputError。"""
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    if match:
        cleaned = match.group(1)
    else:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"模型输出无法解析为 JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMOutputError(f"模型输出 JSON 顶层应为对象，实际为 {type(parsed).__name__}")
    return parsed


class MockLLM:
    """规则模拟后端。

    用途：无 Key 环境与 CI 中复现确定性结果，包括「模型会犯错」的场景
    （字段幻觉、约束漏提取、边界缺陷），从而演示失败定位与归因链路。
    """

    def complete(self, system: str, user: str) -> str:
        if user.startswith("AGENT: requirement"):
            return self._requirement(user)
        if user.startswith("AGENT: coder"):
            return self._coder(user)
        if user.startswith("AGENT: reviewer"):
            return self._reviewer(user)
        raise LLMError("MockLLM 无法识别的 Agent 请求", retryable=False)

    # ---------- 需求解析 ----------
    def _requirement(self, user: str) -> str:
        text = user.split("INPUT:\n", 1)[1].split("\nKNOWLEDGE:", 1)[0].strip()
        task_id = re.search(r"TASK_ID: (\S+)", user).group(1)
        module = ""
        m = re.search(r"([A-Za-z_]\w*)\s*模块", text)
        if m:
            module = m.group(1)
        # 模拟弱点一：只认「审计」字面量，「留痕」等同义表述会漏提取。
        audit = "审计" in text
        # 模拟弱点二：对文本中的 key=value 缺乏免疫力（身份伪造 / 提示注入会进入 extra）。
        extra = {}
        for k, v in re.findall(r"\b([a-z_]{2,})=([^\s，。；]+)", text):
            extra[k] = v
        criteria = [s.strip() for s in re.split(r"[；;]", text) if s.strip()]
        return json.dumps(
            {
                "task_id": task_id,
                "title": text[:30],
                "target_module": module,
                "language": "python",
                "acceptance_criteria": criteria,
                "requires_audit_log": audit,
                "extra": extra,
            },
            ensure_ascii=False,
        )

    # ---------- 代码生成 ----------
    def _coder(self, user: str) -> str:
        card = json.loads(user.split("TASK_CARD:\n", 1)[1].split("\nKNOWLEDGE:", 1)[0])
        raw_input = (
            user.split("ORIGINAL_INPUT:\n", 1)[1].strip() if "ORIGINAL_INPUT:" in user else ""
        )
        module = card.get("target_module") or "common"
        audit = bool(card.get("requires_audit_log"))
        if module == "kv_store":
            content = KV_TEMPLATE.replace(
                "    # AUDIT_HOOK",
                '    audit_log("put", key)' if audit else "    # AUDIT_HOOK",
            )
        elif module == "sql_parser":
            content = SQL_TEMPLATE
        else:
            content = GENERIC_TEMPLATE
        # 模拟弱点三：把需求里的危险表述照单全收（用于验证评审门禁）。
        if "密码" in raw_input and "写死" in raw_input:
            content += '\nPASSWORD = "debug123"\n'
        if "动态执行" in raw_input:
            content += "\ndef run(expr):\n    return eval(expr)\n"
        return json.dumps(
            {
                "files": [{"path": f"{module}/impl.py", "content": content}],
                "summary": f"实现 {module} 模块需求",
            },
            ensure_ascii=False,
        )

    # ---------- 评审 ----------
    def _reviewer(self, user: str) -> str:
        card = json.loads(user.split("TASK_CARD:\n", 1)[1].split("\nCODE:", 1)[0])
        code = user.split("CODE:\n", 1)[1].split("\nKNOWLEDGE:", 1)[0]
        issues = []
        if card.get("requires_audit_log") and "audit_log(" not in code.replace(
            "def audit_log(", ""
        ):
            issues.append(
                {
                    "severity": "major",
                    "category": "missing_audit_log",
                    "location": "put",
                    "message": "任务卡要求审计日志，但写操作未调用 audit_log",
                }
            )
        if re.search(r'(?i)(password|secret)\s*=\s*"[^"]+"', code):
            issues.append(
                {
                    "severity": "major",
                    "category": "hardcoded_secret",
                    "location": "global",
                    "message": "检测到硬编码口令，违反编码规范 SEC-01",
                }
            )
        if re.search(r"\beval\(", code):
            issues.append(
                {
                    "severity": "critical",
                    "category": "use_eval",
                    "location": "run",
                    "message": "禁止使用 eval 动态执行，违反编码规范 SEC-02",
                }
            )
        if re.search(r"except\s*:", code):
            issues.append(
                {
                    "severity": "minor",
                    "category": "bare_except",
                    "location": "-",
                    "message": "裸 except 会吞掉异常，建议捕获具体异常类型",
                }
            )
        approved = not any(i["severity"] in ("critical", "major") for i in issues)
        return json.dumps({"issues": issues, "approved": approved}, ensure_ascii=False)


KV_TEMPLATE = """import time

STORE = {}
AUDIT = []


def audit_log(action, key):
    AUDIT.append((action, key))


def put(key, value, ttl=None):
    expire = None
    if ttl is not None and ttl > 0:
        expire = time.time() + ttl
    STORE[key] = (value, expire)
    # AUDIT_HOOK


def get(key):
    if key not in STORE:
        return None
    value, expire = STORE[key]
    if expire is not None and time.time() >= expire:
        del STORE[key]
        return None
    return value
"""

SQL_TEMPLATE = """def parse_where(sql):
    \"\"\"解析简单等值 WHERE 子句，返回条件字典。\"\"\"
    result = {}
    low = sql.lower()
    if "where" not in low:
        return result
    clause = sql[low.index("where") + 5:].strip().rstrip(";")
    for part in clause.split("and"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip().strip("'\\\"")
    return result
"""

GENERIC_TEMPLATE = """def handle():
    return "ok"
"""


class OpenAICompatibleClient:
    """OpenAI 兼容后端：重试 + 指数退避 + 429 限流 + 超时收敛。"""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ):
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        if not self.api_key:
            raise LLMError("使用真实模型后端前请设置 OPENAI_API_KEY", retryable=False)

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                retryable = exc.code in (429, 500, 502, 503, 504)
                last_err = LLMError(f"LLM 请求失败 HTTP {exc.code}", retryable=retryable)
                if not retryable or attempt >= self.max_retries:
                    break
                wait = self.backoff_base * (2**attempt)
                LOGGER.warning(
                    "LLM 请求 HTTP %s，第 %d 次重试，%.1fs 后重试", exc.code, attempt + 1, wait
                )
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError) as exc:
                retryable = True
                last_err = LLMError(f"LLM 网络/超时错误: {exc}", retryable=True)
                if attempt >= self.max_retries:
                    break
                wait = self.backoff_base * (2**attempt)
                LOGGER.warning("LLM 网络错误，第 %d 次重试，%.1fs 后重试", attempt + 1, wait)
                time.sleep(wait)
        raise last_err if last_err else LLMError("LLM 调用失败", retryable=False)


def get_llm(backend: str = "mock", config=None) -> LLMClient:
    if config is None:
        from .config import default_config

        config = default_config
    if backend == "mock":
        return MockLLM()
    if backend == "openai":
        return OpenAICompatibleClient(
            model=config.openai_model,
            base_url=config.openai_base_url,
            api_key=config.openai_api_key,
            timeout=config.llm_timeout_seconds,
            max_retries=config.llm_max_retries,
            backoff_base=config.llm_backoff_base_seconds,
        )
    raise LLMError(f"未知后端: {backend}", retryable=False)
