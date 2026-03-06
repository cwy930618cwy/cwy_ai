"""Dashboard HTTP server using FastAPI."""
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .service import DashboardService

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class DashboardHTTPServer:
    def __init__(self, service: DashboardService, addr: str, logger: logging.Logger):
        self._service = service
        self._addr = addr
        self._logger = logger
        self._server: Optional[uvicorn.Server] = None
        self._app = self._build_app()

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="AgentFlow Dashboard", version="2.0.0")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # ── 静态文件（CSS/JS）──────────────────────────────────────────────────
        static_dir = Path(__file__).parent / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        def _read_template(name: str) -> Optional[str]:
            """直接读取模板文件内容，不依赖jinja2"""
            tpl_path = TEMPLATES_DIR / name
            if tpl_path.exists():
                return tpl_path.read_text(encoding="utf-8")
            return None

        # ── Pages ──────────────────────────────────────────────────────────────
        @app.get("/", response_class=HTMLResponse)
        async def dashboard_page(request: Request):
            html = _read_template("dashboard.html")
            if html:
                return HTMLResponse(content=html)
            return HTMLResponse(content=_fallback_dashboard_html())

        @app.get("/health", response_class=HTMLResponse)
        async def health_page(request: Request):
            html = _read_template("health.html")
            if html:
                return HTMLResponse(content=html)
            return HTMLResponse(content="<h1>AgentFlow Health</h1><a href='/api/health'>API Health</a>")

        # ── API Routes ──────────────────────────────────────────────────────────
        @app.get("/api/dashboard")
        async def api_dashboard():
            return await self._service.get_dashboard_data()

        @app.get("/api/health")
        async def api_health():
            """返回健康检查数组，与前端 loadHealthData 的期望格式一致"""
            checks = []
            # Redis 检查
            try:
                await self._service._redis.health_check()
                mem = await self._service._redis.memory_usage()
                checks.append({"Name": "Redis", "Status": "healthy", "Detail": f"连接正常, keys={mem}"})
            except Exception as e:
                checks.append({"Name": "Redis", "Status": "error", "Detail": str(e)})
            # SQLite 检查
            if self._service._sqlite:
                checks.append({"Name": "SQLite", "Status": "healthy", "Detail": "已连接"})
            else:
                checks.append({"Name": "SQLite", "Status": "warning", "Detail": "未配置"})
            # 版本信息
            checks.append({"Name": "Version", "Status": "healthy", "Detail": "AgentFlow v2.0.0 (Python)"})
            return checks

        @app.get("/api/tasks")
        async def api_tasks(status: str = "", goal_id: str = "", page: int = 1, page_size: int = 20):
            return await self._service.get_tasks(status=status, goal_id=goal_id, page=page, page_size=page_size)

        @app.post("/api/tasks/update")
        async def api_update_task(request: Request):
            body = await request.json()
            task_id = body.get("task_id", "")
            fields = body.get("fields", {})
            await self._service._redis.hset(
                self._service._redis.key("task", task_id), fields
            )
            return {"status": "updated"}

        @app.post("/api/tasks/delete")
        async def api_delete_task(request: Request):
            body = await request.json()
            ok = await self._service.delete_task(body.get("task_id", ""))
            return {"status": "deleted" if ok else "not_found"}

        @app.post("/api/tasks/delete-by-goal")
        async def api_delete_tasks_by_goal(request: Request):
            body = await request.json()
            goal_id = body.get("goal_id", "")
            # 获取该 goal 下的所有任务
            all_tasks = await self._service.get_tasks(goal_id=goal_id)
            count = 0
            for task in all_tasks:
                tid = task.get("id", "")
                if tid and await self._service.delete_task(tid):
                    count += 1
            return {"status": "deleted", "goal_id": goal_id, "deleted_count": count}

        @app.post("/api/tasks/update-status")
        async def api_update_task_status(request: Request):
            body = await request.json()
            task_id = body.get("task_id", "")
            new_status = body.get("new_status", "") or body.get("status", "")
            if not task_id or not new_status:
                raise HTTPException(400, "task_id 和 new_status 不能为空")
            ok = await self._service.update_task_status(task_id, new_status)
            return {"status": "updated" if ok else "not_found", "task_id": task_id, "new_status": new_status}

        @app.post("/api/tasks/split")
        async def api_split_task(request: Request):
            body = await request.json()
            parent_task_id = body.get("parent_task_id", "")
            subtasks = body.get("subtasks", [])
            if not parent_task_id or not subtasks:
                raise HTTPException(400, "parent_task_id 和 subtasks 不能为空")
            result = await self._service.split_task(parent_task_id, subtasks)
            return result

        @app.post("/api/tasks/review-batch-pass")
        async def api_review_batch_pass(request: Request):
            """批量通过指定目标下所有 review 任务（与 Go 版 handleAPIReviewBatchPass 一致）。"""
            body = await request.json()
            goal_id = body.get("goal_id", "")
            if not goal_id:
                return JSONResponse({"error": "goal_id 不能为空"}, status_code=400)
            try:
                updated = await self._service.review_batch_pass(
                    goal_id,
                    reviewer=body.get("reviewer", ""),
                    comment=body.get("comment", ""),
                )
                return {"status": "ok", "goal_id": goal_id, "updated_count": updated, "review_result": "passed"}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/tasks/review-batch-fail")
        async def api_review_batch_fail(request: Request):
            """批量拒绝指定目标下所有 review 任务（与 Go 版 handleAPIReviewBatchFail 一致）。"""
            body = await request.json()
            goal_id = body.get("goal_id", "")
            if not goal_id:
                return JSONResponse({"error": "goal_id 不能为空"}, status_code=400)
            try:
                updated = await self._service.review_batch_fail(
                    goal_id,
                    reviewer=body.get("reviewer", ""),
                    comment=body.get("comment", ""),
                )
                return {"status": "ok", "goal_id": goal_id, "updated_count": updated, "review_result": "failed"}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/goals")
        async def api_goals(page: int = 1, page_size: int = 20,
                            statuses: str = "", name: str = ""):
            """目标列表，支持多状态过滤和名称模糊搜索（与 Go 版 handleAPIGoals 一致）。"""
            status_list = [s.strip() for s in statuses.split(",") if s.strip()] if statuses else []
            if status_list or name:
                try:
                    goals = await self._service.get_goals_filtered(statuses=status_list, name=name)
                    return goals or []
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)
            return await self._service.get_goals(page=page, page_size=page_size)

        @app.post("/api/goals/delete")
        async def api_delete_goal(request: Request):
            body = await request.json()
            ok = await self._service.delete_goal(body.get("goal_id", ""))
            return {"status": "deleted" if ok else "not_found"}

        @app.post("/api/goals/update-status")
        async def api_update_goal_status(request: Request):
            body = await request.json()
            goal_id = body.get("goal_id", "")
            new_status = body.get("new_status", "") or body.get("status", "")
            if not goal_id or not new_status:
                return JSONResponse({"error": "goal_id 和 new_status 不能为空"}, status_code=400)
            try:
                await self._service.update_goal_status(goal_id, new_status)
                return {"status": "updated", "goal_id": goal_id, "new_status": new_status}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/skills")
        async def api_skills():
            """Skill 列表（与 Go 版 handleAPISkills 一致，使用 skill:list）。"""
            try:
                skills = await self._service.get_skills()
                return skills or []
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/skills/detail")
        async def api_skill_detail(name: str = "", skill_type: str = ""):
            """Skill 详情（含完整 DNA，与 Go 版 handleAPISkillDetail 一致）。"""
            skill_name = name or skill_type
            if not skill_name:
                return JSONResponse({"error": "name 参数不能为空"}, status_code=400)
            try:
                return await self._service.get_skill_detail(skill_name)
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=404)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/skills/create")
        async def api_create_skill(request: Request):
            """创建 Skill（与 Go 版 handleAPISkillCreate 一致）。"""
            body = await request.json()
            try:
                await self._service.create_skill_from_dashboard(body)
                return {"status": "created", "name": body.get("name", "")}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/skills/update")
        async def api_update_skill(request: Request):
            """更新 Skill（与 Go 版 handleAPISkillUpdate 一致）。"""
            body = await request.json()
            name = body.get("name", "")
            fields = body.get("fields", body)  # 兼容直接传 fields 或嵌套 fields
            if not name:
                return JSONResponse({"error": "name 不能为空"}, status_code=400)
            try:
                await self._service.update_skill_from_dashboard(name, fields)
                return {"status": "updated", "name": name}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/skills/delete")
        async def api_delete_skill(request: Request):
            """删除 Skill（与 Go 版 handleAPISkillDelete 一致）。"""
            body = await request.json()
            name = body.get("name", "") or body.get("skill_type", "")
            if not name:
                return JSONResponse({"error": "name 不能为空"}, status_code=400)
            try:
                await self._service.delete_skill_from_dashboard(name)
                return {"status": "deleted", "name": name}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/skills/audit")
        async def api_skill_audit(request: Request):
            """审核 Skill DNA 质量（与 Go 版 handleAPISkillAudit 一致）。"""
            body = await request.json()
            name = body.get("name", "")
            if not name:
                return JSONResponse({"error": "name 不能为空"}, status_code=400)
            try:
                result = await self._service.audit_skill_from_dashboard(
                    name, auto_fix=body.get("auto_fix", False)
                )
                return result
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/skills/absorb")
        async def api_absorb_skills(request: Request):
            """吸收远程 Skill（与 Go 版 handleAPIAbsorbSkills 一致）。"""
            body = await request.json()
            remote_addr = body.get("remote_addr", "")
            if not remote_addr:
                return JSONResponse({"error": "remote_addr 不能为空"}, status_code=400)
            try:
                result = await self._service.absorb_skills(
                    remote_addr,
                    keyword=body.get("keyword", ""),
                    overwrite=body.get("overwrite", False),
                )
                return result
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/skills/evolve")
        async def api_skill_evolve(request: Request):
            """手动触发 Skill 进化（与 Go 版 handleAPISkillEvolve 一致）。"""
            body = await request.json()
            name = body.get("name", "")
            if not name:
                return JSONResponse({"error": "name 不能为空"}, status_code=400)
            try:
                result = await self._service.evolve_skill_from_dashboard(
                    name, auto_apply=body.get("auto_apply", True)
                )
                return result
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/config/skill-auto-evolution")
        async def api_get_skill_auto_evolution():
            """获取 Skill 自动进化开关状态（与 Go 版 handleAPISkillAutoEvolution GET 一致）。"""
            try:
                enabled = await self._service.get_skill_auto_evolution()
                return {"enabled": enabled}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/config/skill-auto-evolution")
        async def api_set_skill_auto_evolution(request: Request):
            """设置 Skill 自动进化开关（与 Go 版 handleAPISkillAutoEvolution POST 一致）。"""
            body = await request.json()
            try:
                await self._service.set_skill_auto_evolution(bool(body.get("enabled", True)))
                return {"status": "updated", "enabled": body.get("enabled", True)}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/recovery-timeline")
        async def api_recovery_timeline(task_id: str = "", agent_id: str = ""):
            """恢复链路数据（与 Go 版 handleAPIRecoveryTimeline 一致）。"""
            try:
                return await self._service.get_recovery_timeline(task_id=task_id, agent_id=agent_id)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/complaints")
        async def api_complaints(cursor: str = "", limit: int = 20, type: str = ""):
            """吐槽列表（与 Go 版 handleAPIComplaints 一致，支持 cursor 分页）。"""
            try:
                return await self._service.get_complaints_list(
                    cursor=cursor, limit=limit, filter_type=type
                )
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/complaints/stats")
        async def api_complaint_stats():
            """吐槽统计（与 Go 版 handleAPIComplaintStats 一致）。"""
            try:
                data = await self._service.get_dashboard_data()
                if "complaint_stats" in data:
                    return data["complaint_stats"]
                return {"total_count": 0, "by_type": {}, "by_severity": {}}
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/fix-experiences")
        async def api_fix_experiences(type: str = "positive", limit: int = 50,
                                       keyword: str = ""):
            """经验列表（与 Go 版 handleAPIFixExperiences 一致）。"""
            try:
                experiences = await self._service.get_fix_experiences(type, limit)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            # 关键词过滤
            if keyword:
                kw = keyword.lower()
                experiences = [
                    exp for exp in experiences
                    if kw in (exp.get("description", "")).lower()
                    or kw in (exp.get("solution", "")).lower()
                ]
            return {"experiences": experiences, "count": len(experiences)}

        @app.get("/api/fix-experiences/stats")
        async def api_fix_experience_stats():
            """经验统计（与 Go 版 handleAPIFixExperienceStats 一致）。"""
            try:
                stats = await self._service.get_fix_experience_stats()
                return stats
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/fix-experiences/delete")
        async def api_delete_fix_experience(request: Request):
            """删除经验（与 Go 版 handleAPIDeleteFixExperience 一致）。"""
            body = await request.json()
            exp_type = body.get("type", "")
            exp_id = body.get("id", "")
            if not exp_type or not exp_id:
                return JSONResponse({"error": "type 和 id 不能为空"}, status_code=400)
            ok = await self._service.delete_fix_experience(exp_type, exp_id)
            if ok:
                return {"status": "deleted", "id": exp_id}
            return JSONResponse({"error": "经验不存在"}, status_code=404)

        @app.post("/api/fix-experiences/create")
        async def api_create_fix_experience(request: Request):
            """手动创建经验（与 Go 版 handleAPICreateFixExperience 一致）。"""
            body = await request.json()
            exp_type = body.get("type", "")
            fields = body.get("fields", {})
            if not exp_type:
                return JSONResponse({"error": "type 不能为空"}, status_code=400)
            if not fields:
                return JSONResponse({"error": "fields 不能为空"}, status_code=400)
            try:
                msg_id = await self._service.create_fix_experience(exp_type, fields)
                return {"status": "created", "id": msg_id, "type": exp_type}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/fix-experiences/update")
        async def api_update_fix_experience(request: Request):
            """更新经验（与 Go 版 handleAPIUpdateFixExperience 一致）。"""
            body = await request.json()
            exp_type = body.get("type", "")
            exp_id = body.get("id", "")
            fields = body.get("fields", {})
            if not exp_type or not exp_id:
                return JSONResponse({"error": "type 和 id 不能为空"}, status_code=400)
            if not fields:
                return JSONResponse({"error": "fields 不能为空"}, status_code=400)
            ok = await self._service.update_fix_experience(exp_type, exp_id, fields)
            if ok:
                return {"status": "updated", "id": exp_id}
            return JSONResponse({"error": "经验不存在"}, status_code=404)

        @app.post("/api/fix-experiences/absorb")
        async def api_absorb_experiences(request: Request):
            """吸收远程经验（与 Go 版 handleAPIAbsorbExperiences 一致）。"""
            body = await request.json()
            remote_addr = body.get("remote_addr", "")
            if not remote_addr:
                return JSONResponse({"error": "remote_addr 不能为空"}, status_code=400)
            import aiohttp
            remote_addr = remote_addr.rstrip("/")
            if not remote_addr.startswith("http"):
                remote_addr = "http://" + remote_addr
            absorbed = 0
            failed = 0
            try:
                async with aiohttp.ClientSession() as session:
                    for exp_type in ["positive", "negative"]:
                        try:
                            async with session.get(
                                f"{remote_addr}/api/fix-experiences?type={exp_type}&limit=100",
                                timeout=aiohttp.ClientTimeout(total=30)
                            ) as resp:
                                if resp.status != 200:
                                    continue
                                data = await resp.json()
                                exps = data.get("experiences", [])
                                for exp in exps:
                                    try:
                                        fields = {k: v for k, v in exp.items() if k != "id" and v}
                                        await self._service.create_fix_experience(exp_type, fields)
                                        absorbed += 1
                                    except Exception:
                                        failed += 1
                        except Exception:
                            failed += 1
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            return {"status": "done", "absorbed": absorbed, "failed": failed}

        @app.post("/api/fix-experiences/organize")
        async def api_organize_experiences():
            """整理经验（去重+自动标注，与 Go 版 handleAPIOrganizeExperiences 一致）。"""
            try:
                result = await self._service.organize_experiences()
                return result
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # ── Project API ────────────────────────────────────────────────────────

        @app.get("/api/projects")
        async def api_projects(status: str = "", tags: str = "",
                                page: int = 1, page_size: int = 20):
            """项目列表（与 Go 版 handleAPIProjects GET 一致）。"""
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            try:
                return await self._service.get_projects(
                    status=status, tags=tag_list, page=page, page_size=page_size
                )
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects")
        async def api_create_project(request: Request):
            """创建项目（与 Go 版 handleAPIProjects POST 一致）。"""
            import uuid
            import json as _json
            from datetime import datetime, timezone
            body = await request.json()
            title = body.get("title", "")
            description = body.get("description", "")
            if not title or not description:
                return JSONResponse({"error": "title 和 description 不能为空"}, status_code=400)
            pid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            data = {
                "id": pid,
                "title": title,
                "description": body.get("description", ""),
                "vision": body.get("vision", ""),
                "status": "active",
                "priority": str(body.get("priority", 5)),
                "tech_stack": _json.dumps(body.get("tech_stack", [])),
                "tags": _json.dumps(body.get("tags", [])),
                "created_at": now,
                "updated_at": now,
            }
            await self._service._redis.hset(
                self._service._redis.key("project", pid), data
            )
            await self._service._redis.zadd(
                self._service._redis.key("project", "list"), {pid: 0}
            )
            return JSONResponse(data, status_code=201)

        @app.get("/api/projects/{project_id}")
        async def api_project_detail(project_id: str):
            """项目详情（与 Go 版 handleAPIProjectDetail 一致）。"""
            try:
                return await self._service.get_project_detail(project_id)
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=404)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/projects/{project_id}/phases")
        async def api_project_phases(project_id: str):
            """阶段门控列表（与 Go 版 handleAPIProjectGates 一致）。"""
            try:
                return await self._service.get_project_phases(project_id)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/projects/{project_id}/phases/{phase}/overview")
        async def api_phase_overview(project_id: str, phase: str):
            """阶段概览（与 Go 版 handleAPIPhaseOverview 一致）。"""
            try:
                return await self._service.get_phase_overview(project_id, phase)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects/{project_id}/phases/{phase}/submit")
        async def api_phase_submit(project_id: str, phase: str, request: Request):
            """提交审阅（将 gate 状态设为 in_review）。"""
            body = await request.json()
            try:
                return await self._service.submit_phase_review(
                    project_id, phase,
                    comment=body.get("comment", ""),
                    submitted_by=body.get("submitted_by", ""),
                )
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects/{project_id}/phases/{phase}/approve")
        async def api_phase_approve(project_id: str, phase: str, request: Request):
            """审批通过（与 Go 版 handleAPIProjectGateApprove 一致）。"""
            body = await request.json()
            try:
                return await self._service.approve_phase(
                    project_id, phase,
                    comment=body.get("comment", ""),
                    approved_by=body.get("approved_by", ""),
                )
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects/{project_id}/phases/{phase}/reject")
        async def api_phase_reject(project_id: str, phase: str, request: Request):
            """驳回（与 Go 版 handleAPIProjectGateReject 一致）。"""
            body = await request.json()
            comment = body.get("comment", "")
            if not comment:
                return JSONResponse({"error": "comment 不能为空"}, status_code=400)
            try:
                return await self._service.reject_phase(
                    project_id, phase,
                    comment=comment,
                    revision_items=body.get("revision_items", []),
                )
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.delete("/api/projects/{project_id}")
        async def api_delete_project(project_id: str, cascade: bool = False):
            """删除项目（与 Go 版 handleAPIProjectDelete 一致）。"""
            try:
                await self._service.delete_project(project_id, cascade=cascade)
                return {"status": "deleted", "project_id": project_id}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=404)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects/{project_id}/phases/add")
        async def api_phase_add(project_id: str, request: Request):
            """添加阶段（与 Go 版 handleAPIPhaseAdd 一致）。"""
            body = await request.json()
            name = body.get("name", "")
            if not name:
                return JSONResponse({"error": "name 不能为空"}, status_code=400)
            try:
                result = await self._service.add_phase(
                    project_id, name,
                    description=body.get("description", ""),
                    parent_phase=body.get("parent_phase", ""),
                    order=body.get("order"),
                )
                return result
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects/{project_id}/phases/remove")
        async def api_phase_remove(project_id: str, request: Request):
            """删除阶段（与 Go 版 handleAPIPhaseRemove 一致）。"""
            body = await request.json()
            phase_name = body.get("phase_name", "") or body.get("name", "")
            if not phase_name:
                return JSONResponse({"error": "phase_name 不能为空"}, status_code=400)
            try:
                await self._service.remove_phase(project_id, phase_name)
                return {"status": "removed", "phase_name": phase_name}
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/projects/{project_id}/phases/update")
        async def api_phase_update(project_id: str, request: Request):
            """更新阶段（与 Go 版 handleAPIPhaseUpdate 一致）。"""
            body = await request.json()
            phase_name = body.get("phase_name", "") or body.get("name", "")
            if not phase_name:
                return JSONResponse({"error": "phase_name 不能为空"}, status_code=400)
            try:
                result = await self._service.update_phase(
                    project_id, phase_name,
                    new_name=body.get("new_name", ""),
                    new_description=body.get("new_description", ""),
                )
                return result
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # ── FixExp Sessions API ────────────────────────────────────────────────

        @app.get("/api/fixexp/sessions")
        async def api_fixexp_sessions(page: int = 1, page_size: int = 20):
            """Fix Session 列表。"""
            try:
                return await self._service.get_fix_sessions(page=page, page_size=page_size)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/fixexp/sessions/{session_id}")
        async def api_fixexp_session_detail(session_id: str):
            """Session 详情。"""
            try:
                return await self._service.get_fix_session_detail(session_id)
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=404)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/fixexp/experiences")
        async def api_fixexp_experiences(type: str = "positive", page: int = 1,
                                          page_size: int = 20, keyword: str = ""):
            """经验列表（支持分页，与 Go 版 handleAPIFixExperiences 一致）。"""
            try:
                return await self._service.get_fixexp_experiences(
                    exp_type=type, page=page, page_size=page_size, keyword=keyword
                )
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # ── Context Metrics API ────────────────────────────────────────────────

        @app.get("/api/context/metrics")
        async def api_context_metrics():
            """编译指标概览。"""
            try:
                return await self._service.get_context_metrics()
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.get("/api/context/metrics/trend")
        async def api_context_metrics_trend(days: int = 7):
            """趋势数据。"""
            try:
                return await self._service.get_context_metrics_trend(days=days)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # ── Webhook API ────────────────────────────────────────────────────────

        @app.get("/api/webhooks")
        async def api_webhooks():
            """Webhook 列表。"""
            try:
                return await self._service.get_webhooks()
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/webhooks")
        async def api_add_webhook(request: Request):
            """添加 Webhook。"""
            body = await request.json()
            url = body.get("url", "")
            if not url:
                return JSONResponse({"error": "url 不能为空"}, status_code=400)
            try:
                return await self._service.add_webhook(
                    url=url,
                    events=body.get("events", []),
                    name=body.get("name", ""),
                )
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.delete("/api/webhooks/{webhook_id}")
        async def api_delete_webhook(webhook_id: str):
            """删除 Webhook。"""
            try:
                ok = await self._service.delete_webhook(webhook_id)
                if ok:
                    return {"status": "deleted", "id": webhook_id}
                return JSONResponse({"error": "Webhook 不存在"}, status_code=404)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        # ── Namespace API ──────────────────────────────────────────────────────

        @app.get("/api/namespaces")
        async def api_namespaces():
            """命名空间列表。"""
            try:
                return await self._service.get_namespaces()
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        @app.post("/api/namespaces")
        async def api_create_namespace(request: Request):
            """创建命名空间。"""
            body = await request.json()
            name = body.get("name", "")
            if not name:
                return JSONResponse({"error": "name 不能为空"}, status_code=400)
            try:
                return await self._service.create_namespace(
                    name=name,
                    description=body.get("description", ""),
                )
            except ValueError as e:
                return JSONResponse({"error": str(e)}, status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        return app

    def get_app(self) -> FastAPI:
        return self._app

    async def serve(self) -> None:
        host, port = self._parse_addr()
        config = uvicorn.Config(
            self._app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._logger.info(f"Dashboard HTTP 服务器启动 addr={self._addr}")
        await self._server.serve()

    async def stop(self) -> None:
        if self._server:
            self._server.should_exit = True

    def _parse_addr(self):
        addr = self._addr
        if addr.startswith(":"):
            return "0.0.0.0", int(addr[1:])
        parts = addr.rsplit(":", 1)
        host = parts[0] or "0.0.0.0"
        port = int(parts[1]) if len(parts) > 1 else 8081
        return host, port


def _fallback_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html>
<head><title>AgentFlow Dashboard</title>
<style>body{font-family:sans-serif;margin:20px}h1{color:#333}.api-links a{display:block;margin:5px 0}</style>
</head>
<body>
<h1>🤖 AgentFlow v2 Dashboard</h1>
<p>Dashboard template not found. Use API endpoints:</p>
<div class="api-links">
<a href="/api/dashboard">/api/dashboard - Overview</a>
<a href="/api/tasks">/api/tasks - Task list</a>
<a href="/api/goals">/api/goals - Goal list</a>
<a href="/api/skills">/api/skills - Skills</a>
<a href="/api/health">/api/health - Health</a>
</div>
</body>
</html>"""
