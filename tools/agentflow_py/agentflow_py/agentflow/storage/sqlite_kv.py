"""
SQLiteKVStore - 用 SQLite 完全替代 RedisClient 的 KV 存储适配器

实现与 RedisClient 完全相同的接口，让所有模块无感知地切换到 SQLite。

数据结构映射：
  - String/KV  → kv_store (key, value, expires_at)
  - Hash       → hash_store (key, field, value)
  - List       → list_store (key, idx, value)  -- idx 用浮点数保证顺序
  - Set        → set_store (key, member)
  - ZSet       → zset_store (key, member, score)
  - Stream     → stream_store (key, entry_id, fields_json)
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

from agentflow.config import SQLiteConfig


class SQLiteKVStore:
    """
    SQLite KV 存储 - 完全兼容 RedisClient 接口。
    所有模块可以直接将 RedisClient 替换为 SQLiteKVStore，无需修改业务代码。
    """

    def __init__(self, db_path: str, logger: logging.Logger,
                 key_prefix: str = "af", namespace: str = ""):
        self._db_path = db_path
        self._logger = logger
        self._key_prefix = key_prefix
        self._namespace = namespace
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()  # 写操作串行化（WAL 模式下读可并发）

    # ── 工厂方法 ──────────────────────────────────────────────────────────────

    @classmethod
    async def create(cls, cfg: SQLiteConfig, db_path: str,
                     logger: logging.Logger) -> "SQLiteKVStore":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        store = cls(db_path, logger, key_prefix="af")
        store._db = await aiosqlite.connect(db_path, check_same_thread=False)
        store._db.row_factory = aiosqlite.Row
        await store._db.execute(f"PRAGMA journal_mode={cfg.journal_mode}")
        await store._db.execute(f"PRAGMA busy_timeout={cfg.busy_timeout}")
        await store._db.execute("PRAGMA foreign_keys=OFF")
        await store._db.execute("PRAGMA synchronous=NORMAL")
        await store._migrate()
        logger.info(f"SQLiteKVStore 初始化成功 path={db_path}")
        return store

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # ── 命名空间支持（兼容 RedisClient.with_namespace） ───────────────────────

    def with_namespace(self, namespace: str) -> "SQLiteKVStore":
        """返回绑定了指定命名空间的视图（共享底层连接）。"""
        if not namespace:
            return self
        ns_store = SQLiteKVStore(self._db_path, self._logger,
                                  self._key_prefix, namespace)
        ns_store._db = self._db  # 共享连接
        ns_store._lock = self._lock  # 共享锁
        return ns_store

    # ── Key 生成（与 RedisClient.key() 完全一致） ─────────────────────────────

    def key(self, *parts: str, namespace: str = "") -> str:
        effective_ns = namespace or self._namespace
        if effective_ns:
            return self._key_prefix + ":" + effective_ns + ":" + ":".join(parts)
        return self._key_prefix + ":" + ":".join(parts)

    # ── 数据库迁移 ────────────────────────────────────────────────────────────

    async def _migrate(self) -> None:
        ddl = [
            # KV / String
            """CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL DEFAULT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_kv_expires ON kv_store(expires_at)",
            # Hash
            """CREATE TABLE IF NOT EXISTS hash_store (
                key TEXT NOT NULL,
                field TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (key, field)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_hash_key ON hash_store(key)",
            # List（用 idx 浮点数维护顺序，lpush 用负数，rpush 用正数）
            """CREATE TABLE IF NOT EXISTS list_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                idx REAL NOT NULL,
                value TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_list_key_idx ON list_store(key, idx)",
            # Set
            """CREATE TABLE IF NOT EXISTS set_store (
                key TEXT NOT NULL,
                member TEXT NOT NULL,
                PRIMARY KEY (key, member)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_set_key ON set_store(key)",
            # ZSet（Sorted Set）
            """CREATE TABLE IF NOT EXISTS zset_store (
                key TEXT NOT NULL,
                member TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (key, member)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_zset_key_score ON zset_store(key, score)",
            # Stream
            """CREATE TABLE IF NOT EXISTS stream_store (
                key TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                PRIMARY KEY (key, entry_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_stream_key ON stream_store(key, entry_id)",
            # Lua 脚本缓存（用于 script_load / evalsha）
            """CREATE TABLE IF NOT EXISTS lua_scripts (
                sha TEXT PRIMARY KEY,
                script TEXT NOT NULL
            )""",
        ]
        async with self._db.cursor() as cur:
            for sql in ddl:
                await cur.execute(sql)
        await self._db.commit()

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    async def _cleanup_expired(self, key: str) -> None:
        """清理已过期的 KV 条目。"""
        now = time.time()
        await self._db.execute(
            "DELETE FROM kv_store WHERE key=? AND expires_at IS NOT NULL AND expires_at <= ?",
            (key, now),
        )

    async def _list_max_idx(self, key: str) -> float:
        """获取 list 的最大 idx（用于 rpush）。"""
        async with self._db.execute(
            "SELECT MAX(idx) FROM list_store WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            v = row[0] if row else None
            return float(v) if v is not None else 0.0

    async def _list_min_idx(self, key: str) -> float:
        """获取 list 的最小 idx（用于 lpush）。"""
        async with self._db.execute(
            "SELECT MIN(idx) FROM list_store WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            v = row[0] if row else None
            return float(v) if v is not None else 0.0

    # ── 健康检查 ──────────────────────────────────────────────────────────────

    async def health_check(self) -> None:
        await self._db.execute("SELECT 1")

    async def memory_usage(self) -> int:
        """返回各表总行数之和（模拟 Redis dbsize）。"""
        total = 0
        for tbl in ("kv_store", "hash_store", "list_store", "set_store", "zset_store"):
            async with self._db.execute(f"SELECT COUNT(*) FROM {tbl}") as cur:
                row = await cur.fetchone()
                total += row[0] if row else 0
        return total

    # ── String / KV ──────────────────────────────────────────────────────────

    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        expires_at = time.time() + ex if ex else None
        async with self._lock:
            await self._db.execute(
                "INSERT OR REPLACE INTO kv_store (key, value, expires_at) VALUES (?, ?, ?)",
                (key, str(value), expires_at),
            )
            await self._db.commit()

    async def get(self, key: str) -> Optional[str]:
        await self._cleanup_expired(key)
        async with self._db.execute(
            "SELECT value FROM kv_store WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def setnx(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """SET if Not eXists，返回是否成功设置。"""
        await self._cleanup_expired(key)
        expires_at = time.time() + ex if ex else None
        async with self._lock:
            async with self._db.execute(
                "SELECT 1 FROM kv_store WHERE key=?", (key,)
            ) as cur:
                exists = await cur.fetchone()
            if exists:
                return False
            await self._db.execute(
                "INSERT INTO kv_store (key, value, expires_at) VALUES (?, ?, ?)",
                (key, str(value), expires_at),
            )
            await self._db.commit()
            return True

    async def delete(self, *keys: str) -> int:
        count = 0
        async with self._lock:
            for key in keys:
                for tbl in ("kv_store", "hash_store", "list_store",
                            "set_store", "zset_store", "stream_store"):
                    cur = await self._db.execute(
                        f"DELETE FROM {tbl} WHERE key=?", (key,)
                    )
                    count += cur.rowcount
            await self._db.commit()
        return count

    async def exists(self, *keys: str) -> int:
        count = 0
        for key in keys:
            await self._cleanup_expired(key)
            found = False
            for tbl in ("kv_store", "hash_store", "list_store",
                        "set_store", "zset_store", "stream_store"):
                async with self._db.execute(
                    f"SELECT 1 FROM {tbl} WHERE key=? LIMIT 1", (key,)
                ) as cur:
                    if await cur.fetchone():
                        found = True
                        break
            if found:
                count += 1
        return count

    async def expire(self, key: str, seconds: int) -> bool:
        expires_at = time.time() + seconds
        async with self._lock:
            cur = await self._db.execute(
                "UPDATE kv_store SET expires_at=? WHERE key=?", (expires_at, key)
            )
            await self._db.commit()
            return cur.rowcount > 0

    # ── Hash ─────────────────────────────────────────────────────────────────

    async def hset(self, key: str, mapping: dict) -> None:
        if not mapping:
            return
        async with self._lock:
            for field, value in mapping.items():
                await self._db.execute(
                    "INSERT OR REPLACE INTO hash_store (key, field, value) VALUES (?, ?, ?)",
                    (key, str(field), str(value)),
                )
            await self._db.commit()

    async def hgetall(self, key: str) -> dict:
        async with self._db.execute(
            "SELECT field, value FROM hash_store WHERE key=?", (key,)
        ) as cur:
            rows = await cur.fetchall()
            return {row[0]: row[1] for row in rows}

    async def hget(self, key: str, field: str) -> Optional[str]:
        async with self._db.execute(
            "SELECT value FROM hash_store WHERE key=? AND field=?", (key, field)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def hdel(self, key: str, *fields: str) -> int:
        count = 0
        async with self._lock:
            for field in fields:
                cur = await self._db.execute(
                    "DELETE FROM hash_store WHERE key=? AND field=?", (key, field)
                )
                count += cur.rowcount
            await self._db.commit()
        return count

    async def hincr_by(self, key: str, field: str, amount: int = 1) -> int:
        async with self._lock:
            async with self._db.execute(
                "SELECT value FROM hash_store WHERE key=? AND field=?", (key, field)
            ) as cur:
                row = await cur.fetchone()
            current = int(row[0]) if row else 0
            new_val = current + amount
            await self._db.execute(
                "INSERT OR REPLACE INTO hash_store (key, field, value) VALUES (?, ?, ?)",
                (key, field, str(new_val)),
            )
            await self._db.commit()
            return new_val

    # ── List ─────────────────────────────────────────────────────────────────

    async def rpush(self, key: str, *values: Any) -> int:
        async with self._lock:
            max_idx = await self._list_max_idx(key)
            for i, v in enumerate(values):
                await self._db.execute(
                    "INSERT INTO list_store (key, idx, value) VALUES (?, ?, ?)",
                    (key, max_idx + i + 1.0, str(v)),
                )
            await self._db.commit()
        return await self.llen(key)

    async def lpush(self, key: str, *values: Any) -> int:
        async with self._lock:
            min_idx = await self._list_min_idx(key)
            # lpush 是逆序插入（最后一个 value 在最前面）
            for i, v in enumerate(reversed(values)):
                await self._db.execute(
                    "INSERT INTO list_store (key, idx, value) VALUES (?, ?, ?)",
                    (key, min_idx - len(values) + i, str(v)),
                )
            await self._db.commit()
        return await self.llen(key)

    async def lrange(self, key: str, start: int, stop: int) -> List[str]:
        async with self._db.execute(
            "SELECT value FROM list_store WHERE key=? ORDER BY idx ASC", (key,)
        ) as cur:
            rows = await cur.fetchall()
        items = [row[0] for row in rows]
        length = len(items)
        if stop == -1:
            stop = length - 1
        if stop < 0:
            stop = length + stop
        if start < 0:
            start = max(0, length + start)
        return items[start:stop + 1]

    async def llen(self, key: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM list_store WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def lrem(self, key: str, count: int, value: Any) -> int:
        """删除 list 中值等于 value 的元素（count>0 从头删，count<0 从尾删，count=0 全删）。"""
        async with self._lock:
            if count == 0:
                cur = await self._db.execute(
                    "DELETE FROM list_store WHERE key=? AND value=?", (key, str(value))
                )
                await self._db.commit()
                return cur.rowcount
            # 获取所有匹配的 id
            order = "ASC" if count > 0 else "DESC"
            limit = abs(count)
            async with self._db.execute(
                f"SELECT id FROM list_store WHERE key=? AND value=? ORDER BY idx {order} LIMIT ?",
                (key, str(value), limit),
            ) as cur:
                ids = [row[0] for row in await cur.fetchall()]
            if not ids:
                return 0
            placeholders = ",".join("?" * len(ids))
            cur = await self._db.execute(
                f"DELETE FROM list_store WHERE id IN ({placeholders})", ids
            )
            await self._db.commit()
            return cur.rowcount

    # ── Set ──────────────────────────────────────────────────────────────────

    async def sadd(self, key: str, *members: Any) -> int:
        count = 0
        async with self._lock:
            for m in members:
                try:
                    await self._db.execute(
                        "INSERT OR IGNORE INTO set_store (key, member) VALUES (?, ?)",
                        (key, str(m)),
                    )
                    count += 1
                except Exception:
                    pass
            await self._db.commit()
        return count

    async def smembers(self, key: str) -> set:
        async with self._db.execute(
            "SELECT member FROM set_store WHERE key=?", (key,)
        ) as cur:
            rows = await cur.fetchall()
            return {row[0] for row in rows}

    async def srem(self, key: str, *members: Any) -> int:
        count = 0
        async with self._lock:
            for m in members:
                cur = await self._db.execute(
                    "DELETE FROM set_store WHERE key=? AND member=?", (key, str(m))
                )
                count += cur.rowcount
            await self._db.commit()
        return count

    async def sismember(self, key: str, member: Any) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM set_store WHERE key=? AND member=?", (key, str(member))
        ) as cur:
            return await cur.fetchone() is not None

    # ── Sorted Set (ZSet) ────────────────────────────────────────────────────

    async def zadd(self, key: str, mapping: dict) -> int:
        count = 0
        async with self._lock:
            for member, score in mapping.items():
                await self._db.execute(
                    "INSERT OR REPLACE INTO zset_store (key, member, score) VALUES (?, ?, ?)",
                    (key, str(member), float(score)),
                )
                count += 1
            await self._db.commit()
        return count

    async def zrangebyscore(self, key: str, min_score: Any, max_score: Any,
                             withscores: bool = False, offset: int = 0,
                             count: int = -1) -> List:
        min_s = float("-inf") if min_score in ("-inf", float("-inf")) else float(min_score)
        max_s = float("inf") if max_score in ("+inf", float("inf")) else float(max_score)
        sql = ("SELECT member, score FROM zset_store "
               "WHERE key=? AND score>=? AND score<=? ORDER BY score ASC")
        async with self._db.execute(sql, (key, min_s, max_s)) as cur:
            rows = await cur.fetchall()
        items = list(rows)
        if offset:
            items = items[offset:]
        if count > 0:
            items = items[:count]
        if withscores:
            return [(row[0], row[1]) for row in items]
        return [row[0] for row in items]

    async def zrevrange_withscores(self, key: str, start: int = 0,
                                    stop: int = -1) -> List[Tuple[str, float]]:
        async with self._db.execute(
            "SELECT member, score FROM zset_store WHERE key=? ORDER BY score DESC",
            (key,),
        ) as cur:
            rows = await cur.fetchall()
        items = list(rows)
        length = len(items)
        if stop == -1:
            stop = length - 1
        return [(row[0], row[1]) for row in items[start:stop + 1]]

    async def zrange_withscores(self, key: str, start: int = 0,
                                 stop: int = -1) -> List[Tuple[str, float]]:
        async with self._db.execute(
            "SELECT member, score FROM zset_store WHERE key=? ORDER BY score ASC",
            (key,),
        ) as cur:
            rows = await cur.fetchall()
        items = list(rows)
        length = len(items)
        if stop == -1:
            stop = length - 1
        return [(row[0], row[1]) for row in items[start:stop + 1]]

    async def zrange(self, key: str, start: int = 0, stop: int = -1) -> List[str]:
        pairs = await self.zrange_withscores(key, start, stop)
        return [p[0] for p in pairs]

    async def zrem(self, key: str, *members: Any) -> int:
        count = 0
        async with self._lock:
            for m in members:
                cur = await self._db.execute(
                    "DELETE FROM zset_store WHERE key=? AND member=?", (key, str(m))
                )
                count += cur.rowcount
            await self._db.commit()
        return count

    async def zcard(self, key: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM zset_store WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def zscore(self, key: str, member: str) -> Optional[float]:
        async with self._db.execute(
            "SELECT score FROM zset_store WHERE key=? AND member=?", (key, member)
        ) as cur:
            row = await cur.fetchone()
            return float(row[0]) if row else None

    async def zincrby(self, key: str, amount: float, member: str) -> float:
        async with self._lock:
            async with self._db.execute(
                "SELECT score FROM zset_store WHERE key=? AND member=?", (key, member)
            ) as cur:
                row = await cur.fetchone()
            current = float(row[0]) if row else 0.0
            new_score = current + amount
            await self._db.execute(
                "INSERT OR REPLACE INTO zset_store (key, member, score) VALUES (?, ?, ?)",
                (key, member, new_score),
            )
            await self._db.commit()
            return new_score

    # ── Scan ─────────────────────────────────────────────────────────────────

    async def scan_iter(self, match: str = "*", count: int = 100) -> List[str]:
        """扫描所有匹配的 key（支持 * 通配符）。"""
        # 将 Redis glob 模式转换为 SQL LIKE 模式
        like_pattern = match.replace("*", "%").replace("?", "_")
        keys = set()
        for tbl in ("kv_store", "hash_store", "list_store",
                    "set_store", "zset_store", "stream_store"):
            async with self._db.execute(
                f"SELECT DISTINCT key FROM {tbl} WHERE key LIKE ?", (like_pattern,)
            ) as cur:
                rows = await cur.fetchall()
                for row in rows:
                    keys.add(row[0])
        return list(keys)

    # ── Stream ────────────────────────────────────────────────────────────────

    async def xadd(self, key: str, fields: dict,
                   maxlen: Optional[int] = None) -> str:
        entry_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        fields_json = json.dumps(fields, ensure_ascii=False)
        async with self._lock:
            await self._db.execute(
                "INSERT INTO stream_store (key, entry_id, fields_json) VALUES (?, ?, ?)",
                (key, entry_id, fields_json),
            )
            if maxlen:
                # 保留最新的 maxlen 条
                await self._db.execute(
                    """DELETE FROM stream_store WHERE key=? AND entry_id NOT IN (
                        SELECT entry_id FROM stream_store WHERE key=?
                        ORDER BY entry_id DESC LIMIT ?
                    )""",
                    (key, key, maxlen),
                )
            await self._db.commit()
        return entry_id

    async def xrange(self, key: str, min_id: str = "-", max_id: str = "+",
                     count: Optional[int] = None) -> List[dict]:
        sql = "SELECT entry_id, fields_json FROM stream_store WHERE key=?"
        params: list = [key]
        if min_id != "-":
            sql += " AND entry_id >= ?"
            params.append(min_id)
        if max_id != "+":
            sql += " AND entry_id <= ?"
            params.append(max_id)
        sql += " ORDER BY entry_id ASC"
        if count:
            sql += f" LIMIT {count}"
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [{"id": row[0], "fields": json.loads(row[1])} for row in rows]

    async def xrevrange(self, key: str, max_id: str = "+", min_id: str = "-",
                        count: Optional[int] = None) -> List[dict]:
        sql = "SELECT entry_id, fields_json FROM stream_store WHERE key=?"
        params: list = [key]
        if min_id != "-":
            sql += " AND entry_id >= ?"
            params.append(min_id)
        if max_id != "+":
            sql += " AND entry_id <= ?"
            params.append(max_id)
        sql += " ORDER BY entry_id DESC"
        if count:
            sql += f" LIMIT {count}"
        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [{"id": row[0], "fields": json.loads(row[1])} for row in rows]

    async def xlen(self, key: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM stream_store WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def xdel(self, key: str, *ids: str) -> int:
        count = 0
        async with self._lock:
            for entry_id in ids:
                cur = await self._db.execute(
                    "DELETE FROM stream_store WHERE key=? AND entry_id=?",
                    (key, entry_id),
                )
                count += cur.rowcount
            await self._db.commit()
        return count

    # ── Lua 脚本（模拟 Redis Lua eval） ──────────────────────────────────────

    async def script_load(self, script: str) -> str:
        """存储脚本并返回 SHA（用 UUID 模拟）。"""
        import hashlib
        sha = hashlib.sha1(script.encode()).hexdigest()
        async with self._lock:
            await self._db.execute(
                "INSERT OR REPLACE INTO lua_scripts (sha, script) VALUES (?, ?)",
                (sha, script),
            )
            await self._db.commit()
        return sha

    async def evalsha(self, sha: str, keys: List[str], *args: Any) -> Any:
        """执行已加载的脚本（通过 SHA 查找）。"""
        async with self._db.execute(
            "SELECT script FROM lua_scripts WHERE sha=?", (sha,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            raise ValueError(f"NOSCRIPT: sha={sha}")
        return await self.eval(row[0], keys, *args)

    async def eval(self, script: str, keys: List[str], *args: Any) -> Any:
        """
        模拟 Redis Lua eval。
        支持 LockManager 中使用的三种脚本：acquire / release / renew，
        以及 TaskStore 中使用的 move_queue / force_move 脚本。
        """
        # ── 锁：acquire (SET NX EX) ──────────────────────────────────────────
        if "SET" in script and "NX" in script and "EX" in script and "EXPIRE" not in script:
            key, owner, ttl = keys[0], str(args[0]), int(args[1])
            acquired = await self.setnx(key, owner, ex=ttl)
            return 1 if acquired else 0

        # ── 锁：release (GET + DEL if owner matches) ─────────────────────────
        if "GET" in script and "DEL" in script and "EXPIRE" not in script and "ZADD" not in script:
            key, owner = keys[0], str(args[0])
            current = await self.get(key)
            if current == owner:
                await self.delete(key)
                return 1
            return 0

        # ── 锁：renew (GET + EXPIRE if owner matches) ────────────────────────
        if "EXPIRE" in script and "GET" in script and "ZADD" not in script:
            key, owner, ttl = keys[0], str(args[0]), int(args[1])
            current = await self.get(key)
            if current == owner:
                await self.expire(key, ttl)
                return 1
            return 0

        # ── 任务队列：move pending→running ───────────────────────────────────
        if "ZREM" in script and "ZADD" in script and len(keys) == 2:
            pending_queue, running_queue = keys[0], keys[1]
            task_id, timestamp = str(args[0]), float(args[1])
            removed = await self.zrem(pending_queue, task_id)
            if removed == 0:
                return -1
            await self.zadd(running_queue, {task_id: timestamp})
            return 1

        # ── 任务队列：force move from any queue to running ───────────────────
        if "ZREM" in script and "ZADD" in script and len(keys) == 1:
            running_queue = keys[0]
            task_id, timestamp = str(args[0]), float(args[1])
            # args[2:] 是所有队列 key
            for q_key in args[2:]:
                await self.zrem(str(q_key), task_id)
            await self.zadd(running_queue, {task_id: timestamp})
            return 1

        # ── 未知脚本：记录警告并返回 0 ───────────────────────────────────────
        self._logger.warning(f"SQLiteKVStore.eval: 未知脚本，返回 0\n{script[:200]}")
        return 0

    # ── Pipeline（简化版：顺序执行，不支持事务回滚） ──────────────────────────

    def pipeline(self):
        """返回一个简单的 Pipeline 对象（顺序执行）。"""
        return _SQLitePipeline(self)

    # ── Raw 属性（兼容直接访问 .raw 的代码） ─────────────────────────────────

    @property
    def raw(self):
        """返回自身（兼容 RedisClient.raw 属性）。"""
        return self


class _SQLitePipeline:
    """
    简化版 Pipeline，收集命令后顺序执行。
    兼容 RedisClient.pipeline() 的使用方式。
    """

    def __init__(self, store: SQLiteKVStore):
        self._store = store
        self._cmds: List[Tuple[str, tuple]] = []

    def __getattr__(self, name: str):
        """动态代理所有方法调用，收集到命令队列。"""
        async def _method(*args, **kwargs):
            self._cmds.append((name, args, kwargs))
            return self  # 支持链式调用

        return _method

    async def execute(self):
        """顺序执行所有收集的命令，返回结果列表。"""
        results = []
        for name, args, kwargs in self._cmds:
            method = getattr(self._store, name)
            result = await method(*args, **kwargs)
            results.append(result)
        self._cmds.clear()
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.execute()
