"""项目内容生成器 - 用于生成项目蓝图、阶段任务和总结报告。"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .model import Project


@dataclass
class StructuredIdea:
    """结构化的 Idea（从模糊想法解析而来）"""
    project_name: str = ""
    core_objective: str = ""
    target_users: str = ""
    key_features: List[str] = field(default_factory=list)
    tech_constraints: List[str] = field(default_factory=list)
    initial_risks: List[str] = field(default_factory=list)
    success_metrics: List[str] = field(default_factory=list)


@dataclass
class GoalTemplate:
    """目标模板（用于自动创建 Goal）"""
    title: str = ""
    description: str = ""
    priority: int = 5
    tags: List[str] = field(default_factory=list)
    phase: str = ""


@dataclass
class Milestone:
    """里程碑"""
    name: str = ""
    description: str = ""
    phase: str = ""
    criteria: str = ""  # 完成标准


@dataclass
class ResourceEstimate:
    """资源预估"""
    estimated_tokens: int = 0
    estimated_days: int = 0
    complexity: str = "medium"  # low/medium/high/very_high
    notes: str = ""


@dataclass
class MacroSupplement:
    """宏观补充内容"""
    sub_goals: List[GoalTemplate] = field(default_factory=list)
    tech_stack_suggestions: List[str] = field(default_factory=list)
    risk_list: List[str] = field(default_factory=list)
    dependency_analysis: str = ""
    milestones: List[Milestone] = field(default_factory=list)
    resource_estimate: ResourceEstimate = field(default_factory=ResourceEstimate)


@dataclass
class TaskTemplate:
    """任务模板（可直接用于 create_tasks）"""
    title: str = ""
    description: str = ""
    skill_type: str = ""
    difficulty: int = 5
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务标题（引用）
    tags: List[str] = field(default_factory=list)
    is_critical_path: bool = False  # 是否核心路径
    estimated_tokens: int = 0


@dataclass
class PhaseSummary:
    """阶段总结报告"""
    project_id: str = ""
    phase_name: str = ""
    completed: List[str] = field(default_factory=list)  # 已完成的工作
    in_progress: List[str] = field(default_factory=list)  # 进行中的工作
    risks: List[str] = field(default_factory=list)  # 风险项
    key_decisions: List[str] = field(default_factory=list)  # 关键决策
    next_steps: List[str] = field(default_factory=list)  # 下一步建议
    ready_for_review: bool = False  # 是否可以提交审阅


@dataclass
class ProjectBlueprint:
    """项目蓝图"""
    vision: str = ""
    core_features: List[str] = field(default_factory=list)
    target_users: str = ""
    tech_constraints: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    milestones: List[str] = field(default_factory=list)
    success_metrics: List[str] = field(default_factory=list)
    prompt: str = ""  # 给 AI 填充的提示词


class Generator:
    """阶段内容生成器
    注意：生成器不直接调用 LLM，而是构建结构化的模板和提示词，由调用方结合 AI 能力填充内容
    """

    def parse_idea(self, raw_idea: str) -> Tuple[StructuredIdea, str]:
        """将模糊想法解析为结构化项目描述（返回提示词模板）
        调用方应将返回的 prompt 发送给 LLM，然后将结果填充到 StructuredIdea 中
        """
        idea = StructuredIdea(
            project_name="待填充",
            core_objective=raw_idea,
        )

        prompt = f"""请将以下模糊想法解析为结构化项目描述：

【原始想法】
{raw_idea}

请按以下格式输出：
1. 项目名称（简洁、有意义）
2. 核心目标（一句话描述项目要解决的核心问题）
3. 目标用户（谁会使用这个项目）
4. 关键功能列表（3-7个核心功能，按优先级排序）
5. 初步技术约束（已知的技术限制或要求）
6. 初步风险（可能遇到的主要风险）
7. 成功指标（如何衡量项目成功）"""

        return idea, prompt

    def generate_project_blueprint(self, project: Project) -> ProjectBlueprint:
        """生成项目蓝图（提示词模板）"""
        blueprint = ProjectBlueprint(
            vision=project.vision or "",
            tech_constraints=project.tech_stack or [],
            risks=project.risk_list or [],
        )

        blueprint.prompt = f"""请为以下项目生成完整的项目蓝图：

【项目名称】{project.title}
【项目描述】{project.description}
【项目愿景】{project.vision or '待确定'}

