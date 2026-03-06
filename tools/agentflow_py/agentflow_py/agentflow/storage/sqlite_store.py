import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from agentflow.config import SQLiteConfig


class SQLiteStore:
    """Async SQLite cold storage."""

    def __init__(self, cfg: SQLiteConfig, db_path: str, logger: logging.Logger):
        self._cfg = cfg
        self._db_path = db_path
        self._logger = logger
        self._db: Optional[aiosqlite.Connection] = None

    @classmethod
    async def create(cls, cfg: SQLiteConfig, db_path: str, logger: logging.Logger) -> "SQLiteStore":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        store = cls(cfg, db_path, logger)
        store._db = await aiosqlite.connect(db_path)
        store._db.row_factory = aiosqlite.Row
        await store._db.execute(f"PRAGMA journal_mode={cfg.journal_mode}")
        await store._db.execute(f"PRAGMA busy_timeout={cfg.busy_timeout}")
        await store._db.execute("PRAGMA foreign_keys=ON")
        await store._migrate()
        logger.info(f"SQLite冷存储初始化成功 path={db_path}")
        return store

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def health_check(self) -> None:
        await self._db.execute("SELECT 1")

    async def _migrate(self) -> None:
        migrations = [
            """CREATE TABLE IF NOT EXISTS archived_tasks (
                task_id TEXT PRIMARY KEY,
                goal_id TEXT,
                data JSON,
                completed_at DATETIME,
                archived_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS archived_experiences (
                exp_id TEXT PRIMARY KEY,
                type TEXT,
                skill_type TEXT,
                category TEXT,
                data JSON,
                created_at DATETIME,
                archived_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            "CREATE INDEX IF NOT EXISTS idx_exp_skill ON archived_experiences(skill_type)",
            "CREATE INDEX IF NOT EXISTS idx_exp_type ON archived_experiences(type)",
            """CREATE TABLE IF NOT EXISTS agent_archives (
                archive_id TEXT PRIMARY KEY,
                data JSON,
                score REAL,
                created_at DATETIME,
                note TEXT
            )""",
            "CREATE INDEX IF NOT EXISTS idx_archive_score ON agent_archives(score DESC)",
            """CREATE TABLE IF NOT EXISTS evolution_logs (
                log_id TEXT PRIMARY KEY,
                evolution_type TEXT,
                target TEXT,
                data JSON,
                created_at DATETIME
            )""",
            """CREATE TABLE IF NOT EXISTS historical_metrics (
                metric_key TEXT,
                date TEXT,
                data JSON,
                PRIMARY KEY (metric_key, date)
            )""",
            """CREATE TABLE IF NOT EXISTS archived_tool_call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT,
                tool_name TEXT NOT NULL,
                file_path TEXT,
                action TEXT,
                brief TEXT,
                timestamp TEXT,
                archived_at TEXT DEFAULT (datetime('now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_audit_task ON archived_tool_call_logs(task_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_agent ON archived_tool_call_logs(agent_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_tool ON archived_tool_call_logs(tool_name)",
            """CREATE TABLE IF NOT EXISTS archived_fix_sessions (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                agent_id TEXT,
                problem TEXT NOT NULL,
                error_msg TEXT,
                error_type TEXT,
                status TEXT NOT NULL,
                resolution TEXT,
                attempt_count INTEGER DEFAULT 0,
                final_experience TEXT,
                data TEXT NOT NULL,
                tags TEXT,
                created_at TEXT,
                resolved_at TEXT,
                archived_at TEXT DEFAULT (datetime('now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_fix_session_status ON archived_fix_sessions(status)",
            "CREATE INDEX IF NOT EXISTS idx_fix_session_error_type ON archived_fix_sessions(error_type)",
            "CREATE INDEX IF NOT EXISTS idx_fix_session_task ON archived_fix_sessions(task_id)",
            """CREATE TABLE IF NOT EXISTS archived_fix_attempts (
                id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                approach TEXT NOT NULL,
                reasoning TEXT,
                result TEXT,
                result_detail TEXT,
                label TEXT,
                modified_files TEXT,
                code_changes TEXT,
                confidence REAL DEFAULT 0,
                created_at TEXT,
                archived_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (session_id, id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_fix_attempt_label ON archived_fix_attempts(label)",
            "CREATE INDEX IF NOT EXISTS idx_fix_attempt_result ON archived_fix_attempts(result)",
            """CREATE TABLE IF NOT EXISTS task_recovery_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT,
                event_type TEXT NOT NULL,
                detail TEXT,
                progress REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_recovery_task ON task_recovery_events(task_id)",
            "CREATE INDEX IF NOT EXISTS idx_recovery_agent ON task_recovery_events(agent_id)",
            "CREATE INDEX IF NOT EXISTS idx_recovery_type ON task_recovery_events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_recovery_time ON task_recovery_events(created_at)",
            """CREATE TABLE IF NOT EXISTS compilation_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                skill_type TEXT,
                detail_level TEXT,
                budget INTEGER,
                total_tokens INTEGER,
                layer_stats TEXT NOT NULL,
                truncated_layers TEXT,
                context_sufficient INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_comp_metrics_skill ON compilation_metrics(skill_type)",
            "CREATE INDEX IF NOT EXISTS idx_comp_metrics_time ON compilation_metrics(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_comp_metrics_detail ON compilation_metrics(detail_level)",
            """CREATE TABLE IF NOT EXISTS migration_meta (
                version INTEGER PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                description TEXT
            )""",
        ]
        async with self._db.cursor() as cur:
            for sql in migrations:
                await cur.execute(sql)
        await self._db.commit()
        self._logger.debug("SQLite表迁移完成")

    # --- Generic execute helpers ---
    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self._db.execute(sql, params)
        await self._db.commit()

    async def executemany(self, sql: str, params_list: List[tuple]) -> None:
        await self._db.executemany(sql, params_list)
        await self._db.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        async with self._db.execute(sql, params) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return dict(row)

    async def fetchall(self, sql: str, params: tuple = ()) -> List[Dict]:
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # --- Specific archive operations ---
    async def archive_task(self, task_id: str, goal_id: str, data: str, completed_at: str) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO archived_tasks (task_id, goal_id, data, completed_at)
               VALUES (?, ?, ?, ?)""",
            (task_id, goal_id, data, completed_at),
        )

    async def archive_experience(self, exp_id: str, exp_type: str, skill_type: str,
                                  category: str, data: str, created_at: str) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO archived_experiences
               (exp_id, type, skill_type, category, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (exp_id, exp_type, skill_type, category, data, created_at),
        )

    async def archive_agent_snapshot(self, archive_id: str, data: str, score: float,
                                      created_at: str, note: str) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO agent_archives (archive_id, data, score, created_at, note)
               VALUES (?, ?, ?, ?, ?)""",
            (archive_id, data, score, created_at, note),
        )

    async def archive_evolution_log(self, log_id: str, evo_type: str,
                                     target: str, data: str, created_at: str) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO evolution_logs (log_id, evolution_type, target, data, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (log_id, evo_type, target, data, created_at),
        )

    async def archive_metric(self, metric_key: str, date: str, data: str) -> None:
        await self.execute(
            "INSERT OR REPLACE INTO historical_metrics (metric_key, date, data) VALUES (?, ?, ?)",
            (metric_key, date, data),
        )

    async def archive_tool_call_logs(self, rows: List[Dict]) -> None:
        sql = """INSERT INTO archived_tool_call_logs
                 (task_id, agent_id, tool_name, file_path, action, brief, timestamp)
                 VALUES (?, ?, ?, ?, ?, ?, ?)"""
        params = [
            (r.get("task_id", ""), r.get("agent_id", ""), r.get("tool_name", ""),
             r.get("file_path", ""), r.get("action", ""), r.get("brief", ""),
             r.get("timestamp", ""))
            for r in rows
        ]
        await self.executemany(sql, params)

    async def archive_fix_session(self, s: Dict, attempts: List[Dict]) -> None:
        await self.execute(
            """INSERT OR REPLACE INTO archived_fix_sessions
               (id, task_id, agent_id, problem, error_msg, error_type, status,
                resolution, attempt_count, final_experience, data, tags, created_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (s["id"], s.get("task_id", ""), s.get("agent_id", ""), s.get("problem", ""),
             s.get("error_msg", ""), s.get("error_type", ""), s.get("status", ""),
             s.get("resolution", ""), s.get("attempt_count", 0),
             s.get("final_experience", ""), s.get("data", "{}"),
             s.get("tags", ""), s.get("created_at", ""), s.get("resolved_at", "")),
        )
        for attempt in attempts:
            await self.execute(
                """INSERT OR REPLACE INTO archived_fix_attempts
                   (id, session_id, approach, reasoning, result, result_detail,
                    label, modified_files, code_changes, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (attempt.get("id", ""), s["id"], attempt.get("approach", ""),
                 attempt.get("reasoning", ""), attempt.get("result", ""),
                 attempt.get("result_detail", ""), attempt.get("label", ""),
                 attempt.get("modified_files", ""), attempt.get("code_changes", ""),
                 attempt.get("confidence", 0.0), attempt.get("created_at", "")),
            )

    async def record_recovery_event(self, task_id: str, agent_id: str,
                                     event_type: str, detail: str, progress: float) -> None:
        await self.execute(
            """INSERT INTO task_recovery_events (task_id, agent_id, event_type, detail, progress)
               VALUES (?, ?, ?, ?, ?)""",
            (task_id, agent_id, event_type, detail, progress),
        )

    async def query_recovery_events(self, task_id: str) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM task_recovery_events WHERE task_id=? ORDER BY created_at ASC",
            (task_id,),
        )

    async def save_compilation_metrics(self, task_id: str, skill_type: str, detail_level: str,
                                        budget: int, total_tokens: int, layer_stats: str,
                                        truncated_layers: str, context_sufficient: bool) -> None:
        await self.execute(
            """INSERT INTO compilation_metrics
               (task_id, skill_type, detail_level, budget, total_tokens,
                layer_stats, truncated_layers, context_sufficient)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, skill_type, detail_level, budget, total_tokens,
             layer_stats, truncated_layers, 1 if context_sufficient else 0),
        )

    async def query_compilation_metrics(self, limit: int = 100) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM compilation_metrics ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    async def get_top_archives(self, n: int = 10) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM agent_archives ORDER BY score DESC LIMIT ?",
            (n,),
        )

    async def query_recovery_timeline(self) -> List[Dict]:
        return await self.fetchall(
            """SELECT * FROM task_recovery_events
               ORDER BY created_at DESC LIMIT 200""",
        )
