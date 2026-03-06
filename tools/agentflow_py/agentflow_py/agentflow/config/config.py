import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ServerConfig:
    transport: str = "stdio"
    sse_addr: str = ":8080"
    dashboard_addr: str = ":8081"
    log_level: str = "info"


@dataclass
class RedisConfig:
    addr: str = "127.0.0.1:6379"
    password: str = ""
    db: int = 0
    pool_size: int = 20
    min_idle_conns: int = 5
    dial_timeout: int = 5
    read_timeout: int = 3
    write_timeout: int = 3
    key_prefix: str = "af:"


@dataclass
class SQLiteConfig:
    db_file: str = "agentflow_archive.db"
    max_open_conns: int = 1
    journal_mode: str = "WAL"
    busy_timeout: int = 5000


@dataclass
class ArchiveConfig:
    interval_minutes: int = 60
    task_archive_days: int = 7
    high_value_task_days: int = 30       # 高价值任务延长保留天数
    high_value_difficulty: int = 7       # 高价值任务难度阈值
    high_value_tokens: int = 10000       # 高价值任务 tokens 阈值
    metrics_archive_days: int = 30
    archive_top_n: int = 10
    active_exp_query_days: int = 60      # 活跃引用经验延长保留天数
    active_exp_query_threshold: int = 1  # 活跃引用阈值


@dataclass
class StorageConfig:
    data_dir: str = "./data"
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)


@dataclass
class CompileConfig:
    default_budget: int = 2000
    min_budget: int = 1200
    max_budget: int = 4000
    truncation_warn_pct: int = 50


@dataclass
class ContextConfig:
    compile: CompileConfig = field(default_factory=CompileConfig)


@dataclass
class SkillLimits:
    max_rules: int = 20
    max_anti_patterns: int = 15
    max_best_practices: int = 15
    distillation_threshold: int = 15
    stale_threshold: int = 10


@dataclass
class CanaryConfig:
    enabled: bool = True
    ratio: float = 0.2
    min_samples: int = 5
    promote_threshold: float = 0.95
    rollback_threshold: float = 0.90


@dataclass
class SkillConfig:
    limits: SkillLimits = field(default_factory=SkillLimits)
    cross_skill_promotion_threshold: int = 3
    canary: CanaryConfig = field(default_factory=CanaryConfig)


@dataclass
class PatternConfig:
    min_evidence: int = 3
    daily_limit: int = 5


@dataclass
class ExperienceConfig:
    stream_maxlen: int = 500
    min_description_length: int = 50
    low_confidence_threshold: float = 0.3


@dataclass
class ScoringConfig:
    early_phase_threshold: int = 20
    mid_phase_threshold: int = 50
    time_decay_factor: float = 0.95


@dataclass
class HumanCalibrationConfig:
    every_n_evolutions: int = 7
    sample_size: int = 3


