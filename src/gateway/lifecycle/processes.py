"""子进程与健康巡检域（Process Lifecycle Domain）

从 `grpc_server.GatewayV2GRPC` 按域拆出的 Mixin，负责智能体子进程的
自动拉起、停止与后台巡检循环：

    自动拉起    _auto_start_worker_agents / _auto_start_manager_agent
    进程控制    _start_agent_process / _stop_agent_process
    健康巡检    _manager_health_check_loop / _worker_health_check_loop
                _scan_orphan_zk_agents / _files_orphan_cleanup_loop

依赖单向：本模块不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 项目根目录（src/gateway/lifecycle/processes.py → 上溯 3 层）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)


class ProcessLifecycleMixin:
    """子进程与健康巡检域（方法实现逐字自 grpc_server 迁出）"""


    async def _auto_start_worker_agents(self) -> None:
        """自动扫描启动 agents/ 目录下所有 worker 类型的智能体"""
        try:
            agents_base = PROJECT_ROOT / "agents"
            if not agents_base.exists():
                logger.warning(f"⚠️ agents 目录不存在: {agents_base}")
                return

            started_count = 0
            for agent_dir in agents_base.iterdir():
                if not agent_dir.is_dir():
                    continue
                # 跳过 manager_agent（由 dfecrab start 单独启动）
                if agent_dir.name == "manager_agent":
                    continue

                config_path = agent_dir / "config.json"
                if not config_path.exists():
                    logger.debug(f"   ℹ️ 跳过 {agent_dir.name}: 无 config.json")
                    continue

                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except Exception as e:
                    logger.warning(f"   ⚠️ 读取 {agent_dir.name}/config.json 失败: {e}")
                    continue

                agent_id = config.get("agent_id") or agent_dir.name
                agent_type = config.get("agent_type", "worker")

                # 只跳过 manager 类型（由 dfecrab start 单独启动）
                if agent_type == "manager":
                    logger.info(f"   ℹ️ 跳过 {agent_id}: manager 类型")
                    continue

                # 检查是否已在运行
                if agent_id in self._agent_processes:
                    proc = self._agent_processes[agent_id]
                    if proc.poll() is None:
                        logger.info(f"   ℹ️ {agent_id} 已在运行 (PID: {proc.pid})，跳过")
                        continue
                    else:
                        logger.warning(f"   ⚠️ {agent_id} 旧进程已退出，重新启动")
                        del self._agent_processes[agent_id]

                logger.info(f"🤖 自动启动 worker 智能体: {agent_id}")
                proc = await self._start_agent_process(agent_id)
                if proc:
                    started_count += 1
                    logger.info(f"   ✅ {agent_id} 已启动 (PID: {proc.pid})")
                else:
                    logger.warning(f"   ⚠️ {agent_id} 启动失败")

            logger.info(f"✅ 自动启动 worker 智能体完成，共启动 {started_count} 个")
        except Exception as e:
            logger.error(f"❌ 自动启动 worker 智能体失败: {e}")

    async def _auto_start_manager_agent(self) -> None:
        """自动启动 Manager Agent 进程"""
        try:
            # 先检查是否已在运行（通过 ZK 检测）
            if self._zk_discovery:
                instances = self._zk_discovery.discover_service("manager_agent")
                if instances:
                    logger.info("✅ Manager Agent 已在 Zookeeper 中注册，跳过自动启动")
                    # 启动健康检查循环
                    asyncio.ensure_future(self._manager_health_check_loop())
                    return

            # 启动 Manager 进程
            logger.info("🚀 自动启动 Manager Agent...")
            proc = await self._start_agent_process("manager_agent")
            if proc:
                logger.info(f"✅ Manager Agent 已启动 (PID: {proc.pid})")
                # 等待 Manager 在 ZK 中注册
                await asyncio.sleep(5)
                # 启动健康检查循环
                asyncio.ensure_future(self._manager_health_check_loop())
            else:
                logger.error("❌ Manager Agent 启动失败")
        except Exception as e:
            logger.error(f"❌ 自动启动 Manager Agent 异常: {e}")

    async def _manager_health_check_loop(self):
        """定时检查 Manager Agent 是否存活，发现宕机自动重启"""
        while self._running:
            try:
                # 检查进程是否存活
                if "manager_agent" in self._agent_processes:
                    proc = self._agent_processes["manager_agent"]
                    if proc.poll() is not None:
                        logger.warning(f"⚠️ Manager Agent 进程已退出 (code: {proc.returncode})，尝试重启...")
                        del self._agent_processes["manager_agent"]
                        proc = await self._start_agent_process("manager_agent")
                        if proc:
                            logger.info(f"✅ Manager Agent 已自动重启 (PID: {proc.pid})")
                        else:
                            logger.error("❌ Manager Agent 重启失败")
                else:
                    # 进程记录不存在，尝试启动
                    logger.warning("⚠️ Manager Agent 进程不存在，尝试启动...")
                    proc = await self._start_agent_process("manager_agent")
                    if proc:
                        logger.info(f"✅ Manager Agent 已启动 (PID: {proc.pid})")
                
                # 通过 ZK 检查服务是否注册成功
                if self._zk_discovery:
                    instances = self._zk_discovery.discover_service("manager_agent")
                    if not instances:
                        logger.warning("⚠️ Manager Agent 未在 Zookeeper 中注册")
                    
            except Exception as e:
                logger.error(f"❌ Manager 健康检查异常: {e}")
            await asyncio.sleep(30)  # 每30秒检查一次

    async def _scan_orphan_zk_agents(self) -> None:
        """扫描 ZK 中本地 agents/ 目录不存在的 Agent 注册，打警告日志

        用于发现残留进程 / 僵尸 ZK 节点（如 agent_id=default 的孤儿注册），
        便于运维及时清理。
        """
        if not self._zk_discovery:
            return
        try:
            agents_base = PROJECT_ROOT / "agents"
            local_ids = set()
            if agents_base.exists():
                local_ids = {
                    d.name for d in agents_base.iterdir()
                    if d.is_dir() and (d / "config.json").exists()
                }

            for service_type in ("worker_agent", "manager_agent", "default_agent"):
                for inst in (self._zk_discovery.discover_service(service_type) or []):
                    agent_id = self._zk_instance_agent_id(inst)
                    if agent_id == "manager_agent" or agent_id in local_ids:
                        continue
                    logger.warning(
                        f"⚠️ [ZK] 孤儿注册: agent_id={agent_id}, "
                        f"service_id={inst.get('service_id')}, "
                        f"addr={inst.get('host')}:{inst.get('port')}, "
                        f"registered_at={inst.get('registered_at')}"
                    )
        except Exception as e:
            logger.error(f"❌ 扫描 ZK 孤儿注册失败: {e}")

    async def _worker_health_check_loop(self):
        """每隔 30 秒检查所有 worker 进程，发现宕机或 ZK 注册丢失就重启"""
        while self._running:
            try:
                agents_base = PROJECT_ROOT / "agents"
                if not agents_base.exists():
                    await asyncio.sleep(30)
                    continue

                for agent_dir in agents_base.iterdir():
                    if not agent_dir.is_dir():
                        continue
                    if agent_dir.name == "manager_agent":
                        continue

                    config_path = agent_dir / "config.json"
                    if not config_path.exists():
                        continue

                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                    except Exception:
                        continue

                    agent_id = config.get("agent_id") or agent_dir.name
                    agent_type = config.get("agent_type", "worker")

                    # 跳过 manager 类型（由 _manager_health_check_loop 负责）
                    if agent_type == "manager":
                        continue

                    # 检查 ZK 中是否有注册（★ 步骤4：注册端统一 worker_agent；default_agent 仅兼容旧节点）
                    registered = False
                    if self._zk_discovery:
                        for _st in ("worker_agent", "default_agent"):
                            for inst in (self._zk_discovery.discover_service(_st) or []):
                                if self._zk_instance_agent_id(inst) == agent_id:
                                    registered = True
                                    break
                            if registered:
                                break

                    need_restart = False

                    # 检查进程是否存活
                    proc = self._agent_processes.get(agent_id)
                    if proc:
                        if proc.poll() is not None:
                            logger.warning(
                                f"⚠️ Worker [{agent_id}] 进程已退出 (code: {proc.returncode})"
                            )
                            del self._agent_processes[agent_id]
                            need_restart = True
                    else:
                        # 进程记录不存在，若 ZK 也无注册 → 需要启动
                        if not registered:
                            need_restart = True

                    # ZK 注册丢失但进程活着 → 可能是 ZK session 过期，重启进程以重建 ZK session
                    if proc and proc.poll() is None and not registered:
                        logger.warning(
                            f"⚠️ Worker [{agent_id}] 进程存活但 ZK 注册丢失，重启以重建 ZK session"
                        )
                        await self._stop_agent_process(agent_id)
                        need_restart = True

                    if need_restart:
                        logger.info(f"🔄 自动重启 worker [{agent_id}]...")
                        await self._start_agent_process(agent_id)

            except Exception as e:
                logger.error(f"❌ Worker 健康检查异常: {e}")
                import traceback
                traceback.print_exc()

            await asyncio.sleep(30)

    async def _files_orphan_cleanup_loop(self) -> None:
        """孤儿附件周期清理（批次12步骤3）

        按 file_upload.cleanup_interval_s 周期调用 registry.cleanup_orphans，
        回收：status=deleted 记录、超 TTL 记录、注册表无记录的落盘文件。
        默认 1 小时扫一次、TTL 30 天；仅处理孤儿，不影响 active 附件。
        """
        try:
            from src.config.app_config import section as _cfg_section
            _fu = _cfg_section("file_upload") or {}
        except Exception:
            _fu = {}
        try:
            _interval = float(_fu.get("cleanup_interval_s", 3600) or 3600)
        except Exception:
            _interval = 3600.0
        while self._running:
            try:
                await asyncio.sleep(_interval)
                if not self._running:
                    break
                from src.files.registry import cleanup_orphans
                _ttl = int(_fu.get("cleanup_ttl_days", 30) or 30)
                _res = cleanup_orphans(ttl_days=_ttl)
                if _res.get("removed_records") or _res.get("removed_files"):
                    logger.info(
                        f"[Files] 孤儿附件清理: records={_res.get('removed_records', 0)}, "
                        f"files={_res.get('removed_files', 0)} (ttl={_ttl}d)"
                    )
                else:
                    logger.debug(
                        f"[Files] 孤儿附件清理: 无孤儿（ttl={_ttl}d）"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[Files] 孤儿附件清理异常（下轮重试）: {e}")

    async def _start_agent_process(self, agent_id: str) -> Optional[subprocess.Popen]:
        """启动 Agent 的 gRPC 服务进程

        Args:
            agent_id: 智能体ID
            
        Returns:
            subprocess.Popen 对象，启动失败返回 None
        """
        if agent_id in self._agent_processes:
            proc = self._agent_processes[agent_id]
            if proc.poll() is None:
                logger.info(f"   ℹ️ Agent [{agent_id}] 进程已在运行 (PID: {proc.pid})")
                return proc
            else:
                # 进程已退出，清理旧记录
                logger.warning(f"   ⚠️ Agent [{agent_id}] 旧进程已退出 (code: {proc.returncode}), 重新启动")
                del self._agent_processes[agent_id]

        if agent_id == "manager_agent":
            agent_service_script = PROJECT_ROOT / "services" / "manager_agent" / "manager_agent_grpc.py"
        else:
            agent_service_script = PROJECT_ROOT / "services" / "agent_service" / "agent_service_grpc.py"
        if not agent_service_script.exists():
            logger.error(f"   ❌ Agent 服务脚本不存在: {agent_service_script}")
            return None

        python_exec = sys.executable

        try:
            cmd = [
                python_exec,
                str(agent_service_script),
                "--zk-hosts", self.zk_hosts,
            ]
            if agent_id != "manager_agent":
                cmd.extend(["--agent-id", agent_id])

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._agent_processes[agent_id] = proc
            logger.info(f"   🚀 Agent [{agent_id}] 进程已启动 (PID: {proc.pid})")
            return proc
        except Exception as e:
            logger.error(f"   ❌ Agent [{agent_id}] 进程启动失败: {e}")
            return None

    async def _stop_agent_process(self, agent_id: str) -> bool:
        """停止 Agent 的 gRPC 服务进程"""
        if agent_id not in self._agent_processes:
            return False

        proc = self._agent_processes.pop(agent_id)
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"   ⚠️ Agent [{agent_id}] 进程未响应终止信号，强制杀死")
                    proc.kill()
                    proc.wait(timeout=3)
                logger.info(f"   ✅ Agent [{agent_id}] 进程已停止 (PID: {proc.pid})")
            except Exception as e:
                logger.error(f"   ❌ Agent [{agent_id}] 进程停止失败: {e}")
                return False
        return True

    async def _handle_delete_agent(self, request, **kwargs) -> Dict[str, Any]:
        """删除智能体（删除 agents/ 目录 + 停止进程）"""
        try:
            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            # ── 先停止进程 ──
            process_stopped = await self._stop_agent_process(agent_id)
            if process_stopped:
                logger.info(f"   ✅ Agent [{agent_id}] 进程已停止")

            agents_base = PROJECT_ROOT / "agents"
            agent_dir = agents_base / agent_id

            if not agent_dir.exists():
                return {"success": False, "error": f"Agent {agent_id} 不存在"}

            import shutil
            shutil.rmtree(agent_dir)

            # 清理 agents_index.json 中对应项
            try:
                index_file = PROJECT_ROOT / "config" / "agents_index.json"
                if index_file.exists():
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_data = json.load(f)
                    if agent_id in index_data.get("agents", {}):
                        del index_data["agents"][agent_id]
                        with open(index_file, 'w', encoding='utf-8') as f:
                            json.dump(index_data, f, ensure_ascii=False, indent=2)
                        logger.info(f"✅ [Index] agents_index.json 已清理: {agent_id}")
            except Exception as e:
                logger.warning(f"⚠️ 清理 agents_index.json 失败: {e}")

            # ★ 删除的是平台默认助手时回退兜底 agent（修复：原逻辑误缩进在 except 内，正常路径永不执行）
            try:
                if agent_id == self._default_agent_id():
                    fallback = self._fallback_default_agent(exclude=agent_id)
                    self._persist_default_agent(fallback)
                    logger.info(f"✅ 默认助手 [{agent_id}] 已删除，平台默认回退 {fallback}")
            except Exception as e:
                logger.warning(f"⚠️ 清理平台默认助手失败: {e}")

            logger.info(f"✅ Agent {agent_id} 删除成功")
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存
            self._agents_list_cache = None
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