请生成：
1. 核心功能列表（5-10个，按优先级排序）
2. 目标用户画像
3. 技术约束和要求
4. 主要风险清单（至少5个）
5. 里程碑规划（对应各阶段）
6. 成功指标（可量化的验收标准）

输出格式为结构化 JSON，便于后续处理。"""

        return blueprint

    def generate_macro_supplement(self, project: Project) -> Tuple[MacroSupplement, str]:
        """生成宏观补充内容（返回模板和提示词）"""
        supplement = MacroSupplement(
            sub_goals=[
                GoalTemplate(
                    title=f"[调研] {project.title} 技术选型",
                    description="调研并确定项目的技术栈和架构方案",
                    priority=8,
                    tags=["research", "tech-stack"],
                    phase="research",
                ),
                GoalTemplate(
                    title=f"[MVP] {project.title} 核心功能实现",
                    description="实现项目的最小可行产品，验证核心功能路径",
                    priority=9,
                    tags=["mvp", "core-feature"],
                    phase="mvp",
                ),
            ],
            milestones=[
                Milestone(name="Idea 确认", phase="idea", criteria="项目蓝图已审批通过"),
                Milestone(name="技术选型完成", phase="research", criteria="技术方案已确定并通过审批"),
                Milestone(name="MVP 上线", phase="mvp", criteria="核心功能可运行并通过演示"),
                Milestone(name="P1 稳定版", phase="p1", criteria="所有 P1 功能完成，测试通过"),
                Milestone(name="P2 完成", phase="p2", criteria="生产就绪，文档完善"),
            ],
            resource_estimate=ResourceEstimate(
                estimated_tokens=self._estimate_tokens(project),
                estimated_days=self._estimate_days(project),
                complexity=self._estimate_complexity(project),
            ),
        )

        tech_stack_str = ", ".join(project.tech_stack) if project.tech_stack else "未确定"
        risk_list_str = ", ".join(project.risk_list) if project.risk_list else "暂无"

        prompt = f"""请为以下项目生成详细的宏观补充规划：

【项目名称】{project.title}
【项目描述】{project.description}
【已知技术栈】{tech_stack_str}
【已知风险】{risk_list_str}

请生成：
1. 子目标树（按阶段拆解，每个阶段2-4个子目标）
2. 技术栈建议（推荐3种方案，说明优缺点）
3. 完整风险清单（至少8个，含应对策略）
4. 依赖分析（外部依赖、内部依赖、关键路径）
5. 里程碑规划（每个阶段的关键里程碑和完成标准）
6. 资源预估（开发时间、复杂度评估）"""

        return supplement, prompt

    def generate_research_tasks(self, project: Project) -> Tuple[List[TaskTemplate], str]:
        """生成调研阶段任务列表"""
        tasks = [
            TaskTemplate(
                title=f"技术方案对比 - {project.title}",
                description=f"""对 {project.title} 项目进行技术方案对比分析。

需要对比至少3种技术方案，每种方案评估：
- 技术成熟度和社区活跃度
- 性能特征
- 学习曲线
- 与现有技术栈的兼容性
- 长期维护成本

输出：技术选型决策文档""",
                skill_type="code_review",
                difficulty=5,
                is_critical_path=True,
                estimated_tokens=8000,
                tags=["research", "tech-comparison"],
            ),
            TaskTemplate(
                title=f"可行性分析 - {project.title}",
                description=f"""对 {project.title} 项目进行可行性分析。

分析维度：
- 技术可行性（现有技术能否支撑）
- 资源可行性（时间、人力是否充足）
- 风险评估（主要风险和缓解措施）
- 依赖评估（外部依赖的稳定性）

输出：可行性分析报告""",
                skill_type="code_review",
                difficulty=4,
                dependencies=[f"技术方案对比 - {project.title}"],
                estimated_tokens=6000,
                tags=["research", "feasibility"],
            ),
            TaskTemplate(
                title="依赖库/框架评估",
                description="""评估项目所需的关键依赖库和框架。

评估内容：
- 版本兼容性
- 许可证合规性
- 安全漏洞历史
- API 稳定性
- 替代方案

输出：依赖评估报告""",
                skill_type="code_review",
                difficulty=3,
                estimated_tokens=4000,
                tags=["research", "dependencies"],
            ),
            TaskTemplate(
                title="原型验证计划",
                description="""制定原型验证计划，确定 MVP 阶段的核心验证点。