@dataclass
class EvolutionConfig:
    pattern: PatternConfig = field(default_factory=PatternConfig)
    experience: ExperienceConfig = field(default_factory=ExperienceConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    human_calibration: HumanCalibrationConfig = field(default_factory=HumanCalibrationConfig)
    evo_log_maxlen: int = 200


@dataclass
class FixAntiLoopConfig:
    similarity_warn_threshold: float = 0.6
    similarity_block_threshold: float = 0.85
    max_same_approach_attempts: int = 2


@dataclass
class FixSessionConfig:
    max_attempts_per_session: int = 20
    stale_timeout_hours: int = 168
    auto_close_on_success: bool = False


@dataclass
class FixArchiveConfig:
    resolved_archive_days: int = 30
    abandoned_archive_days: int = 14
    stale_timeout_days: int = 7


@dataclass
class FixFeedbackConfig:
    min_decay_factor: float = 0.1
    blacklist_misleading_threshold: int = 3
    positive_feedback_recovery: float = 0.1
    feedback_detail_ttl_days: int = 90


@dataclass
class FixExperienceConfig:
    anti_loop: FixAntiLoopConfig = field(default_factory=FixAntiLoopConfig)
    session: FixSessionConfig = field(default_factory=FixSessionConfig)
    archive: FixArchiveConfig = field(default_factory=FixArchiveConfig)
    feedback: FixFeedbackConfig = field(default_factory=FixFeedbackConfig)


@dataclass
class SafetyConfig:
    consecutive_degradation_threshold: int = 3
    test_cases_dir: str = "./data/test_cases"
    high_impact_threshold: float = 0.7


@dataclass
class LockConfig:
    default_ttl: int = 300
    heartbeat_interval: int = 30
    heartbeat_timeout: int = 90


@dataclass
class WatchdogConfig:
    enabled: bool = True
    scan_interval: int = 30
    soft_timeout: int = 1500
    heartbeat_timeout: int = 1800
    max_retries: int = 3


@dataclass
class ToolsConfig:
    layer1_enabled: bool = True
    layer2_enabled: bool = False
    layer2_auto_enable: bool = True


@dataclass
class TokenAlertConfig:
    green_threshold: int = 60000
    yellow_threshold: int = 90000


@dataclass
class RedisMemoryConfig:
    warn_threshold: int = 80
    critical_threshold: int = 100


@dataclass
class MetricsConfig:
    token_alerts: TokenAlertConfig = field(default_factory=TokenAlertConfig)
    redis_memory: RedisMemoryConfig = field(default_factory=RedisMemoryConfig)


@dataclass
class SemanticSearchConfig:
    """语义搜索配置（向量嵌入）"""
    enabled: bool = False
    provider: str = "disabled"   # openai/ollama/disabled
    api_key: str = ""
    base_url: str = "https://api.openai.com"  # API 基础 URL（Ollama 用 http://localhost:11434）
    model: str = "text-embedding-3-small"
    dimension: int = 1536
    cache_ttl: int = 86400       # 向量缓存 TTL（秒）
    timeout: int = 10            # API 请求超时（秒）
    semantic_weight: float = 0.6 # 语义分数权重（0~1）


@dataclass
class WebhookConfig:
    """Webhook 通知配置"""
    enabled: bool = True
    max_retries: int = 3   # 发送失败最大重试次数
    timeout_sec: int = 10  # 单次请求超时（秒）


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    sqlite: SQLiteConfig = field(default_factory=SQLiteConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    skill: SkillConfig = field(default_factory=SkillConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    fix_experience: FixExperienceConfig = field(default_factory=FixExperienceConfig)
    semantic_search: SemanticSearchConfig = field(default_factory=SemanticSearchConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    lock: LockConfig = field(default_factory=LockConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    language: str = "zh"  # 默认语言：zh（中文）或 en（英文）

    def get_sqlite_path(self) -> str:
        return str(Path(self.storage.data_dir) / self.sqlite.db_file)

    def get_redis_data_dir(self) -> str:
        return str(Path(self.storage.data_dir) / "redis")


def _from_dict(cls, data: dict):
    """Recursively build dataclass from dict."""
    if not isinstance(data, dict):
        return data
    import dataclasses
    if not dataclasses.is_dataclass(cls):
        return data
    hints = {f.name: f for f in dataclasses.fields(cls)}
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in data:
            val = data[f.name]
            ft = f.type if isinstance(f.type, type) else None
            # Try to resolve field type
            if ft is None:
                try:
                    import typing
                    # For Python 3.10+ use get_type_hints
                    hints_map = typing.get_type_hints(cls)
                    ft = hints_map.get(f.name)
                except Exception:
                    ft = None
            if ft is not None and dataclasses.is_dataclass(ft) and isinstance(val, dict):
                kwargs[f.name] = _from_dict(ft, val)
            else:
                kwargs[f.name] = val
        else:
            kwargs[f.name] = f.default if f.default is not dataclasses.MISSING else f.default_factory()
    return cls(**kwargs)


def _apply_env_overrides(cfg: Config) -> None:
    if v := os.environ.get("AF_SERVER_TRANSPORT"):
        cfg.server.transport = v
    if v := os.environ.get("AF_SERVER_SSE_ADDR"):
        cfg.server.sse_addr = v
    if v := os.environ.get("AF_SERVER_LOG_LEVEL"):
        cfg.server.log_level = v
    if v := os.environ.get("AF_REDIS_ADDR"):
        cfg.redis.addr = v
    if v := os.environ.get("AF_REDIS_PASSWORD"):
        cfg.redis.password = v
    if v := os.environ.get("AF_STORAGE_DATA_DIR"):
        cfg.storage.data_dir = v
    if os.environ.get("AF_TOOLS_LAYER2_ENABLED", "").lower() == "true":
        cfg.tools.layer2_enabled = True


def _ensure_data_dirs(cfg: Config) -> None:
    dirs = [
        cfg.storage.data_dir,
        cfg.safety.test_cases_dir,
        cfg.get_redis_data_dir(),
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def load_config(path: Optional[str] = None) -> Config:
    cfg = Config()
    if path and Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        cfg = _from_dict(Config, raw)
    _apply_env_overrides(cfg)
    _ensure_data_dirs(cfg)
    return cfg
