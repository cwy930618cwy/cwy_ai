"""
存储层模块

SQLiteKVStore 完全替代 RedisClient，实现相同接口。
为保持向后兼容，RedisClient 作为 SQLiteKVStore 的别名导出。
"""
from .sqlite_kv import SQLiteKVStore
from .sqlite_store import SQLiteStore

# 向后兼容别名：所有模块 `from agentflow.storage import RedisClient` 无需修改
RedisClient = SQLiteKVStore

__all__ = ["SQLiteKVStore", "SQLiteStore", "RedisClient"]