内容：
- 核心假设列表（需要验证的关键假设）
- 验证方法（如何验证每个假设）
- 成功标准（验证通过的判断标准）
- 原型范围（最小化验证所需的功能集）

输出：原型验证计划文档""",
                skill_type="code_review",
                difficulty=4,
                dependencies=[f"可行性分析 - {project.title}"],
                is_critical_path=True,
                estimated_tokens=5000,
                tags=["research", "prototype"],
            ),
        ]

        tech_stack_str = ", ".join(project.tech_stack) if project.tech_stack else "未确定"

        prompt = f"""请为 {project.title} 项目的调研阶段生成详细的调研任务列表。

项目描述：{project.description}
已知技术约束：{tech_stack_str}

请生成：
1. 技术方案对比任务（至少对比3种方案）
2. 可行性分析任务
3. 关键依赖评估任务
4. 原型验证计划任务

每个任务需要包含：标题、详细描述、预估工作量、依赖关系、验收标准"""

        return tasks, prompt

    def generate_mvp_tasks(self, project: Project, research_summary: str = "") -> Tuple[List[TaskTemplate], str]:
        """基于调研结果生成 MVP 核心任务"""
        tasks = [
            TaskTemplate(
                title="MVP 架构设计",
                description=f"""为 {project.title} 项目设计 MVP 架构。

基于调研结果，设计最简可行的系统架构：
- 核心模块划分
- 数据流设计
- 接口定义
- 技术选型确认

输出：架构设计文档和接口规范""",
                skill_type="api_design",
                difficulty=7,
                is_critical_path=True,
                estimated_tokens=10000,
                tags=["mvp", "architecture"],
            ),
            TaskTemplate(
                title="核心数据模型实现",
                description="""实现 MVP 阶段的核心数据模型。

包括：
- 数据库表设计
- 核心实体定义
- 基础 CRUD 操作
- 数据验证逻辑""",
                skill_type="db_storage",
                difficulty=5,
                dependencies=["MVP 架构设计"],
                is_critical_path=True,
                estimated_tokens=8000,
                tags=["mvp", "data-model"],
            ),
            TaskTemplate(
                title="核心业务逻辑实现",
                description="""实现 MVP 阶段的核心业务逻辑。

包括：
- 核心功能流程
- 业务规则实现
- 错误处理
- 基础测试""",
                skill_type="go_crud",
                difficulty=7,
                dependencies=["核心数据模型实现"],
                is_critical_path=True,
                estimated_tokens=15000,
                tags=["mvp", "business-logic"],
            ),
            TaskTemplate(
                title="MVP API 接口实现",
                description="""实现 MVP 阶段的 API 接口层。

包括：
- RESTful API 设计
- 参数验证
- 错误响应
- 基础认证""",
                skill_type="api_design",
                difficulty=5,
                dependencies=["核心业务逻辑实现"],
                estimated_tokens=8000,
                tags=["mvp", "api"],
            ),
            TaskTemplate(
                title="MVP 集成测试",
                description="""编写 MVP 阶段的集成测试。

测试范围：
- 核心功能路径测试
- 边界条件测试
- 错误处理测试
- 性能基准测试""",
                skill_type="testing",
                difficulty=5,
                dependencies=["MVP API 接口实现"],
                estimated_tokens=8000,
                tags=["mvp", "testing"],
            ),
        ]

        prompt = f"""请为 {project.title} 项目的 MVP 阶段生成详细的任务列表。

项目描述：{project.description}
调研结论：{research_summary or '待补充'}

请生成 MVP 核心任务，要求：
1. 聚焦核心功能路径，避免过度设计
2. 每个任务有明确的依赖关系
3. 标记核心路径任务（is_critical_path=true）
4. 合理评估难度（1-10）和预估 Token 消耗
5. 任务描述包含明确的验收标准"""

        return tasks, prompt

    def generate_phase_summary(
        self,
        project: Project,
        phase_name: str,
        completed_tasks: List[str],
        in_progress_tasks: List[str],
    ) -> Tuple[PhaseSummary, str]:
        """生成阶段总结报告（提示词模板）"""
        summary = PhaseSummary(
            project_id=project.id,
            phase_name=phase_name,
            completed=completed_tasks,
            in_progress=in_progress_tasks,
        )

        completed_str = self._format_list(completed_tasks)
        in_progress_str = self._format_list(in_progress_tasks)

        prompt = f"""请为 {project.title} 项目的 {phase_name} 阶段生成总结报告。

