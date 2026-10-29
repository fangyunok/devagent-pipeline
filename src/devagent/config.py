"""统一配置层。

配置优先级：代码默认值 < 环境变量（DEVAGENT_ 前缀）< 显式传参。
所有模块从这里取配置，避免常量散落、便于多环境复用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw is not None else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw is not None else default


@dataclass
class Config:
    # LLM 后端
    backend: str = "mock"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # LLM 调用工程参数
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 3
    llm_backoff_base_seconds: float = 1.0

    # 知识库
    knowledge_dir: str = "knowledge_docs"
    knowledge_top_k: int = 3

    # 日志与 trace
    log_level: str = "INFO"
    trace_enabled: bool = True

    # 沙箱执行（阶段二接入容器隔离时复用）
    sandbox_timeout_seconds: float = 10.0
    sandbox_max_memory_mb: int = 256
    sandbox_backend: str = "subprocess"  # 预留：docker


def load_config(overrides: dict | None = None) -> Config:
    """按 默认值 → 环境变量 → overrides 的顺序组装配置。"""
    cfg = Config(
        backend=os.environ.get("DEVAGENT_BACKEND", "mock"),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        llm_timeout_seconds=_env_float("DEVAGENT_LLM_TIMEOUT", 120.0),
        llm_max_retries=_env_int("DEVAGENT_LLM_MAX_RETRIES", 3),
        llm_backoff_base_seconds=_env_float("DEVAGENT_LLM_BACKOFF", 1.0),
        knowledge_dir=os.environ.get("DEVAGENT_KNOWLEDGE_DIR", "knowledge_docs"),
        knowledge_top_k=_env_int("DEVAGENT_KNOWLEDGE_TOP_K", 3),
        log_level=os.environ.get("DEVAGENT_LOG_LEVEL", "INFO"),
        trace_enabled=_env_bool("DEVAGENT_TRACE", True),
        sandbox_timeout_seconds=_env_float("DEVAGENT_SANDBOX_TIMEOUT", 10.0),
        sandbox_max_memory_mb=_env_int("DEVAGENT_SANDBOX_MAX_MEMORY_MB", 256),
        sandbox_backend=os.environ.get("DEVAGENT_SANDBOX_BACKEND", "subprocess"),
    )
    if overrides:
        for key, value in overrides.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg


# 供简单脚本直接使用的模块级默认配置
default_config = load_config()
