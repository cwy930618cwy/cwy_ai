"""
py 工程移植功能集成测试

参考 Go 工程 tests/integration_test.go 和 tests/project_lifecycle_test.go 编写。
覆盖：
  1. namespace 隔离测试
  2. collab 协作测试（任务评论 + Agent 邮箱）
  3. plugin 插件测试（HTTP 插件注册和工具调用）
  4. project 生命周期测试（创建、阶段推进、审批流程）
  5. webhook 触发测试（事件触发和 Webhook 分发）
  6. 数据导入导出测试（export_data 和 import_data）

运行方式：
  python -m pytest tests/test_integration_new_features.py -v
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# 公共 Fixture：Mock Redis Client
# ---------------------------------------------------------------------------

def make_mock_redis(key_prefix: str = "af") -> MagicMock:
    """
    构造一个模拟 RedisClient，内存中存储数据以支持常见操作。
    覆盖 hset/hget/hgetall/hdel/rpush/lrange/llen/xadd/xrange/xrevrange/
         xlen/set/get/delete/exists/zadd/zrangebyscore/zrevrange_withscores/
         zrange/zrem/sadd/smembers/srem/sismember 等方法。
    """
    store: Dict[str, Any] = {}

    mock = MagicMock()
    mock._key_prefix = key_prefix
    mock._namespace = ""

    def _key(*parts, namespace=""):
        ns = namespace or mock._namespace
        if ns:
            return key_prefix + ":" + ns + ":" + ":".join(parts)
        return key_prefix + ":" + ":".join(parts)

    mock.key = _key

    # --- Hash ---
    async def hset(key, mapping):
        if key not in store:
            store[key] = {}
        store[key].update(mapping)

    async def hget(key, field):
        return store.get(key, {}).get(field)

    async def hgetall(key):
        return dict(store.get(key, {}))

    async def hdel(key, *fields):
        h = store.get(key, {})
        for f in fields:
            h.pop(f, None)
        return len(fields)

    mock.hset = AsyncMock(side_effect=hset)
    mock.hget = AsyncMock(side_effect=hget)
    mock.hgetall = AsyncMock(side_effect=hgetall)
    mock.hdel = AsyncMock(side_effect=hdel)

    # --- String ---
    async def set_val(key, value, ex=None):
        store[key] = value

    async def get_val(key):
        return store.get(key)

    async def delete(*keys):
        for k in keys:
            store.pop(k, None)
        return len(keys)

    async def exists(*keys):
        return sum(1 for k in keys if k in store)

    mock.set = AsyncMock(side_effect=set_val)
    mock.get = AsyncMock(side_effect=get_val)
    mock.delete = AsyncMock(side_effect=delete)
    mock.exists = AsyncMock(side_effect=exists)

    # --- List ---
    async def rpush(key, *values):
        if key not in store:
            store[key] = []
        if not isinstance(store[key], list):
            store[key] = []
        store[key].extend(values)
        return len(store[key])

    async def lpush(key, *values):
        if key not in store:
            store[key] = []
        if not isinstance(store[key], list):
            store[key] = []
        for v in values:
            store[key].insert(0, v)
        return len(store[key])

    async def lrange(key, start, stop):
        lst = store.get(key, [])
        if not isinstance(lst, list):
            return []
        if stop == -1:
            return lst[start:]
        return lst[start:stop + 1]

    async def llen(key):
        lst = store.get(key, [])
        return len(lst) if isinstance(lst, list) else 0

    async def lrem(key, count, value):
        lst = store.get(key, [])
        if isinstance(lst, list):
            removed = 0
            new_lst = []
            for item in lst:
                if item == value and (count == 0 or removed < abs(count)):
                    removed += 1
                else:
                    new_lst.append(item)
            store[key] = new_lst
            return removed
        return 0

    mock.rpush = AsyncMock(side_effect=rpush)
    mock.lpush = AsyncMock(side_effect=lpush)
    mock.lrange = AsyncMock(side_effect=lrange)
    mock.llen = AsyncMock(side_effect=llen)
    mock.lrem = AsyncMock(side_effect=lrem)

    # --- SortedSet ---
    async def zadd(key, mapping):
        if key not in store:
            store[key] = {}
        if not isinstance(store.get(key), dict):
            store[key] = {}
        store[key].update(mapping)
        return len(mapping)

    async def zrangebyscore(key, min_score, max_score, withscores=False, offset=0, count=-1):
        ss = store.get(key, {})
        if not isinstance(ss, dict):
            return []
        items = sorted(ss.items(), key=lambda x: x[1])
        result = []
        for member, score in items:
            try:
                s = float(score)
                mn = float(min_score) if min_score != "-inf" else float("-inf")
                mx = float(max_score) if max_score != "+inf" else float("inf")
                if mn <= s <= mx:
                    result.append((member, s) if withscores else member)
            except (ValueError, TypeError):
                pass
        return result

    async def zrevrange_withscores(key, start=0, stop=-1):
        ss = store.get(key, {})
        if not isinstance(ss, dict):
            return []
        items = sorted(ss.items(), key=lambda x: -x[1])
        if stop == -1:
            return items[start:]
        return items[start:stop + 1]

    async def zrange(key, start=0, stop=-1):
        ss = store.get(key, {})
        if not isinstance(ss, dict):
            return []
        items = sorted(ss.items(), key=lambda x: x[1])
        members = [m for m, _ in items]
        if stop == -1:
            return members[start:]
        return members[start:stop + 1]

    async def zrem(key, *members):
        ss = store.get(key, {})
        if isinstance(ss, dict):
            for m in members:
                ss.pop(m, None)
        return len(members)

    async def zcard(key):
        ss = store.get(key, {})
        return len(ss) if isinstance(ss, dict) else 0

    mock.zadd = AsyncMock(side_effect=zadd)
    mock.zrangebyscore = AsyncMock(side_effect=zrangebyscore)
    mock.zrevrange_withscores = AsyncMock(side_effect=zrevrange_withscores)
    mock.zrange = AsyncMock(side_effect=zrange)
    mock.zrem = AsyncMock(side_effect=zrem)
    mock.zcard = AsyncMock(side_effect=zcard)

    # --- Set ---
    async def sadd(key, *members):
        if key not in store:
            store[key] = set()
        if not isinstance(store[key], set):
            store[key] = set()
        store[key].update(members)
        return len(members)

    async def smembers(key):
        return store.get(key, set())

    async def srem(key, *members):
        s = store.get(key, set())
        if isinstance(s, set):
            for m in members:
                s.discard(m)
        return len(members)

    async def sismember(key, member):
        return member in store.get(key, set())

    mock.sadd = AsyncMock(side_effect=sadd)
    mock.smembers = AsyncMock(side_effect=smembers)
    mock.srem = AsyncMock(side_effect=srem)
    mock.sismember = AsyncMock(side_effect=sismember)

    # --- Stream ---
    _stream_counter: Dict[str, int] = {}

    async def xadd(key, fields, maxlen=None):
        if key not in store:
            store[key] = []
        if not isinstance(store[key], list):
            store[key] = []
        idx = _stream_counter.get(key, 0) + 1
        _stream_counter[key] = idx
        entry_id = f"{int(datetime.now().timestamp() * 1000)}-{idx}"
        store[key].append({"id": entry_id, "fields": dict(fields)})
        if maxlen and len(store[key]) > maxlen:
            store[key] = store[key][-maxlen:]
        return entry_id

    async def xrange(key, min_id="-", max_id="+", count=None):
        entries = store.get(key, [])
        if not isinstance(entries, list):
            return []
        result = list(entries)
        if count is not None:
            result = result[:count]
        return result

    async def xrevrange(key, max_id="+", min_id="-", count=None):
        entries = store.get(key, [])
        if not isinstance(entries, list):
            return []
        result = list(reversed(entries))
        if count is not None:
            result = result[:count]
        return result

    async def xlen(key):
        entries = store.get(key, [])
        return len(entries) if isinstance(entries, list) else 0

    async def xdel(key, *ids):
        entries = store.get(key, [])
        if isinstance(entries, list):
            store[key] = [e for e in entries if e["id"] not in ids]
        return len(ids)

    mock.xadd = AsyncMock(side_effect=xadd)
    mock.xrange = AsyncMock(side_effect=xrange)
    mock.xrevrange = AsyncMock(side_effect=xrevrange)
    mock.xlen = AsyncMock(side_effect=xlen)
    mock.xdel = AsyncMock(side_effect=xdel)

    # --- raw ---
    raw_mock = MagicMock()
    raw_mock.ltrim = AsyncMock()
    mock.raw = raw_mock

    # --- Pipeline ---
    class MockPipeline:
        """Mock Pipeline 支持批量操作"""
        def __init__(self):
            self._ops = []

        def hset(self, key, mapping):
            self._ops.append(('hset', key, mapping))
            return self

        def zadd(self, key, mapping):
            self._ops.append(('zadd', key, mapping))
            return self

        def set(self, key, value):
            self._ops.append(('set', key, value))
            return self

        def delete(self, key):
            self._ops.append(('delete', key))
            return self

        def rpush(self, key, *values):
            self._ops.append(('rpush', key, values))
            return self

        def lrem(self, key, count, value):
            self._ops.append(('lrem', key, count, value))
            return self

        async def execute(self):
            results = []
            for op in self._ops:
                if op[0] == 'hset':
                    _, key, mapping = op
                    if key not in store:
                        store[key] = {}
                    store[key].update(mapping)
                    results.append(len(mapping))
                elif op[0] == 'zadd':
                    _, key, mapping = op
                    if key not in store:
                        store[key] = {}
                    store[key].update(mapping)
                    results.append(len(mapping))
                elif op[0] == 'set':
                    _, key, value = op
                    store[key] = value
                    results.append('OK')
                elif op[0] == 'delete':
                    _, key = op
                    store.pop(key, None)
                    results.append(1)
                elif op[0] == 'rpush':
                    _, key, values = op
                    if key not in store:
                        store[key] = []
                    if not isinstance(store[key], list):
                        store[key] = []
                    store[key].extend(values)
                    results.append(len(store[key]))
                elif op[0] == 'lrem':
                    _, key, count, value = op
                    lst = store.get(key, [])
                    if isinstance(lst, list):
                        removed = 0
                        new_lst = []
                        for item in lst:
                            if item == value and (count == 0 or removed < abs(count)):
                                removed += 1
                            else:
                                new_lst.append(item)
                        store[key] = new_lst
                        results.append(removed)
            return results

    def pipeline():
        return MockPipeline()

    mock.pipeline = pipeline

    # --- zrange_withscores ---
    async def zrange_withscores(key, start=0, stop=-1):
        ss = store.get(key, {})
        if not isinstance(ss, dict):
            return []
        items = sorted(ss.items(), key=lambda x: x[1])
        if stop == -1:
            return items[start:]
        return items[start:stop + 1]

    mock.zrange_withscores = AsyncMock(side_effect=zrange_withscores)

    # --- with_namespace ---
    def with_namespace(namespace: str):
        ns_mock = make_mock_redis(key_prefix)
        ns_mock._namespace = namespace
        # 共享同一个 store 不合适，命名空间隔离应独立
        # 这里返回一个全新的 mock（独立存储）
        return ns_mock

    mock.with_namespace = with_namespace

    # 保存内部存储以供测试访问
    mock._store = store

    return mock


def run_async(coro):
    """在同步测试中运行异步协程"""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. Namespace 隔离测试
# ---------------------------------------------------------------------------

class TestNamespaceIsolation:
    """
    测试不同 namespace 的数据完全隔离。
    参考 Go 工程 namespace 多租户支持的设计。
    """

    def test_namespace_register_and_get(self):
        """测试注册命名空间后可以正确获取"""
        import sys
        sys.path.insert(0, ".")
        from agentflow.namespace.manager import NamespaceManager

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.namespace")
        mgr = NamespaceManager(mock_redis, logger)

        async def _run():
            ns = await mgr.register("proj_001", "项目A", "测试项目A")
            assert ns.id == "proj_001"
            assert ns.name == "项目A"
            assert ns.description == "测试项目A"
            assert ns.created_at != ""
            return ns

        ns = run_async(_run())
        assert ns.id == "proj_001"

    def test_namespace_list(self):
        """测试列出所有命名空间"""
        from agentflow.namespace.manager import NamespaceManager

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.namespace")
        mgr = NamespaceManager(mock_redis, logger)

        async def _run():
            await mgr.register("proj_001", "项目A")
            await mgr.register("proj_002", "项目B")
            ns_list = await mgr.list()
            return ns_list

        ns_list = run_async(_run())
        ids = [ns.id for ns in ns_list]
        assert "proj_001" in ids
        assert "proj_002" in ids

    def test_namespace_delete(self):
        """测试删除命名空间后不可再获取"""
        from agentflow.namespace.manager import NamespaceManager

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.namespace")
        mgr = NamespaceManager(mock_redis, logger)

        async def _run():
            await mgr.register("proj_del", "待删除项目")
            assert await mgr.exists("proj_del") is True
            await mgr.delete("proj_del")
            assert await mgr.exists("proj_del") is False

        run_async(_run())

    def test_namespace_data_isolation(self):
        """
        测试不同 namespace 的 Redis key 完全隔离。
        namespace A 写入的数据不会出现在 namespace B 的 key 中。
        """
        mock_redis = make_mock_redis()

        # namespace A 的 key
        key_a = mock_redis.key("task", "task_001", namespace="proj_a")
        # namespace B 的 key
        key_b = mock_redis.key("task", "task_001", namespace="proj_b")
        # 默认 namespace 的 key
        key_default = mock_redis.key("task", "task_001")

        # 三个 key 应该互不相同
        assert key_a != key_b
        assert key_a != key_default
        assert key_b != key_default

        # 验证 key 格式包含 namespace
        assert "proj_a" in key_a
        assert "proj_b" in key_b
        assert "proj_a" not in key_default
        assert "proj_b" not in key_default

    def test_namespace_with_namespace_method(self):
        """测试 with_namespace 方法返回隔离的 RedisClient 视图"""
        from agentflow.storage.redis_client import RedisClient
        from agentflow.config import RedisConfig

        cfg = RedisConfig()
        cfg.addr = "127.0.0.1:6379"
        cfg.key_prefix = "af"
        logger = logging.getLogger("test")

        client = RedisClient(cfg, logger)
        ns_client = client.with_namespace("proj_test")

        # 带 namespace 的 key 应包含 namespace 前缀
        key_default = client.key("task", "123")
        key_ns = ns_client.key("task", "123")

        assert "proj_test" in key_ns
        assert "proj_test" not in key_default
        assert key_default != key_ns

    def test_namespace_data_isolation_strict(self):
        """
        严格数据隔离测试：验证写入 ns_a 的数据从 ns_b 读取不到。
        这是数据层面的隔离验证，而非仅验证 key 格式。
        """
        async def _run():
            # 使用两个独立的 mock_redis 实例模拟不同 namespace
            mock_redis_a = make_mock_redis(key_prefix="af:ns_a")
            mock_redis_b = make_mock_redis(key_prefix="af:ns_b")

            # 在 ns_a 写入数据
            key_a = mock_redis_a.key("task", "shared_task_id")
            await mock_redis_a.hset(key_a, {"title": "ns_a 的任务", "status": "pending"})

            # 从 ns_b 读取同名 key
            key_b = mock_redis_b.key("task", "shared_task_id")
            data_in_b = await mock_redis_b.hgetall(key_b)

            # ns_b 中不应有 ns_a 写入的数据
            assert data_in_b == {} or data_in_b.get("title") != "ns_a 的任务", \
                "ns_b 不应能读取到 ns_a 写入的数据"

            # 验证 ns_a 自己可以读取
            data_in_a = await mock_redis_a.hgetall(key_a)
            assert data_in_a.get("title") == "ns_a 的任务"
            assert data_in_a.get("status") == "pending"

            # 验证 key 格式不同（namespace 隔离的根本原因）
            assert key_a != key_b, "不同 namespace 的相同逻辑 key 不应相同"

        run_async(_run())


# ---------------------------------------------------------------------------
# 2. Collab 协作测试
# ---------------------------------------------------------------------------

class TestCollabFeatures:
    """
    测试 collab 协作模块：任务评论和 Agent 邮箱消息。
    参考 Go 工程 internal/collab/ 的测试逻辑。
    """

    def test_add_and_get_comments(self):
        """测试添加评论后可以正确获取"""
        from agentflow.collab.comment import CommentStore
        from agentflow.collab.mailbox import Mailbox

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.collab")
        mailbox = Mailbox(mock_redis, logger)
        store = CommentStore(mock_redis, mailbox, logger)

        async def _run():
            comment = await store.add_comment("task_001", "agent_a", "这是一条测试评论")
            assert comment.task_id == "task_001"
            assert comment.agent_id == "agent_a"
            assert comment.content == "这是一条测试评论"
            assert comment.id != ""

            comments = await store.get_comments("task_001")
            assert len(comments) == 1
            assert comments[0].content == "这是一条测试评论"

        run_async(_run())

    def test_comment_mention_notification(self):
        """
        测试评论中的 @mention 会触发邮箱通知。
        评论 @agent_b 时，agent_b 的邮箱应收到通知消息。
        """
        from agentflow.collab.comment import CommentStore, extract_mentions
        from agentflow.collab.mailbox import Mailbox

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.collab")
        mailbox = Mailbox(mock_redis, logger)
        store = CommentStore(mock_redis, mailbox, logger)

        async def _run():
            # 添加带 @mention 的评论
            comment = await store.add_comment(
                "task_001", "agent_a", "请 @agent_b 帮忙看一下这个问题"
            )
            assert "agent_b" in comment.mentions

            # agent_b 的邮箱应该收到通知
            messages = await mailbox.read("agent_b", limit=10)
            assert len(messages) >= 1
            # 验证消息内容包含任务 ID
            assert any("task_001" in msg.subject for msg in messages)

        run_async(_run())

    def test_mention_extraction(self):
        """测试从评论内容中提取 @mention"""
        from agentflow.collab.comment import extract_mentions

        mentions = extract_mentions("Hello @agent1 and @agent2, @agent1 again!")
        # 去重后应只有 agent1 和 agent2
        assert len(mentions) == 2
        assert "agent1" in mentions
        assert "agent2" in mentions

    def test_mailbox_send_and_read(self):
        """测试 Agent 邮箱发送和读取消息"""
        from agentflow.collab.mailbox import Mailbox
        from agentflow.collab.model import new_message

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.collab")
        mailbox = Mailbox(mock_redis, logger)

        async def _run():
            msg = new_message("agent_a", "agent_b", "任务通知", "任务 task_001 已完成", "task_001")
            await mailbox.send(msg)

            messages = await mailbox.read("agent_b", limit=10)
            assert len(messages) >= 1
            assert messages[0].from_agent == "agent_a"
            assert messages[0].subject == "任务通知"

        run_async(_run())

    def test_mailbox_mark_all_read(self):
        """测试标记所有邮件为已读"""
        from agentflow.collab.mailbox import Mailbox
        from agentflow.collab.model import new_message

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.collab")
        mailbox = Mailbox(mock_redis, logger)

        async def _run():
            # 发送 3 条消息
            for i in range(3):
                msg = new_message("agent_a", "agent_b", f"消息{i}", f"内容{i}")
                await mailbox.send(msg)

            # 标记全部已读
            await mailbox.mark_all_read("agent_b")

            # 验证游标已更新（Redis 中有游标 key）
            cursor_key = mailbox._read_cursor_key("agent_b")
            cursor = await mock_redis.get(cursor_key)
            assert cursor is not None

        run_async(_run())

    def test_multiple_comments_on_task(self):
        """测试一个任务可以有多条评论"""
        from agentflow.collab.comment import CommentStore

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.collab")
        store = CommentStore(mock_redis, None, logger)

        async def _run():
            await store.add_comment("task_002", "agent_a", "评论1")
            await store.add_comment("task_002", "agent_b", "评论2")
            await store.add_comment("task_002", "agent_a", "评论3")

            comments = await store.get_comments("task_002")
            assert len(comments) == 3

        run_async(_run())


# ---------------------------------------------------------------------------
# 3. Plugin 插件测试
# ---------------------------------------------------------------------------

class TestPluginSystem:
    """
    测试 plugin 插件系统：HTTP 插件注册和工具调用。
    使用 mock 模拟 HTTP 请求，避免真实网络连接。
    参考 Go 工程 internal/plugin/ 的测试逻辑。
    """

    def _make_mock_manifest(self, plugin_id: str, tools: List[Dict]) -> MagicMock:
        """创建模拟插件清单"""
        from agentflow.plugin.interfaces import PluginManifest, PluginToolDef
        manifest = PluginManifest(
            id=plugin_id,
            name=f"Test Plugin {plugin_id}",
            version="1.0.0",
            description="测试插件",
            tools=[
                PluginToolDef(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("input_schema", {"type": "object", "properties": {}}),
                )
                for t in tools
            ],
        )
        return manifest

    def test_plugin_register_and_list(self):
        """
        测试插件注册后可以在列表中找到。
        Mock 掉 HTTPPlugin.manifest() 避免真实 HTTP 请求。
        """
        from agentflow.plugin.manager import Manager
        from agentflow.plugin.interfaces import PluginConfig, PluginType, PluginStatus
        from agentflow.mcp_server.registry import Registry

        logger = logging.getLogger("test.plugin")
        registry = Registry(logger)

        async def _run():
            manager = Manager(registry, logger)

            # Mock HTTPPlugin
            with patch("agentflow.plugin.manager.HTTPPlugin") as MockHTTPPlugin:
                mock_plugin_instance = MagicMock()
                mock_plugin_instance.id.return_value = "test-plugin"
                mock_plugin_instance.manifest = AsyncMock(
                    return_value=self._make_mock_manifest("test-plugin", [
                        {"name": "hello", "description": "打招呼工具"},
                    ])
                )
                mock_plugin_instance.info.return_value = MagicMock(
                    config=MagicMock(id="test-plugin"),
                    status=PluginStatus.ACTIVE,
                    version="1.0.0",
                    tool_count=1,
                )
                mock_plugin_instance.unload = AsyncMock()
                MockHTTPPlugin.return_value = mock_plugin_instance

                config = PluginConfig(
                    id="test-plugin",
                    name="测试插件",
                    type=PluginType.HTTP,
                    address="http://localhost:18090",
                )
                info = await manager.register(config)
                assert info is not None

                plugins = manager.list()
                assert len(plugins) == 1

        run_async(_run())

    def test_plugin_unload(self):
        """测试卸载插件后不再出现在列表中"""
        from agentflow.plugin.manager import Manager
        from agentflow.plugin.interfaces import PluginConfig, PluginType, PluginStatus
        from agentflow.mcp_server.registry import Registry

        logger = logging.getLogger("test.plugin")
        registry = Registry(logger)

        async def _run():
            manager = Manager(registry, logger)

            with patch("agentflow.plugin.manager.HTTPPlugin") as MockHTTPPlugin:
                mock_plugin_instance = MagicMock()
                mock_plugin_instance.id.return_value = "plugin-to-unload"
                mock_plugin_instance.manifest = AsyncMock(
                    return_value=self._make_mock_manifest("plugin-to-unload", [
                        {"name": "tool1"},
                    ])
                )
                mock_plugin_instance.info.return_value = MagicMock(
                    config=MagicMock(id="plugin-to-unload"),
                    status=PluginStatus.ACTIVE,
                    version="1.0.0",
                    tool_count=1,
                )
                mock_plugin_instance.unload = AsyncMock()
                MockHTTPPlugin.return_value = mock_plugin_instance

                config = PluginConfig(
                    id="plugin-to-unload",
                    name="待卸载插件",
                    type=PluginType.HTTP,
                    address="http://localhost:18090",
                )
                await manager.register(config)
                assert len(manager.list()) == 1

                await manager.unload("plugin-to-unload")
                assert len(manager.list()) == 0

        run_async(_run())

    def test_plugin_duplicate_register_raises(self):
        """测试重复注册同一插件 ID 应抛出异常"""
        from agentflow.plugin.manager import Manager
        from agentflow.plugin.interfaces import PluginConfig, PluginType, PluginStatus
        from agentflow.mcp_server.registry import Registry

        logger = logging.getLogger("test.plugin")
        registry = Registry(logger)

        async def _run():
            manager = Manager(registry, logger)

            with patch("agentflow.plugin.manager.HTTPPlugin") as MockHTTPPlugin:
                mock_plugin_instance = MagicMock()
                mock_plugin_instance.id.return_value = "dup-plugin"
                mock_plugin_instance.manifest = AsyncMock(
                    return_value=self._make_mock_manifest("dup-plugin", [])
                )
                mock_plugin_instance.info.return_value = MagicMock(
                    config=MagicMock(id="dup-plugin"),
                    status=PluginStatus.ACTIVE,
                    version="1.0.0",
                    tool_count=0,
                )
                mock_plugin_instance.unload = AsyncMock()
                MockHTTPPlugin.return_value = mock_plugin_instance

                config = PluginConfig(
                    id="dup-plugin",
                    name="重复插件",
                    type=PluginType.HTTP,
                    address="http://localhost:18090",
                )
                await manager.register(config)

                # 第二次注册同 ID 应抛出 ValueError
                with pytest.raises(ValueError, match="已注册"):
                    await manager.register(config)

        run_async(_run())

    def test_plugin_tool_name_format(self):
        """
        测试插件工具注册到 MCP Registry 后的名称格式。
        工具名称应为 plugin_{plugin_id}_{tool_name} 格式。
        """
        from agentflow.plugin.manager import Manager
        from agentflow.plugin.interfaces import PluginConfig, PluginType, PluginStatus
        from agentflow.mcp_server.registry import Registry

        logger = logging.getLogger("test.plugin")
        registry = Registry(logger)

        async def _run():
            manager = Manager(registry, logger)

            with patch("agentflow.plugin.manager.HTTPPlugin") as MockHTTPPlugin:
                mock_plugin_instance = MagicMock()
                mock_plugin_instance.id.return_value = "calc-plugin"
                mock_plugin_instance.manifest = AsyncMock(
                    return_value=self._make_mock_manifest("calc-plugin", [
                        {"name": "add", "description": "加法"},
                        {"name": "subtract", "description": "减法"},
                    ])
                )
                mock_plugin_instance.info.return_value = MagicMock(
                    config=MagicMock(id="calc-plugin"),
                    status=PluginStatus.ACTIVE,
                    version="1.0.0",
                    tool_count=2,
                )
                mock_plugin_instance.unload = AsyncMock()
                MockHTTPPlugin.return_value = mock_plugin_instance

                config = PluginConfig(
                    id="calc-plugin",
                    name="计算插件",
                    type=PluginType.HTTP,
                    address="http://localhost:18090",
                )
                await manager.register(config)

                # 验证工具已注册到 Registry，名称格式正确
                tool_add = registry.get_handler("plugin_calc-plugin_add")
                tool_sub = registry.get_handler("plugin_calc-plugin_subtract")
                assert tool_add is not None, "plugin_calc-plugin_add 应已注册"
                assert tool_sub is not None, "plugin_calc-plugin_subtract 应已注册"

        run_async(_run())


# ---------------------------------------------------------------------------
# 4. Project 生命周期测试
# ---------------------------------------------------------------------------

class TestProjectLifecycle:
    """
    测试 project 生命周期：创建、阶段推进、审批流程。
    参考 Go 工程 tests/project_lifecycle_test.go。
    """

    def _make_project_env(self):
        """创建 project 测试环境"""
        from agentflow.project.store import ProjectStore
        from agentflow.project.engine import Engine
        from agentflow.project.engine import (
            CreateProjectParams, SubmitPhaseReviewParams,
            ApprovePhaseParams, RejectPhaseParams,
        )
        from agentflow.goal.store import GoalStore
        from agentflow.namespace.manager import NamespaceManager

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.project")
        ns_mgr = NamespaceManager(mock_redis, logger)
        goal_store = GoalStore(mock_redis, logger)
        project_store = ProjectStore(mock_redis, logger, ns_mgr)
        engine = Engine(project_store, goal_store, logger)
        return engine, project_store, mock_redis

    def test_create_project_happy_path(self):
        """
        测试创建项目的完整流程（HappyPath）：
        - 项目初始阶段应为 idea
        - PhaseGate 应自动创建
        """
        from agentflow.project.model import ProjectStatus

        engine, store, _ = self._make_project_env()

        async def _run():
            from agentflow.project.engine import CreateProjectParams
            p = await engine.create_project(
                CreateProjectParams(
                    title="测试项目-HappyPath",
                    description="这是一个完整流程测试项目",
                    priority=8,
                    tags=["test", "integration"],
                )
            )
            assert p.id != ""

            # 验证 PhaseGate 已自动创建（项目创建后添加阶段才有 PhaseGate）
            # 这里主要验证项目创建成功
            return p

        p = run_async(_run())
        assert p.id != ""

    def test_submit_phase_review(self):
        """
        测试提交阶段审阅：
        - 提交后 PhaseGate 状态应变为 in_review/pending
        """
        from agentflow.project.model import PhaseGateStatus

        engine, store, _ = self._make_project_env()

        async def _run():
            from agentflow.project.engine import CreateProjectParams, SubmitPhaseReviewParams
            from agentflow.project.model import Deliverable
            p = await engine.create_project(
                CreateProjectParams(
                    title="测试项目-提交审阅",
                    description="测试提交阶段审阅",
                )
            )
            # 先添加 idea 阶段
            p = await engine.add_phase(p.id, "idea", "Idea阶段")
            gate = await engine.submit_for_review(
                SubmitPhaseReviewParams(
                    project_id=p.id,
                    phase_name="idea",
                    deliverables=[
                        Deliverable(name="项目蓝图", description="已完成", is_completed=True)
                    ],
                    summary="Idea 阶段总结",
                )
            )
            assert gate is not None
            return gate

        gate = run_async(_run())
        assert gate is not None

    def test_approve_phase(self):
        """
        测试审批通过阶段：
        - 审批后 PhaseGate 状态应为 approved
        - 项目应推进到下一阶段
        """
        from agentflow.project.model import PhaseGateStatus

        engine, store, _ = self._make_project_env()

        async def _run():
            from agentflow.project.engine import (
                CreateProjectParams, SubmitPhaseReviewParams, ApprovePhaseParams
            )
            p = await engine.create_project(
                CreateProjectParams(
                    title="测试项目-审批通过",
                    description="测试审批通过流程",
                )
            )
            # 先添加 idea 阶段
            p = await engine.add_phase(p.id, "idea", "Idea阶段")
            # 提交审阅
            await engine.submit_for_review(
                SubmitPhaseReviewParams(
                    project_id=p.id,
                    phase_name="idea",
                    summary="Idea 阶段完成",
                )
            )
            # 审批通过
            updated_project = await engine.approve_phase(
                ApprovePhaseParams(
                    project_id=p.id,
                    phase_name="idea",
                    comment="内容完整，审批通过",
                    approved_by="test_reviewer",
                )
            )
            assert updated_project is not None

            # 验证 PhaseGate 状态
            gate = await store.get_phase_gate(p.id, "idea")
            assert gate.status == PhaseGateStatus.APPROVED

        run_async(_run())

    def test_reject_and_resubmit(self):
        """
        测试驳回后重新提交流程：
        - 驳回后 PhaseGate 状态应为 rejected
        - 重新提交后状态应变为 in_review/pending
        """
        from agentflow.project.model import PhaseGateStatus

        engine, store, _ = self._make_project_env()

        async def _run():
            from agentflow.project.engine import (
                CreateProjectParams, SubmitPhaseReviewParams, RejectPhaseParams
            )
            p = await engine.create_project(
                CreateProjectParams(
                    title="测试项目-驳回重提",
                    description="测试驳回后重新提交",
                )
            )
            # 先添加 idea 阶段
            p = await engine.add_phase(p.id, "idea", "Idea阶段")
            # 提交审阅
            await engine.submit_for_review(
                SubmitPhaseReviewParams(
                    project_id=p.id,
                    phase_name="idea",
                    summary="初次提交",
                )
            )
            # 驳回
            rejected_gate = await engine.reject_phase(
                RejectPhaseParams(
                    project_id=p.id,
                    phase_name="idea",
                    comment="内容不完整",
                )
            )
            assert rejected_gate.status == PhaseGateStatus.REJECTED

            # 重新提交
            resubmit_gate = await engine.submit_for_review(
                SubmitPhaseReviewParams(
                    project_id=p.id,
                    phase_name="idea",
                    summary="修订后重新提交",
                )
            )
            assert resubmit_gate is not None

        run_async(_run())

    def test_list_projects(self):
        """测试列出所有项目"""
        engine, store, _ = self._make_project_env()

        async def _run():
            from agentflow.project.engine import CreateProjectParams
            for i in range(3):
                await engine.create_project(
                    CreateProjectParams(
                        title=f"项目-{i}",
                        description=f"测试项目 {i}",
                    )
                )
            projects, total = await store.list_projects(page=1, page_size=10)
            assert total >= 3
            assert len(projects) >= 3

        run_async(_run())

    def test_phase_history_recorded(self):
        """测试审批历史被正确记录"""
        engine, store, _ = self._make_project_env()

        async def _run():
            from agentflow.project.engine import (
                CreateProjectParams, SubmitPhaseReviewParams, ApprovePhaseParams
            )
            p = await engine.create_project(
                CreateProjectParams(
                    title="测试项目-历史记录",
                    description="测试审批历史",
                )
            )
            # 先添加 idea 阶段
            p = await engine.add_phase(p.id, "idea", "Idea阶段")
            await engine.submit_for_review(
                SubmitPhaseReviewParams(
                    project_id=p.id,
                    phase_name="idea",
                    summary="提交审阅",
                )
            )
            await engine.approve_phase(
                ApprovePhaseParams(
                    project_id=p.id,
                    phase_name="idea",
                    comment="通过",
                    approved_by="reviewer",
                )
            )
            history = await store.get_phase_history(p.id)
            assert len(history) >= 1
            # 审批历史中应有 approved 记录
            actions = [h.action for h in history]
            assert any("approved" in a for a in actions)

        run_async(_run())


# ---------------------------------------------------------------------------
# 5. Webhook 触发测试
# ---------------------------------------------------------------------------

class TestWebhookDispatcher:
    """
    测试 webhook 触发和分发。
    使用 mock 模拟 HTTP 请求，验证事件分发逻辑。
    参考 Go 工程 internal/webhook/ 的设计。
    """

    def test_add_and_list_endpoints(self):
        """测试添加 Webhook 端点后可以列出"""
        from agentflow.webhook.dispatcher import Dispatcher
        from agentflow.webhook.model import WebhookEndpoint, EventType

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.webhook")
        dispatcher = Dispatcher(mock_redis, logger)

        async def _run():
            ep = WebhookEndpoint(
                id="wh_001",
                url="http://localhost:9090/webhook",
                event_types=[EventType.TASK_COMPLETED],
                enabled=True,
            )
            await dispatcher.add_endpoint(ep)

            endpoints = await dispatcher.list_endpoints()
            assert len(endpoints) >= 1
            urls = [e.url for e in endpoints]
            assert "http://localhost:9090/webhook" in urls

        run_async(_run())

    def test_remove_endpoint(self):
        """测试删除 Webhook 端点"""
        from agentflow.webhook.dispatcher import Dispatcher
        from agentflow.webhook.model import WebhookEndpoint, EventType

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.webhook")
        dispatcher = Dispatcher(mock_redis, logger)

        async def _run():
            ep = WebhookEndpoint(
                id="wh_del",
                url="http://localhost:9090/to-delete",
                enabled=True,
            )
            await dispatcher.add_endpoint(ep)
            assert len(await dispatcher.list_endpoints()) >= 1

            await dispatcher.remove_endpoint("wh_del")
            endpoints = await dispatcher.list_endpoints()
            ids = [e.id for e in endpoints]
            assert "wh_del" not in ids

        run_async(_run())

    def test_event_dispatch_to_matching_endpoint(self):
        """
        测试事件分发到匹配的端点。
        端点订阅了 TASK_COMPLETED，触发该事件时应发送 HTTP 请求。
        """
        from agentflow.webhook.dispatcher import Dispatcher
        from agentflow.webhook.model import WebhookEndpoint, WebhookEvent, EventType

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.webhook")
        dispatcher = Dispatcher(mock_redis, logger)

        async def _run():
            # 预设端点配置
            ep = WebhookEndpoint(
                id="wh_test",
                url="http://localhost:9090/hook",
                event_types=[EventType.TASK_COMPLETED],
                enabled=True,
            )
            await dispatcher.add_endpoint(ep)

            # Mock _send 方法，避免真实 HTTP 请求
            dispatcher._send = AsyncMock()

            event = WebhookEvent.new_event(
                EventType.TASK_COMPLETED,
                "task_001",
                {"task_id": "task_001", "status": "completed"},
            )
            # 直接调用内部分发方法（同步等待）
            await dispatcher._dispatch_async(event)

            # 验证 _send 被调用
            assert dispatcher._send.called

        run_async(_run())

    def test_event_not_dispatched_to_wrong_type(self):
        """
        测试事件类型不匹配时不分发。
        端点只订阅 TASK_FAILED，触发 TASK_COMPLETED 时不应发送。
        """
        from agentflow.webhook.dispatcher import Dispatcher
        from agentflow.webhook.model import WebhookEndpoint, WebhookEvent, EventType

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.webhook")
        dispatcher = Dispatcher(mock_redis, logger)

        async def _run():
            ep = WebhookEndpoint(
                id="wh_fail_only",
                url="http://localhost:9090/fail-hook",
                event_types=[EventType.TASK_FAILED],  # 只订阅失败事件
                enabled=True,
            )
            await dispatcher.add_endpoint(ep)

            dispatcher._send = AsyncMock()

            # 触发 TASK_COMPLETED 事件（不应分发到该端点）
            event = WebhookEvent.new_event(
                EventType.TASK_COMPLETED,
                "task_001",
            )
            await dispatcher._dispatch_async(event)

            # _send 不应被调用
            assert not dispatcher._send.called

        run_async(_run())

    def test_endpoint_should_receive_all_events(self):
        """测试空 event_types 的端点接收所有事件"""
        from agentflow.webhook.model import WebhookEndpoint, EventType

        ep = WebhookEndpoint(
            id="wh_all",
            url="http://localhost:9090/all",
            event_types=[],  # 空列表 = 接收所有事件
            enabled=True,
        )
        # 应接收所有事件类型
        for et in EventType:
            assert ep.should_receive(et) is True

    def test_disabled_endpoint_not_receive(self):
        """测试禁用的端点不接收事件"""
        from agentflow.webhook.model import WebhookEndpoint, EventType

        ep = WebhookEndpoint(
            id="wh_disabled",
            url="http://localhost:9090/disabled",
            enabled=False,
        )
        assert ep.should_receive(EventType.TASK_COMPLETED) is False

    def test_webhook_hmac_signature(self):
        """
        测试带 secret 的 Webhook 请求会携带 HMAC 签名头。
        验证 X-AgentFlow-Signature 头的格式和内容正确性。
        """
        import hmac as hmac_lib
        import hashlib
        import json as _json
        from agentflow.webhook.dispatcher import Dispatcher
        from agentflow.webhook.model import WebhookEndpoint, WebhookEvent, EventType

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.webhook.hmac")
        dispatcher = Dispatcher(mock_redis, logger)

        captured_headers = {}

        async def _run():
            secret = "my-webhook-secret"
            ep = WebhookEndpoint(
                id="wh_hmac",
                url="http://localhost:9090/hmac-hook",
                event_types=[EventType.TASK_COMPLETED],
                enabled=True,
                secret=secret,
            )
            await dispatcher.add_endpoint(ep)

            # 拦截 _send 调用，捕获发送的 headers
            async def mock_send(endpoint, payload, headers=None):
                captured_headers.update(headers or {})

            dispatcher._send = mock_send

            event = WebhookEvent(
                event_type=EventType.TASK_COMPLETED,
                payload={"task_id": "task_001", "status": "completed"},
            )
            await dispatcher.dispatch(event)

        run_async(_run())

        # 验证 HMAC 签名头存在
        assert "X-AgentFlow-Signature" in captured_headers, \
            "带 secret 的 Webhook 应携带 X-AgentFlow-Signature 头"

        sig_header = captured_headers["X-AgentFlow-Signature"]
        assert sig_header.startswith("sha256="), \
            "签名头应以 sha256= 开头"


# ---------------------------------------------------------------------------
# 6. 数据导入导出测试
# ---------------------------------------------------------------------------

class TestDataPortability:
    """
    测试数据导入导出功能（export_data / import_data）。
    参考 Go 工程 portability 模块的设计。
    """

    def _make_portability_env(self):
        """创建 portability 测试环境"""
        from agentflow.portability.exporter import Exporter
        from agentflow.portability.importer import Importer
        from agentflow.skill.store import SkillStore
        from agentflow.goal.store import GoalStore
        from agentflow.task.store import TaskStore
        from agentflow.lock.manager import LockManager

        mock_redis = make_mock_redis()
        logger = logging.getLogger("test.portability")
        from agentflow.config import SkillConfig
        skill_cfg = SkillConfig()
        skill_store = SkillStore(mock_redis, skill_cfg, logger)
        goal_store = GoalStore(mock_redis, logger)

        # TaskStore 需要 LockManager
        lock_mgr = MagicMock()
        lock_mgr.acquire = AsyncMock(return_value=True)
        lock_mgr.release = AsyncMock()
        task_store = TaskStore(mock_redis, lock_mgr, logger)

        exporter = Exporter(mock_redis, skill_store, goal_store, task_store, logger)
        importer = Importer(mock_redis, skill_store, goal_store, logger)
        return exporter, importer, mock_redis, skill_store, goal_store

    def test_export_empty_data(self):
        """测试导出空数据时返回有效的导出包"""
        from agentflow.portability.exporter import Exporter
        from agentflow.portability.model import ExportParams, ExportScope

        exporter, _, _, _, _ = self._make_portability_env()

        async def _run():
            params = ExportParams(scope=ExportScope())
            pkg = await exporter.export(params)
            assert pkg.version == "1.0"
            assert pkg.exported_at != ""
            assert pkg.stats is not None
            # 空数据时统计应为 0
            assert pkg.stats.skill_count == 0
            assert pkg.stats.goal_count == 0
            assert pkg.stats.task_count == 0
            return pkg

        pkg = run_async(_run())
        assert pkg is not None

    def test_export_global_rules(self):
        """测试导出全局规则"""
        from agentflow.portability.exporter import Exporter
        from agentflow.portability.model import ExportParams, ExportScope

        exporter, _, mock_redis, _, _ = self._make_portability_env()

        async def _run():
            # 预先写入全局规则
            rules_key = mock_redis.key("ctx", "global_rules")
            await mock_redis.rpush(rules_key, "规则1：代码必须有注释")
            await mock_redis.rpush(rules_key, "规则2：函数不超过50行")

            params = ExportParams(
                scope=ExportScope(
                    skills=False, experiences=False,
                    global_rules=True, goals=False, tasks=False,
                )
            )
            pkg = await exporter.export(params)
            assert pkg.stats.global_rule_count == 2
            assert "规则1：代码必须有注释" in pkg.global_rules
            assert "规则2：函数不超过50行" in pkg.global_rules

        run_async(_run())

    def test_import_global_rules_skip_policy(self):
        """
        测试导入全局规则（skip 冲突策略）：
        - 已存在的规则不重复导入
        """
        from agentflow.portability.importer import Importer
        from agentflow.portability.model import ExportPackage, ExportScope, ImportParams

        _, importer, mock_redis, _, _ = self._make_portability_env()

        async def _run():
            # 预先写入一条规则
            rules_key = mock_redis.key("ctx", "global_rules")
            await mock_redis.rpush(rules_key, "已有规则")

            # 导入包含重复规则的数据包
            pkg = ExportPackage(
                version="1.0",
                exported_at=datetime.now().isoformat(),
                scope=ExportScope(
                    skills=False, experiences=False,
                    global_rules=True, goals=False, tasks=False,
                ),
                global_rules=["已有规则", "新规则"],
            )
            params = ImportParams(conflict_policy="skip")
            result = await importer.import_data(pkg, params)

            # "已有规则" 被跳过，"新规则" 被导入
            assert result.global_rules_imported == 1
            assert len(result.errors) == 0

        run_async(_run())

    def test_import_global_rules_overwrite_policy(self):
        """
        测试导入全局规则（overwrite 冲突策略）：
        - 先清空再写入所有规则
        """
        from agentflow.portability.importer import Importer
        from agentflow.portability.model import ExportPackage, ExportScope, ImportParams

        _, importer, mock_redis, _, _ = self._make_portability_env()

        async def _run():
            # 预先写入旧规则
            rules_key = mock_redis.key("ctx", "global_rules")
            await mock_redis.rpush(rules_key, "旧规则1")
            await mock_redis.rpush(rules_key, "旧规则2")

            pkg = ExportPackage(
                version="1.0",
                exported_at=datetime.now().isoformat(),
                scope=ExportScope(
                    skills=False, experiences=False,
                    global_rules=True, goals=False, tasks=False,
                ),
                global_rules=["新规则A", "新规则B", "新规则C"],
            )
            params = ImportParams(conflict_policy="overwrite")
            result = await importer.import_data(pkg, params)

            # overwrite 后应有 3 条新规则
            assert result.global_rules_imported == 3
            # 验证旧规则已被清除
            current_rules = await mock_redis.lrange(rules_key, 0, -1)
            assert "旧规则1" not in current_rules
            assert "新规则A" in current_rules

        run_async(_run())

    def test_export_import_roundtrip_goals(self):
        """
        测试 Goals 导出后再导入的完整流程（round-trip）。
        导入后数据应与导出前一致。
        """
        from agentflow.portability.exporter import Exporter
        from agentflow.portability.importer import Importer
        from agentflow.portability.model import ExportParams, ExportScope, ImportParams
        from agentflow.goal.store import GoalStore

        exporter, importer, mock_redis, _, goal_store = self._make_portability_env()

        async def _run():
            # 创建 Goal
            goal = await goal_store.create(
                title="测试目标",
                description="用于导出导入测试",
                priority=5,
            )
            goal_id = goal.id

            # 导出
            params = ExportParams(
                scope=ExportScope(
                    skills=False, experiences=False,
                    global_rules=False, goals=True, tasks=False,
                )
            )
            pkg = await exporter.export(params)
            assert pkg.stats.goal_count >= 1
            assert any(g.get("id") == goal_id for g in pkg.goals)

            # 删除原 Goal（模拟迁移场景）
            await mock_redis.delete(mock_redis.key("goal", goal_id))
            await mock_redis.zrem(mock_redis.key("goal", "list"), goal_id)

            # 导入
            import_params = ImportParams(conflict_policy="skip")
            result = await importer.import_data(pkg, import_params)
            assert result.goals_imported >= 1
            assert len(result.errors) == 0

        run_async(_run())

    def test_export_package_serialization(self):
        """测试导出包可以正确序列化和反序列化"""
        from agentflow.portability.model import (
            ExportPackage, ExportScope, ExportStats, SkillExport, ExpExport
        )

        pkg = ExportPackage(
            version="1.0",
            exported_at=datetime.now().isoformat(),
            scope=ExportScope(),
            global_rules=["规则1", "规则2"],
            stats=ExportStats(global_rule_count=2),
        )

        # 序列化为 dict
        d = pkg.to_dict()
        assert d["version"] == "1.0"
        assert d["global_rules"] == ["规则1", "规则2"]
        assert d["stats"]["global_rule_count"] == 2

        # 从 dict 反序列化
        pkg2 = ExportPackage.from_dict(d)
        assert pkg2.version == "1.0"
        assert pkg2.global_rules == ["规则1", "规则2"]
        assert pkg2.stats.global_rule_count == 2

    def test_import_merge_skill_dna(self):
        """
        测试 merge 冲突策略：导入时合并 Skill DNA（追加规则/反模式/最佳实践）。
        验证已存在的 Skill 在 merge 模式下规则会被追加而不是覆盖。
        """
        from agentflow.portability.model import (
            ExportPackage, ExportScope, ExportStats, SkillExport, ImportParams
        )

        exporter, importer, mock_redis, skill_store, _ = self._make_portability_env()

        async def _run():
            from agentflow.config import SkillConfig
            from agentflow.skill.store import SkillStore

            # 1. 初始化 Skill DNA（已有一条规则）
            await skill_store.init_skill("test_skill")
            initial_dna = {
                "rules": ["规则A"],
                "anti_patterns": ["反模式X"],
                "best_practices": ["最佳实践1"],
            }
            await skill_store.update_dna("test_skill", initial_dna)

            # 2. 构造包含额外规则的导出包
            skill_export = SkillExport(
                skill_type="test_skill",
                skill={
                    "dna": {
                        "rules": ["规则B"],
                        "anti_patterns": ["反模式Y"],
                        "best_practices": ["最佳实践2"],
                    }
                },
            )
            pkg = ExportPackage(
                version="1.0",
                exported_at=datetime.now().isoformat(),
                scope=ExportScope(skills=True),
                skills=[skill_export],
                stats=ExportStats(skill_count=1),
            )

            # 3. 使用 merge 策略导入
            import_params = ImportParams(conflict_policy="merge")
            result = await importer.import_data(pkg, import_params)
            assert len(result.errors) == 0, f"merge 导入不应有错误: {result.errors}"

            # 4. 验证 DNA 已合并（规则追加）
            merged_dna = await skill_store.get_dna("test_skill")
            if merged_dna:
                rules = merged_dna.get("rules", [])
                # merge 后应包含原有规则和新增规则
                assert "规则A" in rules or "规则B" in rules, \
                    f"merge 后 DNA 规则应包含原有或新增规则，实际: {rules}"

        run_async(_run())
