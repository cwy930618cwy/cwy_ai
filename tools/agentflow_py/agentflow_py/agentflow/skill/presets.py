"""Preset Skill DNAs - 6 built-in skill types."""
from .model import SkillDNA

PRESET_SKILLS = [
    SkillDNA(
        skill_type="go_crud",
        rules=[
            "使用 context.Context 作为所有函数的第一个参数",
            "错误处理必须包含足够的上下文信息，使用 fmt.Errorf 包装",
            "避免全局变量，通过依赖注入传递依赖",
            "接口定义在使用方，不在实现方（接口隔离原则）",
            "使用 slog 结构化日志记录",
        ],
        anti_patterns=[
            "不要在循环中打开数据库连接",
            "不要忽略错误返回值",
            "不要使用 panic 处理可预期的错误",
        ],
        best_practices=[
            "CRUD操作统一通过 Store 接口封装",
            "使用 Pipeline 批量执行 Redis 命令",
            "关键操作使用 Lua 脚本保证原子性",
        ],
        context_hints=["Redis HSET/HGETALL", "批量Pipeline", "Lua原子锁"],
    ),
    SkillDNA(
        skill_type="api_design",
        rules=[
            "RESTful API 遵循动词 + 名词复数格式",
            "响应统一包含 status/data/error 字段",
            "分页参数统一为 page/page_size，从1开始",
            "日期时间统一使用 ISO8601 格式",
        ],
        anti_patterns=[
            "不要在 URL 中暴露内部实现细节",
            "不要返回裸 500 错误",
        ],
        best_practices=[
            "使用 OpenAPI/Swagger 记录接口规范",
            "接口版本化：/api/v1/...",
            "幂等性：PUT/DELETE 操作可安全重试",
        ],
        context_hints=["FastAPI", "Pydantic校验", "OpenAPI文档"],
    ),
    SkillDNA(
        skill_type="testing",
        rules=[
            "测试用例命名遵循 test_{function}_{scenario}_{expected} 格式",
            "每个测试独立，不依赖其他测试的副作用",
            "Mock 外部依赖，避免真实网络/数据库调用",
            "覆盖率目标 ≥ 80%",
        ],
        anti_patterns=[
            "不要在测试中使用硬编码的端口/时间",
            "不要测试实现细节，只测试公开行为",
        ],
        best_practices=[
            "使用 fixture/setup 复用测试数据",
            "边界值测试：空值、nil、最大最小值",
            "异常路径测试：网络超时、DB失败等",
        ],
        context_hints=["pytest fixtures", "mock.patch", "parameterize"],
    ),
    SkillDNA(
        skill_type="code_review",
        rules=[
            "审查重点：安全性 > 正确性 > 性能 > 可读性",
            "发现问题时提供具体修改建议，而非仅指出问题",
            "区分 Blocker/Major/Minor/Suggestion 级别",
        ],
        anti_patterns=[
            "不要在 Review 中引入范围外的修改",
            "不要因为代码风格差异阻塞 Review",
        ],
        best_practices=[
            "关注边界条件和错误处理",
            "检查并发安全性（锁、原子操作）",
            "验证测试覆盖重要路径",
        ],
        context_hints=["安全检查清单", "性能热点识别", "依赖版本检查"],
    ),
    SkillDNA(
        skill_type="db_storage",
        rules=[
            "所有写操作必须在事务中执行",
            "索引策略：高频查询字段必须建索引",
            "禁止 SELECT *，明确指定字段",
            "敏感数据必须加密存储",
        ],
        anti_patterns=[
            "不要在应用层做联表查询的工作",
            "不要在循环中执行 N+1 查询",
            "不要在生产环境使用 DROP TABLE",
        ],
        best_practices=[
            "使用连接池，不要每次请求创建新连接",
            "长事务要有超时控制",
            "定期 EXPLAIN 分析慢查询",
        ],
        context_hints=["SQLite WAL模式", "Redis持久化", "连接池配置"],
    ),
    SkillDNA(
        skill_type="auth_security",
        rules=[
            "密码必须使用 bcrypt/argon2 哈希存储",
            "Token 使用 JWT，有效期不超过24小时",
            "所有外部输入必须校验和清洗",
            "HTTPS only，禁止明文传输敏感数据",
        ],
        anti_patterns=[
            "不要在日志中输出密码、Token、密钥",
            "不要硬编码密钥或秘密配置",
            "不要信任客户端传来的权限标志",
        ],
        best_practices=[
            "最小权限原则：只授予必要的权限",
            "SQL注入防御：使用参数化查询",
            "限流：API接口加速率限制",
        ],
        context_hints=["JWT验证", "RBAC权限模型", "OWASP Top 10"],
    ),
]


async def install_presets(store) -> None:
    for dna in PRESET_SKILLS:
        existing = await store.get_dna(dna.skill_type)
        if not existing:
            await store.save_dna(dna)
            meta_key = store._redis.key("skill", dna.skill_type, "meta")
            await store._redis.hset(meta_key, {
                "name": dna.skill_type.replace("_", " ").title(),
                "description": f"预置技能: {dna.skill_type}",
                "version": "1",
            })
