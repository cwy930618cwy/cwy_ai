import logging
import time
from typing import List

from agentflow.storage import RedisClient

# Lua: atomic acquire (SET NX EX)
_ACQUIRE_LUA = """
local key = KEYS[1]
local value = ARGV[1]
local ttl = tonumber(ARGV[2])
local ok = redis.call('SET', key, value, 'NX', 'EX', ttl)
if ok then return 1 end
return 0
"""

# Lua: atomic release (validate owner then DEL)
_RELEASE_LUA = """
local key = KEYS[1]
local value = ARGV[1]
local current = redis.call('GET', key)
if current == value then
    redis.call('DEL', key)
    return 1
end
return 0
"""

# Lua: atomic renew (validate owner then EXPIRE)
_RENEW_LUA = """
local key = KEYS[1]
local value = ARGV[1]
local ttl = tonumber(ARGV[2])
local current = redis.call('GET', key)
if current == value then
    redis.call('EXPIRE', key, ttl)
    return 1
end
return 0
"""

# Lua: move task queue pending→running
_MOVE_QUEUE_LUA = """
local pending_queue = KEYS[1]
local running_queue = KEYS[2]
local task_id = ARGV[1]
local timestamp = tonumber(ARGV[2])
local moved = redis.call('ZREM', pending_queue, task_id)
if moved == 0 then
    return -1
end
redis.call('ZADD', running_queue, timestamp, task_id)
return 1
"""

# Lua: force move from any queue to running
_FORCE_MOVE_LUA = """
local running_queue = KEYS[1]
local task_id = ARGV[1]
local timestamp = tonumber(ARGV[2])
for i = 3, #ARGV do
    redis.call('ZREM', ARGV[i], task_id)
end
redis.call('ZADD', running_queue, timestamp, task_id)
return 1
"""


class LockManager:
    def __init__(self, redis: RedisClient, logger: logging.Logger):
        self._redis = redis
        self._logger = logger
        self._acquire_sha = ""
        self._release_sha = ""
        self._renew_sha = ""

    @classmethod
    async def create(cls, redis: RedisClient, logger: logging.Logger) -> "LockManager":
        mgr = cls(redis, logger)
        mgr._acquire_sha = await redis.script_load(_ACQUIRE_LUA)
        mgr._release_sha = await redis.script_load(_RELEASE_LUA)
        mgr._renew_sha = await redis.script_load(_RENEW_LUA)
        logger.info("分布式锁管理器初始化成功")
        return mgr

    async def acquire(self, key: str, owner: str, ttl_secs: int) -> bool:
        result = await self._redis.evalsha(self._acquire_sha, [key], owner, ttl_secs)
        acquired = int(result) == 1
        if acquired:
            self._logger.debug(f"获取锁成功 key={key} owner={owner}")
        return acquired

    async def release(self, key: str, owner: str) -> bool:
        result = await self._redis.evalsha(self._release_sha, [key], owner)
        released = int(result) == 1
        if released:
            self._logger.debug(f"释放锁成功 key={key} owner={owner}")
        return released

    async def renew(self, key: str, owner: str, ttl_secs: int) -> bool:
        result = await self._redis.evalsha(self._renew_sha, [key], owner, ttl_secs)
        return int(result) == 1

    async def claim_task(self, lock_key: str, pending_queue: str, running_queue: str,
                         agent_id: str, task_id: str, ttl_secs: int) -> int:
        """Atomically claim task. Returns 1=success, 0=already claimed, -1=not available."""
        locked = await self._redis.setnx(lock_key, agent_id, ex=ttl_secs)
        if not locked:
            self._logger.debug(f"任务已被认领 task={task_id}")
            return 0
        ts = int(time.time())
        result = await self._redis.eval(
            _MOVE_QUEUE_LUA,
            [pending_queue, running_queue],
            task_id, ts,
        )
        val = int(result)
        if val == -1:
            await self._redis.delete(lock_key)
            self._logger.debug(f"任务不可用 task={task_id}")
            return -1
        self._logger.info(f"任务认领成功 task={task_id} agent={agent_id}")
        return 1

    async def force_claim_task(self, lock_key: str, running_queue: str,
                                agent_id: str, task_id: str,
                                ttl_secs: int, *all_queue_keys: str) -> int:
        """Force claim task from any queue."""
        await self._redis.set(lock_key, agent_id, ex=ttl_secs)
        ts = int(time.time())
        args: List = [task_id, ts] + list(all_queue_keys)
        result = await self._redis.eval(_FORCE_MOVE_LUA, [running_queue], *args)
        self._logger.info(f"任务已强制接管 task={task_id} new_agent={agent_id}")
        return int(result)

    async def update_heartbeat(self, agent_id: str, timeout_secs: int) -> None:
        key = self._redis.key("agent", agent_id, "heartbeat")
        await self._redis.set(key, str(int(time.time())), ex=timeout_secs)

    async def check_heartbeat(self, agent_id: str) -> bool:
        key = self._redis.key("agent", agent_id, "heartbeat")
        val = await self._redis.get(key)
        return val is not None
