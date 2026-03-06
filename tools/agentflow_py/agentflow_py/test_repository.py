#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 repository 模块导入"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

from agentflow.repository import (
    Backend,
    PageResult,
    TaskFilter,
    TaskRecord,
    TaskRepository,
    GoalFilter,
    GoalRecord,
    GoalRepository,
    SkillRecord,
    SkillRepository,
    ExperienceFilter,
    ExperienceRecord,
    ExperienceRepository,
    RepositoryFactory,
    Config,
    default_config,
    new_repository_factory,
    RedisTaskRepositoryAdapter,
    RedisRepositoryFactory,
)

def test_imports():
    """测试所有导入"""
    print("✓ 所有导入成功!")
    print(f"  Backend.REDIS = {Backend.REDIS}")
    
    # 测试 Config
    cfg = default_config()
    print(f"  默认配置: backend={cfg.backend}, redis_enabled={cfg.redis_enabled}")
    
    # 测试 PageResult
    result = PageResult(items=[1, 2, 3], total=10, page=1, page_size=20)
    print(f"  PageResult: items={len(result.items)}, total={result.total}")
    
    # 测试 TaskFilter
    filter = TaskFilter(status="pending", page=1, page_size=10)
    print(f"  TaskFilter: status={filter.status}, page={filter.page}")
    
    # 测试 TaskRecord
    task = TaskRecord(id="t1", title="测试任务", status="pending")
    print(f"  TaskRecord: id={task.id}, title={task.title}")
    
    print("\n✓ 所有测试通过!")


if __name__ == "__main__":
    test_imports()
