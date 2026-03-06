import logging
from typing import Dict

from agentflow.mcp_server import Registry, ToolDef, ToolLayer, new_json_result, new_error_result
from .store import SkillStore


def register_tools(registry: Registry, store: SkillStore, logger: logging.Logger) -> None:

    registry.register(
        ToolDef(
            name="get_skill",
            description="获取指定Skill DNA详情，包含规则/反模式/最佳实践/证据链。",
            input_schema={
                "type": "object",
                "properties": {"skill_type": {"type": "string"}},
                "required": ["skill_type"],
            },
            layer=ToolLayer.LAYER1,
        ),
        _make_get_skill_handler(store),
    )

    registry.register(
        ToolDef(
            name="list_skills",
            description="获取所有可用Skill类型列表及其基本信息。",
            input_schema={"type": "object", "properties": {}},
            layer=ToolLayer.LAYER1,
        ),
        _make_list_skills_handler(store),
    )

    registry.register(
        ToolDef(
            name="create_skill",
            description="创建新的Skill DNA。",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_type": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "rules": {"type": "array", "items": {"type": "string"}},
                    "anti_patterns": {"type": "array", "items": {"type": "string"}},
                    "best_practices": {"type": "array", "items": {"type": "string"}},
                    "context_hints": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["skill_type"],
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_create_skill_handler(store),
    )

    registry.register(
        ToolDef(
            name="update_skill",
            description="更新Skill DNA字段。",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_type": {"type": "string"},
                    "updates": {"type": "object"},
                },
                "required": ["skill_type", "updates"],
            },
            layer=ToolLayer.LAYER2,
        ),
        _make_update_skill_handler(store),
    )

    logger.debug("Skill 模块工具注册完成 count=4")


def _make_get_skill_handler(store: SkillStore):
    async def handler(params: Dict):
        try:
            skill = await store.get_skill(params["skill_type"])
            if not skill:
                return new_error_result(f"Skill {params['skill_type']} 不存在")
            return new_json_result(skill.to_dict())
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_list_skills_handler(store: SkillStore):
    async def handler(params: Dict):
        try:
            skills = await store.list_skills()
            return new_json_result({
                "skills": [s.to_dict() for s in skills],
                "count": len(skills),
            })
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_create_skill_handler(store: SkillStore):
    async def handler(params: Dict):
        try:
            from .model import SkillDNA
            dna = SkillDNA(
                skill_type=params["skill_type"],
                rules=params.get("rules", []),
                anti_patterns=params.get("anti_patterns", []),
                best_practices=params.get("best_practices", []),
                context_hints=params.get("context_hints", []),
            )
            await store.save_dna(dna)
            meta_key = store._redis.key("skill", dna.skill_type, "meta")
            await store._redis.hset(meta_key, {
                "name": params.get("name", dna.skill_type),
                "description": params.get("description", ""),
                "version": "1",
            })
            return new_json_result({"status": "created", "skill_type": dna.skill_type})
        except Exception as e:
            return new_error_result(str(e))
    return handler


def _make_update_skill_handler(store: SkillStore):
    async def handler(params: Dict):
        try:
            dna = await store.update_dna_fields(params["skill_type"], params.get("updates", {}))
            if not dna:
                return new_error_result(f"Skill {params['skill_type']} 不存在")
            return new_json_result({"status": "updated", "skill_type": dna.skill_type, "version": dna.version})
        except Exception as e:
            return new_error_result(str(e))
    return handler
