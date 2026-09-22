"""Task Manager - 任务管理器"""
import os
import json
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from src.task.models import Task, TaskStatus, TaskType, TaskStep, CollaborationMode
from src.task.manager_agent import ManagerAgent
from src.task.audit import AuditLogger
from src.task.periodic_scheduler import preview_schedule, validate_schedule

logger = logging.getLogger(__name__)

#: 允许通过 `update_task` 直接改写的字段白名单（防越权改写 task_id/steps 等）
_UPDATABLE_FIELDS = {
    "topic", "title", "description", "schedule", "require_confirmation",
    "retry_config", "notification_config", "trigger_config", "progress",
    "current_step", "selected_agents", "collaboration_mode", "execution_mode",
}


class TaskManager:
    """任务管理器 - 负责任务的CRUD操作和增强功能"""
    
    def __init__(self, storage_dir: str = "data/tasks"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, Task] = {}
        self._task_index_file = self.storage_dir / "task_index.json"
        
        project_root = Path(__file__).resolve().parent.parent.parent
        self.manager_agent = ManagerAgent(project_root=project_root)
        
        logger.info(f"📂 任务存储目录: {self.storage_dir.absolute()}")
        self._load_index()
        
        task_count = len(self._tasks)
        if task_count > 0:
            logger.info(f"📊 已加载 {task_count} 个任务")
            status_count = {}
            for task in self._tasks.values():
                status = task.status.value if hasattr(task.status, 'value') else str(task.status)
                status_count[status] = status_count.get(status, 0) + 1
            logger.info(f"   📈 任务状态分布: {status_count}")
        else:
            logger.info("📊 当前无任务")
        
        logger.info("✅ TaskManager 初始化完成")
    
    def _load_index(self):
        """加载任务索引"""
        if self._task_index_file.exists():
            try:
                with open(self._task_index_file, 'r', encoding='utf-8') as f:
                    index = json.load(f)
                    for task_id, task_info in index.items():
                        task_file = self.storage_dir / f"{task_id}.json"
                        if task_file.exists():
                            try:
                                with open(task_file, 'r', encoding='utf-8') as tf:
                                    data = json.load(tf)
                                    task = Task.from_dict(data)
                                    self._tasks[task_id] = task
                            except Exception as e:
                                logger.warning(f"加载任务 {task_id} 失败: {e}")
                logger.info(f"✅ 已加载 {len(self._tasks)} 个任务索引")
            except Exception as e:
                logger.error(f"❌ 加载任务索引失败: {e}")
        else:
            logger.info("📋 任务索引文件不存在，将创建新索引")
    
    def _save_index(self):
        """保存任务索引"""
        try:
            index = {
                task_id: {
                    "topic": task.topic,
                    "title": task.title,
                    "task_type": task.task_type.value if hasattr(task.task_type, 'value') else str(task.task_type),
                    "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
                    "created_at": task.created_at.isoformat() if isinstance(task.created_at, datetime) else str(task.created_at),
                    "file": str(self.storage_dir / f"{task_id}.json")
                }
                for task_id, task in self._tasks.items()
            }
            with open(self._task_index_file, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存任务索引失败: {e}")
    
    def get_available_agents(self) -> List[Dict[str, Any]]:
        """返回当前所有可用的智能体列表（供前端手动指定/修改智能体时展示全部）"""
        available = []
        for agent_id, info in self.manager_agent.agent_capabilities.items():
            available.append({
                "agent_id": agent_id,
                "name": info.get("name", agent_id),
                "capabilities": info.get("capabilities", []),
                "description": info.get("description", ""),
                "agent_type": info.get("agent_type", "worker"),
                "icon": info.get("icon", "🤖"),
                "iconColor": info.get("iconColor", "#2196F3"),
                "bgColor": info.get("bgColor", "#E3F2FD"),
            })
        return available

    def create_task(
        self,
        topic: str,
        task_type: TaskType = TaskType.TEMPORARY,
        description: str = "",
        supervisor_agent_id: str = "supervisor_01",
        agent_group_config: Optional[Dict] = None,
        schedule: Optional[Dict] = None,
        execution_mode: str = "auto_select",
        require_confirmation: bool = True,
        collaboration_mode: Optional[str] = None,
        selected_agents: Optional[List[str]] = None,
        retry_config: Optional[Dict] = None,
        notification_config: Optional[Dict] = None,
        trigger_config: Optional[Dict] = None,
        parent_task_id: str = "",
    ) -> Dict[str, Any]:
        """创建新任务 - 让LLM决定执行模式"""
        task_id = f"task_{uuid.uuid4().hex[:12]}"

        # ★ 定时/周期任务的调度合法性校验（前端用时间选择器生成 cron 后由这里兜底拦截）：
        #   否则非法 cron 只会在 approve 注册作业时失败，任务却显示"已确认"——静默无排期
        if task_type in (TaskType.PERIODIC, TaskType.SCHEDULED) and schedule:
            _check = validate_schedule(schedule)
            if not _check["ok"]:
                raise ValueError(f"schedule 非法: {_check['error']}")
        
        manager_recommendation = None
        final_selected_agents = selected_agents or []
        recommended_mode = collaboration_mode or "sequential"
        
        if execution_mode in ["auto_select", "hybrid"]:
            recommendation = self.manager_agent.recommend_agents(
                description or topic,
                mode=execution_mode
            )
            manager_recommendation = recommendation
            
            recommended_mode = recommendation.get("recommended_collaboration_mode", "sequential")
            
            if execution_mode == "auto_select":
                final_selected_agents = [agent["agent_id"] for agent in recommendation["recommended_agents"]]
            
            logger.info(f"🤖 LLM 推荐执行模式: {recommended_mode}")
            logger.info(f"🤖 LLM 推荐智能体: {final_selected_agents}")
        
        task = Task(
            task_id=task_id,
            topic=topic,
            task_type=task_type,
            description=description,
            supervisor_agent_id=supervisor_agent_id,
            agent_group_config=agent_group_config or {},
            schedule=schedule,
            execution_mode=execution_mode,
            require_confirmation=require_confirmation,
            collaboration_mode=recommended_mode,
            selected_agents=final_selected_agents,
            manager_recommendation=manager_recommendation,
            retry_config=retry_config or {"max_attempts": 3, "backoff": "exponential"},
            notification_config=notification_config or {},
            trigger_config=trigger_config,
            parent_task_id=parent_task_id,
            status=TaskStatus.DRAFT if require_confirmation else TaskStatus.PENDING,
        )
        
        if final_selected_agents:
            task.steps = self._create_task_steps_with_mode(task.task_id, final_selected_agents, recommended_mode)
        
        self._tasks[task_id] = task
        self._save_task(task)
        self._save_index()
        
        logger.info(f"创建任务成功: {task_id} - {topic}")
        logger.info(f"   📋 智能体: {final_selected_agents}")
        logger.info(f"   📋 执行模式: {recommended_mode}")

        AuditLogger(task.task_id, storage_dir=str(self.storage_dir / "audit")).log(
            "create",
            details={
                "task_type": task.task_type.value,
                "status": task.status.value,
                "agents": final_selected_agents,
                "collaboration_mode": recommended_mode,
                "require_confirmation": require_confirmation,
            },
        )

        return {
            "task": task,
            "manager_recommendation": manager_recommendation,
            "available_agents": self.get_available_agents(),
            "approval_url": f"/api/v2/tasks/{task_id}/approve" if require_confirmation else None,
            # ★ 调度回显：前端创建即可展示"下次执行时间"，无需自己推算 cron
            "schedule": task.schedule,
            "schedule_preview": (
                preview_schedule(task.schedule)
                if task.task_type in (TaskType.PERIODIC, TaskType.SCHEDULED) and task.schedule
                else None
            ),
        }
    
    def _create_task_steps_with_mode(self, task_id: str, agent_ids: List[str], mode: str) -> List[TaskStep]:
        """根据执行模式创建任务步骤"""
        steps = []
        
        if mode == "sequential":
            for i, agent_id in enumerate(agent_ids):
                step = TaskStep(
                    task_id=task_id,
                    agent_id=agent_id,
                    step_order=i,
                    group=0,
                    step_name=f"步骤{i+1}: {agent_id}",
                    status="pending"
                )
                steps.append(step)
        
        elif mode == "parallel":
            for i, agent_id in enumerate(agent_ids):
                step = TaskStep(
                    task_id=task_id,
                    agent_id=agent_id,
                    step_order=i,
                    group=1,
                    step_name=f"并行-{i+1}: {agent_id}",
                    status="pending"
                )
                steps.append(step)
        
        elif mode == "hybrid":
            query_agents = []
            analysis_agents = []
            report_agents = []
            
            for agent_id in agent_ids:
                agent_info = self.manager_agent.agent_capabilities.get(agent_id, {})
                caps = agent_info.get("capabilities", [])
                caps_str = " ".join(caps).lower()
                
                if any(kw in caps_str for kw in ["查询", "获取", "采集", "请求"]):
                    query_agents.append(agent_id)
                elif any(kw in caps_str for kw in ["分析", "统计", "计算"]):
                    analysis_agents.append(agent_id)
                elif any(kw in caps_str for kw in ["报告", "生成", "撰写", "输出"]):
                    report_agents.append(agent_id)
                else:
                    analysis_agents.append(agent_id)
            
            group_id = 1
            step_order = 0
            
            for agent_id in query_agents:
                step = TaskStep(
                    task_id=task_id,
                    agent_id=agent_id,
                    step_order=step_order,
                    group=group_id,
                    step_name=f"查询-{agent_id}",
                    status="pending"
                )
                steps.append(step)
                step_order += 1
            
            if query_agents:
                group_id += 1
            
            for agent_id in analysis_agents:
                step = TaskStep(
                    task_id=task_id,
                    agent_id=agent_id,
                    step_order=step_order,
                    group=group_id,
                    step_name=f"分析-{agent_id}",
                    status="pending"
                )
                steps.append(step)
                step_order += 1
            
            if analysis_agents:
                group_id += 1
            
            for agent_id in report_agents:
                step = TaskStep(
                    task_id=task_id,
                    agent_id=agent_id,
                    step_order=step_order,
                    group=group_id,
                    step_name=f"报告-{agent_id}",
                    status="pending"
                )
                steps.append(step)
                step_order += 1
        
        return steps
    
    def _save_task(self, task: Task):
        """保存单个任务到文件"""
        task_file = self.storage_dir / f"{task.task_id}.json"
        try:
            with open(task_file, 'w', encoding='utf-8') as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存任务文件失败 {task.task_id}: {e}")
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        if task_id in self._tasks:
            return self._tasks[task_id]
        
        task_file = self.storage_dir / f"{task_id}.json"
        if task_file.exists():
            try:
                with open(task_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    task = Task.from_dict(data)
                    self._tasks[task_id] = task
                    return task
            except Exception as e:
                logger.error(f"加载任务失败 {task_id}: {e}")
        
        return None
    
    def list_tasks(
        self,
        task_type: Optional[TaskType] = None,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """列出任务"""
        # 防御性转换：确保 limit 和 offset 是整数
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            limit = 100
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            offset = 0

        tasks = list(self._tasks.values())
        
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        
        total = len(tasks)
        paginated = tasks[offset:offset + limit]
        
        return {
            "tasks": paginated,
            "count": total,
            "limit": limit,
            "offset": offset,
            "available_agents": self.get_available_agents()
        }
    
    def delete_task(self, task_id: str) -> bool:
        """删除任务（含定时作业注销 + 审计清理）"""
        if task_id not in self._tasks:
            # 兼容：索引缺失但文件存在时也允许删除
            task_file = self.storage_dir / f"{task_id}.json"
            if not task_file.exists():
                return False

        self._tasks.pop(task_id, None)

        task_file = self.storage_dir / f"{task_id}.json"
        if task_file.exists():
            try:
                task_file.unlink()
            except Exception as e:
                logger.warning(f"删除任务文件失败 {task_id}: {e}")

        # 联动注销定时作业（原先由 API 层调用，失败会误报删除失败）
        try:
            from src.task.periodic_scheduler import get_periodic_scheduler

            get_periodic_scheduler(str(self.storage_dir)).remove_job(task_id)
        except Exception as e:
            logger.warning(f"注销定时作业失败 {task_id}: {e}")

        try:
            AuditLogger(task_id, storage_dir=str(self.storage_dir / "audit")).clear()
        except Exception:
            pass

        self._save_index()
        logger.info(f"删除任务: {task_id}")
        return True
    
    def approve_task(self, task_id: str, approved: bool, approved_by: str = "system", modified_config: Optional[Dict] = None) -> Optional[Task]:
        """确认或拒绝任务

        `modified_config` 支持：
          - agents            改用这批智能体
          - collaboration_mode 改协作模式
          - schedule          改定时/周期（前端在"确认"弹窗里让用户直接填时间后提交）
        传入的 schedule 会先校验，非法直接抛 ValueError（任务保持 DRAFT，不会出现"确认成功但没排期"）。
        """
        task = self.get_task(task_id)
        if not task:
            return None
        
        if task.status != TaskStatus.DRAFT:
            logger.warning(f"任务状态不是DRAFT，当前状态: {task.status}")
            return task

        # ★ 校验待写入的调度配置（在校验失败时保持任务状态不变）
        _new_schedule = (modified_config or {}).get("schedule")
        if approved and _new_schedule is not None:
            _check = validate_schedule(_new_schedule)
            if not _check["ok"]:
                raise ValueError(f"schedule 非法: {_check['error']}")

        if approved:
            if modified_config:
                if _new_schedule is not None:
                    task.schedule = _new_schedule
                if "agents" in modified_config:
                    task.selected_agents = modified_config["agents"]
                    mode = task.collaboration_mode.value if hasattr(task.collaboration_mode, 'value') else str(task.collaboration_mode)
                    task.steps = self._create_task_steps_with_mode(task.task_id, modified_config["agents"], mode)
                if "collaboration_mode" in modified_config:
                    task.collaboration_mode = CollaborationMode(modified_config["collaboration_mode"])
                    task.steps = self._create_task_steps_with_mode(
                        task.task_id, 
                        task.selected_agents, 
                        modified_config["collaboration_mode"]
                    )
            
            task.status = TaskStatus.PENDING
            task.approved_by = approved_by
            task.approved_at = datetime.now()
            logger.info(f"任务已确认: {task_id}")
        else:
            task.status = TaskStatus.CANCELLED
            logger.info(f"任务已拒绝: {task_id}")
        
        
        # ===== 定时/周期任务：注册到真实调度器（cron 或固定间隔）=====
        if approved and task.task_type.value in ("periodic", "scheduled") and task.schedule:
            try:
                from src.task.periodic_scheduler import get_periodic_scheduler

                scheduler = get_periodic_scheduler(str(self.storage_dir))
                scheduler.register_callback(
                    task.task_id,
                    lambda tid, args: self._execute_scheduled_task(tid, args),
                )
                timezone = task.schedule.get("timezone", "Asia/Shanghai")
                args = {"task_data": task.schedule}
                if task.schedule.get("cron"):
                    ok = scheduler.add_cron_job(
                        task_id=task.task_id,
                        cron=task.schedule["cron"],
                        timezone=timezone,
                        args=args,
                        name=task.topic,
                    )
                elif task.schedule.get("interval_seconds"):
                    ok = scheduler.add_interval_job(
                        task_id=task.task_id,
                        interval_seconds=task.schedule["interval_seconds"],
                        timezone=timezone,
                        args=args,
                        name=task.topic,
                    )
                else:
                    ok = False
                    logger.warning(f"⚠️ schedule 缺少 cron/interval_seconds: {task.task_id}")
                if not ok:
                    _why = validate_schedule(task.schedule).get("error", "")
                    logger.warning(f"⚠️ 定时任务注册失败: {task.task_id} {_why}")
            except Exception as e:
                logger.error(f"❌ 注册定时任务失败: {e}")
        elif approved and task.task_type.value in ("periodic", "scheduled"):
            logger.warning(
                f"⚠️ 定时/周期任务缺少 schedule，未排期: {task.task_id}"
                "（schedule 需含 cron 或 interval_seconds）"
            )
        # ==================================================

        try:
            AuditLogger(task.task_id, storage_dir=str(self.storage_dir / "audit")).log(
                "approve" if approved else "reject",
                agent=approved_by,
                details={"status": task.status.value, "modified": bool(modified_config)},
            )
        except Exception:
            pass

        self._save_task(task)
        self._save_index()
        return task

    def get_schedule_status(self, task_id: str) -> Dict[str, Any]:
        """定时/周期任务的排期状态（前端在"确认/暂停/恢复"后回显用）。

        Returns:
            {
              "is_scheduled": bool,     # 是否定时/周期类型
              "registered": bool,       # 是否已在调度器中排期
              "next_run": str | None,   # 下次执行时间（ISO8601，含时区）
              "run_count": int,         # 已执行次数
              "last_error": str,        # 上次执行错误
              "error": str,             # 未排期的原因（给用户看）
            }

        用途：避免"任务显示已确认，但实际没有排期"这种静默状态——
        前端拿到 registered=False 就应提示用户补齐时间规则。
        """
        info: Dict[str, Any] = {
            "is_scheduled": False, "registered": False, "next_run": None,
            "run_count": 0, "last_error": "", "error": "",
        }
        task = self.get_task(task_id)
        if not task:
            info["error"] = f"任务不存在: {task_id}"
            return info
        if task.task_type.value not in ("periodic", "scheduled"):
            return info
        info["is_scheduled"] = True

        check = validate_schedule(task.schedule)
        if not check["ok"]:
            info["error"] = f"调度配置缺失或非法：{check['error']}"
            return info
        try:
            from src.task.periodic_scheduler import get_periodic_scheduler

            job = get_periodic_scheduler(str(self.storage_dir)).get_job(task_id)
        except Exception as e:  # noqa: BLE001
            info["error"] = f"查询调度器失败: {e}"
            return info
        if not job:
            info["error"] = "尚未排期：请确认任务（approve）后生效"
            return info
        info.update({
            "registered": bool(job.enabled),
            "next_run": job.next_run or None,
            "run_count": job.run_count,
            "last_error": job.last_error or "",
        })
        if not job.enabled:
            info["error"] = "任务已暂停（paused）"
        return info

    def update_task_agents(self, task_id: str, agent_ids: List[str], mode: Optional[str] = None) -> Optional[Task]:
        """更新任务的智能体列表和执行模式"""
        task = self.get_task(task_id)
        if not task:
            return None
        
        if task.status not in [TaskStatus.DRAFT, TaskStatus.PENDING]:
            logger.warning(f"任务状态为 {task.status}，不能修改智能体")
            return task
        
        task.selected_agents = agent_ids
        
        if mode:
            final_mode = mode
        else:
            recommendation = self.manager_agent.recommend_agents(task.description or task.topic)
            final_mode = recommendation.get("recommended_collaboration_mode", "sequential")
            logger.info(f"🤖 Manager 推荐执行模式: {final_mode}")
        
        task.collaboration_mode = CollaborationMode(final_mode)
        task.steps = self._create_task_steps_with_mode(task.task_id, agent_ids, final_mode)
        
        if task.status == TaskStatus.PENDING:
            task.status = TaskStatus.DRAFT
            task.approved_by = ""
            task.approved_at = None
            logger.info(f"任务配置已修改，状态重置为 DRAFT: {task_id}")
        
        task.updated_at = datetime.now()
        self._save_task(task)
        self._save_index()
        
        logger.info(f"更新任务智能体: {task_id}")
        logger.info(f"   📋 新智能体: {agent_ids}")
        logger.info(f"   📋 新模式: {final_mode}")
        
        return task
    
    def update_task_progress(self, task_id: str, progress: int, current_step: str = "", status: Optional[TaskStatus] = None) -> Optional[Task]:
        """更新任务进度"""
        task = self.get_task(task_id)
        if not task:
            return None
        
        task.progress = progress
        if current_step:
            task.current_step = current_step
        if status:
            task.status = status
        
        task.updated_at = datetime.now()
        self._save_task(task)
        return task
    
    def update_task_step(self, task_id: str, step_index: int, status: str, output_data: Optional[Dict] = None, logs: str = "") -> Optional[Task]:
        """更新任务步骤状态"""
        task = self.get_task(task_id)
        if not task or not task.steps or step_index >= len(task.steps):
            return None
        
        step = task.steps[step_index]
        step.status = status
        if output_data:
            step.output_data = output_data
        if logs:
            step.logs = logs
        
        if status == "running":
            step.started_at = datetime.now()
        elif status in ["completed", "failed"]:
            step.completed_at = datetime.now()
        
        self._save_task(task)
        return task
    
    def preview_recommendation(self, description: str, mode: str = "auto_select") -> Dict[str, Any]:
        """预览Manager推荐（不创建任务）"""
        return self.manager_agent.recommend_agents(description, mode)
    
    def get_task_progress(self, task_id: str) -> Optional[Dict]:
        """获取任务进度"""
        task = self.get_task(task_id)
        if not task:
            return None
        
        step_progress = []
        for step in task.steps:
            step_progress.append({
                "step_id": step.step_id,
                "agent_id": step.agent_id,
                "status": step.status.value if hasattr(step.status, 'value') else str(step.status),
                "started_at": step.started_at.isoformat() if isinstance(step.started_at, datetime) else None,
                "completed_at": step.completed_at.isoformat() if isinstance(step.completed_at, datetime) else None,
                "logs": step.logs[:200] if step.logs else ""
            })
        
        return {
            "task_id": task_id,
            "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
            "progress": task.progress,
            "current_step": task.current_step,
            "total_steps": len(task.steps),
            "steps": step_progress,
            "started_at": task.started_at.isoformat() if isinstance(task.started_at, datetime) else None,
            "updated_at": task.updated_at.isoformat() if isinstance(task.updated_at, datetime) else None,
        }
    
    async def start(self):
        """启动任务管理器"""
        logger.info("TaskManager 已启动")
    
    async def stop(self):
        """停止任务管理器"""
        logger.info("TaskManager 已停止")
        self._save_index()


    def _execute_scheduled_task(self, task_id: str, args: dict):
        """定时任务执行回调"""
        try:
            logger.info(f"🔄 定时任务触发: {task_id}")
            
            task = self.get_task(task_id)
            if not task:
                logger.error(f"❌ 定时任务不存在: {task_id}")
                return
            
            from src.task.executor import TaskExecutor
            executor = TaskExecutor(self)
            asyncio.create_task(executor.execute_task(task_id, args))
            
        except Exception as e:
            logger.error(f"❌ 定时任务执行异常: {e}")
            import traceback
            traceback.print_exc()

    # ================================================================
    # 状态机 / 字段更新 / 类型转化 / 统计（补齐 V2 接口依赖的能力）
    # ================================================================

    def update_task_status(self, task_id: str, status, **kwargs) -> Optional[Task]:
        """仅更新状态（及可选 progress/current_step/error_message）。

        兼容 `status` 传入 TaskStatus 或字符串。
        """
        task = self.get_task(task_id)
        if not task:
            return None
        if isinstance(status, str):
            try:
                status = TaskStatus(status)
            except ValueError:
                logger.warning(f"未知任务状态: {status}")
                return task
        task.status = status
        for field_name in ("progress", "current_step", "error_message", "result"):
            if field_name in kwargs and kwargs[field_name] is not None:
                setattr(task, field_name, kwargs[field_name])
        if status == TaskStatus.RUNNING and not task.started_at:
            task.started_at = datetime.now()
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            task.completed_at = datetime.now()
        task.updated_at = datetime.now()
        self._save_task(task)
        self._save_index()
        return task

    def update_task(self, task_id: str, updates: Dict[str, Any]) -> Optional[Task]:
        """按字段白名单更新任务（区别于 convert_task：不新建任务）。"""
        task = self.get_task(task_id)
        if not task or not isinstance(updates, dict):
            return None
        applied = {}
        for key, value in updates.items():
            if key not in _UPDATABLE_FIELDS:
                continue
            if key == "collaboration_mode" and isinstance(value, str):
                try:
                    value = CollaborationMode(value)
                except ValueError:
                    continue
            if key == "selected_agents" and isinstance(value, list):
                task.steps = self._create_task_steps_with_mode(
                    task.task_id, value, task.collaboration_mode.value
                )
            setattr(task, key, value)
            applied[key] = value if not hasattr(value, "value") else value.value
        task.updated_at = datetime.now()
        self._save_task(task)
        self._save_index()
        AuditLogger(task_id, storage_dir=str(self.storage_dir / "audit")).log(
            "update", details={"fields": list(applied.keys())}
        )
        return task

    def convert_task(self, task_id: str, target_type, schedule: Optional[Dict] = None) -> Optional[Task]:
        """任务类型转化：原任务置 CONVERTED，新建同内容的目标类型任务并返回新任务。"""
        task = self.get_task(task_id)
        if not task:
            return None
        if isinstance(target_type, str):
            try:
                target_type = TaskType(target_type)
            except ValueError:
                logger.warning(f"未知任务类型: {target_type}")
                return None
        if task.task_type == target_type:
            logger.info(f"任务类型相同，跳过转化: {task_id}")
            return task

        result = self.create_task(
            topic=task.topic,
            task_type=target_type,
            description=task.description,
            supervisor_agent_id=task.supervisor_agent_id,
            agent_group_config=task.agent_group_config,
            schedule=schedule or (task.schedule if target_type in (TaskType.PERIODIC, TaskType.SCHEDULED) else None),
            execution_mode=task.execution_mode,
            require_confirmation=task.require_confirmation,
            collaboration_mode=task.collaboration_mode.value if hasattr(task.collaboration_mode, "value") else None,
            selected_agents=task.selected_agents,
            retry_config=task.retry_config,
            notification_config=task.notification_config,
            trigger_config=task.trigger_config,
            parent_task_id=task_id,
        )
        new_task = result["task"]

        task.status = TaskStatus.CONVERTED
        task.updated_at = datetime.now()
        self._save_task(task)
        self._save_index()

        AuditLogger(task_id, storage_dir=str(self.storage_dir / "audit")).log(
            "convert", details={"target_type": target_type.value, "new_task_id": new_task.task_id}
        )
        logger.info(f"🔄 任务转化: {task_id} -> {new_task.task_id} ({target_type.value})")
        return new_task

    def get_stats(self) -> Dict[str, Any]:
        """任务统计（供 dashboard / stats 接口）。"""
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for task in self._tasks.values():
            status = task.status.value if hasattr(task.status, "value") else str(task.status)
            task_type = task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type)
            by_status[status] = by_status.get(status, 0) + 1
            by_type[task_type] = by_type.get(task_type, 0) + 1
        return {
            "total": len(self._tasks),
            "by_status": by_status,
            "by_type": by_type,
            "running": by_status.get(TaskStatus.RUNNING.value, 0),
            "pending": by_status.get(TaskStatus.PENDING.value, 0) + by_status.get(TaskStatus.DRAFT.value, 0),
            "completed": by_status.get(TaskStatus.COMPLETED.value, 0),
            "failed": by_status.get(TaskStatus.FAILED.value, 0),
        }


_instance: Optional[TaskManager] = None


def get_task_manager(storage_dir: str = "data/tasks") -> TaskManager:
    """获取全局唯一的 TaskManager（网关与任务 API 共用，避免各自 new 一份）。

    历史问题：`src/task/api_routes.py` 每个请求 `TaskManager()` 新建实例，
    每次都重读 task_index.json 与全部任务文件，且内存态与网关单例不一致。
    """
    global _instance
    if _instance is None:
        _instance = TaskManager(storage_dir=storage_dir)
    return _instance


def reset_task_manager() -> None:
    """重置单例（仅供测试使用）。"""
    global _instance
    _instance = None