项目描述：{project.description}
已完成任务：
{completed_str}

进行中任务：
{in_progress_str}

请生成：
1. 阶段成果总结（已完成的关键工作）
2. 风险项（当前存在的风险和问题）
3. 关键决策（本阶段做出的重要技术/产品决策）
4. 下一步建议（进入下一阶段的准备工作）
5. 是否可以提交审阅（ready_for_review: true/false，及理由）"""

        return summary, prompt

    def generate_research_plan(self, project: Project) -> Tuple[List[TaskTemplate], str]:
        """生成调研计划（generate_research_tasks 的规范化别名）
        
        返回调研阶段的任务列表和提示词，供调用方结合 LLM 生成具体调研内容。
        """
        return self.generate_research_tasks(project)

    def generate_phase_tasks(self, project: Project, phase_name: str) -> Tuple[List[TaskTemplate], str]:
        """生成阶段任务列表（generate_phase_tasks_for_phase 的规范化别名）
        
        根据阶段名称生成对应的任务模板列表和提示词。
        支持的阶段：research、mvp，其他阶段使用通用模板。
        """
        return self.generate_phase_tasks_for_phase(project, phase_name)

    def generate_phase_tasks_for_phase(self, project: Project, phase_name: str) -> Tuple[List[TaskTemplate], str]:
        """为指定阶段生成任务列表"""
        if phase_name == "research":
            return self.generate_research_tasks(project)
        elif phase_name == "mvp":
            return self.generate_mvp_tasks(project, "")
        else:
            return self._generate_generic_phase_tasks(project, phase_name)

    def _generate_generic_phase_tasks(self, project: Project, phase_name: str) -> Tuple[List[TaskTemplate], str]:
        """生成通用阶段任务"""
        tasks = [
            TaskTemplate(
                title=f"[{phase_name}] 阶段规划",
                description=f"制定 {phase_name} 阶段的详细执行计划",
                skill_type="code_review",
                difficulty=3,
                tags=[phase_name, "planning"],
            ),
            TaskTemplate(
                title=f"[{phase_name}] 核心工作",
                description=f"执行 {phase_name} 阶段的核心工作内容",
                skill_type="go_crud",
                difficulty=6,
                dependencies=[f"[{phase_name}] 阶段规划"],
                is_critical_path=True,
                tags=[phase_name, "core"],
            ),
            TaskTemplate(
                title=f"[{phase_name}] 阶段验收",
                description=f"验证 {phase_name} 阶段的产出物是否满足准出条件",
                skill_type="testing",
                difficulty=4,
                dependencies=[f"[{phase_name}] 核心工作"],
                tags=[phase_name, "review"],
            ),
        ]

        prompt = f"""请为 {project.title} 项目的 {phase_name} 阶段生成详细的任务列表。

项目描述：{project.description}

请根据阶段目标生成具体可执行的任务，每个任务需要：
- 明确的标题和描述
- 合理的技能类型（go_crud/api_design/db_storage/testing/code_review）
- 难度评分（1-10）
- 依赖关系
- 预估 Token 消耗"""

        return tasks, prompt

    def _estimate_tokens(self, project: Project) -> int:
        """基于项目复杂度估算 Token 消耗"""
        base = 50000
        if project.tech_stack and len(project.tech_stack) > 3:
            base += 20000
        if project.risk_list and len(project.risk_list) > 5:
            base += 10000
        return base

    def _estimate_days(self, project: Project) -> int:
        """基于项目复杂度估算开发天数"""
        base = 30
        if project.tech_stack and len(project.tech_stack) > 3:
            base += 15
        return base

    def _estimate_complexity(self, project: Project) -> str:
        """评估项目复杂度"""
        score = 0
        if project.tech_stack:
            if len(project.tech_stack) > 5:
                score += 2
            elif len(project.tech_stack) > 2:
                score += 1
        if project.risk_list:
            if len(project.risk_list) > 8:
                score += 2
            elif len(project.risk_list) > 4:
                score += 1

        if score >= 4:
            return "very_high"
        elif score >= 3:
            return "high"
        elif score >= 1:
            return "medium"
        else:
            return "low"

    def _format_list(self, items: List[str]) -> str:
        """格式化列表"""
        if not items:
            return "（无）"
        return "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))
