"""
Agent Service - gRPC版本（随机端口）

每个智能体运行在独立的进程中，通过gRPC提供服务。
启动时自动分配随机可用端口，并注册到Zookeeper。

使用方式:
    python3 agent_service_grpc.py --agent-id analyst_agent --zk-hosts 127.0.0.1:2181
"""

import argparse
import json
import logging
import re
import socket
import threading
from decimal import Decimal
import sys
import time
from concurrent import futures
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

# 添加项目路径（必须放在所有项目导入之前）
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "core" / "grpc"))
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 自定义日志处理器（在路径设置后导入）
from src.utils.log_handler import DailyTrimmedFileHandler

import grpc
import httpx
import requests


from src.gateway.grpc import dfecrab_pb2
from src.gateway.grpc import dfecrab_pb2_grpc
from src.gateway.grpc.zk_registry import ZKServiceRegistry
from src.gateway.grpc.port_allocator import get_available_port, release_port
from src.memory.long_term import MemoryManager

# SQL 字段校验模块（添加 services 目录到路径）
sys.path.insert(0, str(PROJECT_ROOT / "services" / "agent_service"))
try:
    from validate_sql_fields import validate_sql
except ImportError:
    validate_sql = None
    logging.warning("⚠️ 无法导入 validate_sql_fields 模块")

# 时间解析模块
from src.utils.time_parser import parse_time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        DailyTrimmedFileHandler(LOG_DIR / "worker_agents.log", keep_days=7, encoding='utf-8')
    ]
)

# ✅ 降低第三方库日志级别，避免污染业务日志
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("kazoo").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)





class AgentServiceImpl(dfecrab_pb2_grpc.AgentServiceServicer):
    """Agent gRPC服务实现"""
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.agent_dir = PROJECT_ROOT / "agents" / agent_id

        # 记忆管理器（每个Worker独立记忆；按用户懒初始化，见 _get_memory_mgr）
        self.memory_mgr = MemoryManager(agent_id=agent_id)
        self._memory_mgrs: Dict[str, MemoryManager] = {}

        # Session历史（兼容性保留，实际使用memory_mgr的短期记忆）
        self.session_history: Dict[str, Dict] = {}
        self._max_session_history: int = 500  # 最大 session 数，超出后 LRU 淘汰
        self._session_last_access: Dict[str, float] = {}  # session 最后访问时间

        # 加载配置（快速加载，不等待模型检查）
        self.config = self._load_config()
        self.tools = self._load_tools()
        self.llm_config = {}  # 先置空，后台异步加载

        logger.info(f"🤖 Agent Service初始化完成: {agent_id}")
        logger.info(f"💾 记忆管理器已初始化（短期+长期+全局共享）")
        
        # 后台异步加载模型配置（不阻塞启动）
        threading.Thread(target=self._async_load_llm_config, daemon=True).start()
        logger.info(f"🔄 模型配置将在后台异步加载...")

    def _get_memory_mgr(self, user_id: str = None) -> MemoryManager:
        """按用户获取记忆管理器（user_id 为空时使用系统级默认路径）"""
        key = user_id or "__system__"
        if key not in self._memory_mgrs:
            self._memory_mgrs[key] = MemoryManager(agent_id=self.agent_id, user_id=user_id or None)
        return self._memory_mgrs[key]
        



    
    def _load_config(self) -> Dict:
        """加载配置"""
        config_file = self.agent_dir / "config.json"
        if config_file.exists():
            with open(config_file, 'r') as f:
                return json.load(f)
        # ── 分支13: 重过载 ──
        if category == 13:
            result_str = str(data.get("result", ""))
            if result_str and result_str not in ("None", ""):
                answer_final = result_str
            else:
                answer_final = "重过载数据查询完成"
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": answer_final,
                    "DataType": "CHAT"
                }
            }

        return {"agent_id": self.agent_id}
    
    def _load_tools(self) -> Dict:
        """加载工具"""
        tools_file = self.agent_dir / "tools.json"
        if tools_file.exists():
            with open(tools_file, 'r') as f:
                return json.load(f)
        return {"enabled_skills": []}

    def _async_load_llm_config(self):
        """后台异步加载模型配置（不阻塞启动）"""
        try:
            logger.info(f"🔄 [{self.agent_id}] 开始后台加载模型配置...")
            self.llm_config = self._load_llm_config()
            if self.llm_config:
                logger.info(f"✅ [{self.agent_id}] 模型配置加载完成: {self.llm_config.get('model_name', 'unknown')}")
            else:
                logger.warning(f"⚠️ [{self.agent_id}] 模型配置加载失败，请求时将重试")
        except Exception as e:
            logger.error(f"❌ [{self.agent_id}] 模型配置加载异常: {e}")

    def _load_llm_config(self) -> Dict:
        """加载 LLM 配置：优先 agent 指定模型 → 探活 → fallback chain"""
        from src.services.model_manager import model_manager
        
        # 第1步：读 agent config.json 的 model_config，默认 qwen3
        preferred_model = self.config.get("model_config", "qwen3")
        logger.info(f"🔍 [{self.agent_id}] 优先使用模型: {preferred_model}")
        
        # 第2步：在 model_providers 中查找并探活
        provider_cfg = model_manager.get_provider_config(preferred_model)
        if provider_cfg and provider_cfg.get("enabled", False):
            if model_manager._check_alive(provider_cfg, verify_content=True):
                logger.info(f"✅ [{self.agent_id}] 指定模型 {preferred_model} 存活，使用")
                return {
                    "api_base": provider_cfg.get("api_base", ""),
                    "model_name": provider_cfg.get("model_name", ""),
                    "timeout": provider_cfg.get("timeout", 120),
                    "api_key": provider_cfg.get("api_key", "not-needed")
                }
            else:
                logger.warning(f"⚠️ [{self.agent_id}] 指定模型 {preferred_model} 探活失败，进入 fallback")
        else:
            logger.info(f"ℹ️ [{self.agent_id}] 指定模型 {preferred_model} 未在 model_providers 中找到，进入 fallback")
        
        # 第3步：fallback — 按 fallback chain 依次探活
        alive_configs = model_manager.get_all_alive_configs()
        if alive_configs:
            fallback = alive_configs[0]
            logger.info(f"✅ [{self.agent_id}] 降级使用模型: {fallback.get('name', 'unknown')}")
            return {
                "api_base": fallback.get("api_base", ""),
                "model_name": fallback.get("model_name", ""),
                "timeout": fallback.get("timeout", 120),
                "api_key": fallback.get("api_key", "not-needed")
            }
        
        # 全不可用
        logger.error(f"❌ [{self.agent_id}] 所有模型均不可用")
        return {}

    async def _call_llm_async(self, prompt: str, system_prompt: str = "", max_tokens: int = None,
                              response_format: dict = None) -> str:
        """
        调用 LLM API（异步版本）
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            max_tokens: 最大输出 token 数（None=使用默认4096）
            response_format: 输出格式，如 {"type": "json_object"}，None=不约束
            
        Returns:
            LLM 响应文本
        """
        # 懒加载：如果模型配置还没加载完，同步加载
        if not self.llm_config.get("api_base"):
            logger.info(f"🔄 [{self.agent_id}] 模型配置未就绪，同步加载...")
            self.llm_config = self._load_llm_config()
            if not self.llm_config.get("api_base"):
                logger.warning(f"⚠️ [{self.agent_id}] LLM API not configured")
                return None
        
        api_base = self.llm_config["api_base"]
        model_name = self.llm_config.get("model_name", "default")
        timeout = self.llm_config.get("timeout", 120)
        
        messages = []
        worker_guard = "禁止输出<think>，禁止输出思考过程，只输出最终结果。"
        final_system_prompt = system_prompt.strip()
        if self.agent_id not in ["manager_agent", "sql_generator_agent"]:
            final_system_prompt = f"{worker_guard}\n{final_system_prompt}".strip()
        if final_system_prompt:
            messages.append({"role": "system", "content": final_system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        url = f"{api_base}/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": max_tokens if max_tokens is not None else 4096,
        }
        if response_format:
            payload["response_format"] = response_format
        
        headers = {"Content-Type": "application/json"}
        
        if self.llm_config.get("api_key") and self.llm_config["api_key"] != "not-needed":
            headers["Authorization"] = f"Bearer {self.llm_config['api_key']}"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.error(f"❌ Invalid LLM response format")
                    return None
                    
        except httpx.TimeoutException:
            logger.error("❌ LLM API timeout")
            return None
        except Exception as e:
            logger.error(f"❌ LLM API call failed: {e}")
            return None

    def _trim_session_history(self):
        """LRU 淘汰最久未访问的 session，防止内存无限增长"""
        if len(self.session_history) <= self._max_session_history:
            return
        excess = len(self.session_history) - self._max_session_history
        sorted_sessions = sorted(self._session_last_access.items(), key=lambda x: x[1])
        for session_id, _ in sorted_sessions[:excess]:
            self.session_history.pop(session_id, None)
            self._session_last_access.pop(session_id, None)
            logger.info(f"🗑️ [LRU] 淘汰旧 session: {session_id[:20]}...")
    
    def _call_llm(self, prompt: str, system_prompt: str = "", max_tokens: int = None,
                  response_format: dict = None) -> str:
        """
        调用 LLM API（同步包装器）
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            max_tokens: 最大输出 token 数（None=使用默认4096）
            response_format: 输出格式，如 {"type": "json_object"}，None=不约束
            
        Returns:
            LLM 响应文本
        """
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self._call_llm_async(prompt, system_prompt, max_tokens, response_format)
                )
                return result
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"❌ LLM sync wrapper failed: {e}")
            return None
    
    def Execute(self, request, context):
        """执行任务"""
        start_time = time.time()

        try:
            logger.info(f"\n{'='*80}")
            logger.info(f"🤖 [{self.agent_id}] 收到执行请求")
            logger.info(f"   ├─ Session ID: {request.session_id}")
            logger.info(f"   ├─ Instruction: {request.instruction}")
            logger.info(f"   ├─ Skills: {list(request.skills)}")
            logger.info(f"   ├─ Input Data 键: {list(request.input_data.keys())}")
            logger.info(f"   └─ Timeout: {request.timeout}s")
            logger.info(f"{'='*80}")

            # 记录到短期记忆（按用户隔离）
            logger.info(f"📝 [{self.agent_id}] 记录请求到短期记忆 (user={request.user_id or 'system'})")
            self._get_memory_mgr(request.user_id).add_to_short_term(request.session_id, {
                "role": "user",
                "content": f"指令: {request.instruction}, 输入: {dict(request.input_data)}"
            })

            # 转换input_data
            input_data = dict(request.input_data)
            
            # 显示输入数据详情
            logger.info(f"📥 [{self.agent_id}] [Input] 传入数据: {json.dumps(input_data, ensure_ascii=False, default=str)}")
            
            # 执行技能
            logger.info(f"⚙️ [{self.agent_id}] 开始执行技能处理")
            result = self._execute_skills(
                skills=list(request.skills),
                input_data=input_data,
                instruction=request.instruction,
                session_id=request.session_id
            )
            
            # 记录输出详情
            logger.info(f"📤 [{self.agent_id}] [Output] 执行结果: {json.dumps(result, ensure_ascii=False, default=str)}")

            # 记录AI响应到短期记忆（按用户隔离）
            result_summary = str(result)[:200]  # 摘要
            logger.info(f"💾 [{self.agent_id}] 记录结果到长期记忆")
            self._get_memory_mgr(request.user_id).add_to_short_term(request.session_id, {
                "role": "assistant",
                "content": result_summary
            })
            
            # 记录Session（兼容性）
            self.session_history[request.session_id] = {
                "input": input_data,
                "output": result,
                "timestamp": datetime.now().isoformat()
            }
            self._session_last_access[request.session_id] = time.time()
            self._trim_session_history()

            # 更新长期记忆（从任务中学习，按用户隔离）
            self._learn_from_execution(request.instruction, result, start_time, request.user_id)

            # 返回结果
            execution_time_ms = int((time.time() - start_time) * 1000)

            success_flag = not (isinstance(result, dict) and result.get("status") == "error")
            error_message = result.get("message", "") if isinstance(result, dict) and not success_flag else ""

            logger.info(f"✅ [{self.agent_id}] 执行完成")
            logger.info(f"   ├─ 执行时间: {execution_time_ms}ms")
            logger.info(f"   ├─ 成功: {success_flag}")
            logger.info(f"   └─ Session: {request.session_id}")
            logger.info(f"{'='*80}\n")

            def _safe_json_fallback(obj):
                if isinstance(obj, Decimal):
                    return int(obj) if obj == obj.to_integral_value() else float(obj)
                return str(obj)

            return dfecrab_pb2.ExecuteResponse(
                success=success_flag,
                agent_id=self.agent_id,
                session_id=request.session_id,
                result=json.dumps(result, ensure_ascii=False, default=_safe_json_fallback),
                error=error_message,
                memory_updated=True,
                execution_time_ms=execution_time_ms,
                timestamp=datetime.now().isoformat()
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            logger.error(f"❌ [{self.agent_id}] 执行失败")
            logger.error(f"   ├─ 错误: {e}")
            logger.error(f"   ├─ 执行时间: {execution_time_ms}ms")
            logger.error(f"   └─ Session: {request.session_id}")
            import traceback
            traceback.print_exc()
            logger.error(f"{'='*80}\n")

            return dfecrab_pb2.ExecuteResponse(
                success=False,
                agent_id=self.agent_id,
                session_id=request.session_id,
                error=str(e),
                execution_time_ms=execution_time_ms,
                timestamp=datetime.now().isoformat()
            )
    
    def Health(self, request, context):
        """健康检查"""
        try:
            # 获取记忆统计信息
            mem_stats = self.memory_mgr.get_memory_stats()
            
            return dfecrab_pb2.HealthStatus(
                healthy=True,
                agent_id=self.agent_id,
                session_count=mem_stats.get("short_term_sessions", 0),
                enabled_skills=self.tools.get("enabled_skills", []),
                timestamp=datetime.now().isoformat()
            )
        except Exception as e:
            return dfecrab_pb2.HealthStatus(
                healthy=False,
                agent_id=self.agent_id,
                session_count=0,
                enabled_skills=[],
                timestamp=datetime.now().isoformat()
            )

    def _execute_skills(self, skills: list, input_data: Dict, instruction: str, session_id: str) -> Any:
        """执行技能"""
        # 如果 Manager 没有传 skills，则使用自身 tools.json 配置的技能
        if not skills:
            skills = self.tools.get("enabled_skills", [])
            if skills:
                logger.info(f"   🔄 [{self.agent_id}] 使用自身配置的技能: {skills}")

        if self.agent_id == "sql_generator_agent":
            return self._execute_sql_generator_skills(skills, input_data, instruction)
        elif self.agent_id == "analyst_agent":
            return self._execute_analyst_skills(skills, input_data, instruction)
        elif self.agent_id == "reporter_agent":
            return self._execute_reporter_skills(skills, input_data, instruction)
        elif self.agent_id == "file_manager_agent":
            return self._execute_file_manager_skills(skills, input_data, instruction)
        elif self.agent_id == "dm_agent":
            return self._execute_dm_skills(skills, input_data, instruction)
        elif self.agent_id in ("default", "dfecrab"):
            return self._execute_default_skills(skills, input_data, instruction)
        elif self.agent_id == "kunming":
            return self._execute_kunming_skills(skills, input_data, instruction)
        else:
            return self._execute_generic_skills(skills, input_data, instruction)

    def _execute_default_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """default 智能体：通用对话、闲聊、问答"""
        message = input_data.get("message", instruction)
        
        logger.info(f"   🦀 [{self.agent_id}] 执行通用对话")
        logger.info(f"      └─ 消息: {message[:200]}...")
        
        system_prompt = self.config.get("system_prompt", "你是DFEcrab的默认智能助手。请自然、简洁地回复用户。")
        user_prompt = message
        
        llm_response = self._call_llm(user_prompt, system_prompt)
        
        if llm_response:
            llm_response = re.sub(r'<think>[\s\S]*?</think>', '', llm_response, flags=re.DOTALL).strip()
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": llm_response
            }
        
        return {
            "status": "error",
            "agent_id": self.agent_id,
            "message": "模型无响应"
        }

    def _execute_kunming_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """
        昆明配网 — 硬编码驱动模式（仅 Round 1 调 LLM）

        Round 0 (代码):    time_parser 预解析时间 → 注入到 LLM prompt
        Round 1 (LLM):     分类 + 提取参数           ← 唯一一次 LLM 调用
        Round 2 (硬编码):  category → endpoint 映射  ← 直接 import kunming_api.execute()
        Round 3 (代码):     检查 API 成功 → 使用 API message 作为回复
        """
        message = input_data.get("message", instruction)

        logger.info(f"   🗄️ [{self.agent_id}] 执行昆明配网技能")
        logger.info(f"      └─ 消息: {message[:200]}...")

        skill_results = []

        # ============================================================
        # 🔵 Round 0: time_parser 预解析时间 → 注入到 LLM prompt
        # ============================================================
        pure_msg = message
        if "消息:" in message:
            pure_msg = message.split("消息:")[-1].strip()
        elif "消息：" in message:
            pure_msg = message.split("消息：")[-1].strip()

        parsed_text, parsed_time = parse_time(pure_msg)
        time_hint = ""

        if parsed_time.get("resolved") and parsed_time.get("start_time"):
            # 🔒 简单验证：未来日期不注入
            parsed_date_str = parsed_time["start_time"][:10]
            parsed_date = datetime.strptime(parsed_date_str, "%Y-%m-%d")
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            if parsed_date > today:
                logger.warning(
                    f"      ├─ 🔒 time_parser 解析出未来日期 {parsed_date_str}，跳过注入"
                )
                parsed_time = {"resolved": False}
            else:
                time_hint = (
                    f"\n[时间已解析]\n"
                    f"用户说的相对时间已自动解析：{parsed_time.get('description', '')}\n"
                    f"对应日期范围：{parsed_time.get('start_time', '')} ~ {parsed_time.get('end_time', '')}\n"
                )
                logger.info(
                    f"      ├─ 🔵 Round 0: time_parser 注入时间提示 "
                    f"[{parsed_time.get('time_type', 'N/A')}] "
                    f"{parsed_time.get('start_time')} ~ {parsed_time.get('end_time')}"
                )

        # 分类器优先看纯用户问题，避免被 [当前时间]/[新会话] 包装文本干扰。
        enhanced_message = f"{time_hint}{pure_msg}" if time_hint else pure_msg
        enhanced_input = dict(input_data)
        enhanced_input["message"] = enhanced_message

        # ================================================================
        # Round 1: LLM 分类 + 参数提取（唯一一次 LLM 调用）
        # ================================================================
        logger.info(f"      ├─ [Round 1/3] LLM 分类决策...")
        classifier_result = self._execute_single_skill("kunming_classifier", enhanced_input, instruction)
        if classifier_result:
            skill_results.append({"skill": "kunming_classifier", "result": classifier_result})
            logger.info(f"      ├─ 分类结果: {json.dumps(classifier_result, ensure_ascii=False, default=str)[:300]}")

            # 🧠 模型主导 + 代码辅助：LLM 失败或明显误分类时修正
            original_msg = pure_msg
            llm_category = classifier_result.get("category", 5)
            VALID_CATEGORIES = {5, 6, 7, 8, 9, 10, 11, 12, 13}
            overload_requested = "重过载" in original_msg or "过载" in original_msg

            # 重过载优先走代码稳定判定，避免模型把它误判成 12（某局跳闸）等其他类别
            if overload_requested and (
                classifier_result.get("status") != "success"
                or llm_category != 13
                or not classifier_result.get("mode")
            ):
                overload_params = self._code_assist_kunming_classifier(original_msg)
                if overload_params.get("category") == 13:
                    classifier_result["category"] = 13
                    classifier_result["status"] = "success"
                    for key in ["mode", "area", "date", "days", "load_threshold"]:
                        value = overload_params.get(key)
                        if value not in ("", None):
                            classifier_result[key] = value
                    llm_category = 13
                    logger.info(
                        "      ├─ 🔧 重过载代码校正: category=13, mode=%s, area=%s, days=%s, threshold=%s",
                        classifier_result.get("mode", ""),
                        classifier_result.get("area", ""),
                        classifier_result.get("days", 3),
                        classifier_result.get("load_threshold", 80),
                    )

            # 代码辅助修正：LLM 返回 error / 类别不在合法范围 时触发
            needs_fix = (
                classifier_result.get("status") == "error"
                or llm_category not in VALID_CATEGORIES
            )
            if needs_fix:
                # 跳闸细分（从最具体到最泛化）
                if "跳闸" in original_msg:
                    bureau_match = re.search(r'([\u4e00-\u9fa5]{2,6})(?:供电局|局)', original_msg)
                    if bureau_match:
                        classifier_result["category"] = 12
                        classifier_result["bureau"] = f"{bureau_match.group(1)}供电局"
                    elif "保供电" in original_msg:
                        classifier_result["category"] = 11
                    elif re.search(r'城区一小时|城区1小时', original_msg):
                        classifier_result["category"] = 10
                    else:
                        classifier_result["category"] = 6
                    classifier_result["status"] = "success"
                    logger.info(f"      ├─ 🔧 代码辅助：跳闸→category={classifier_result['category']}")
                elif "受令" in original_msg:
                    classifier_result["category"] = 8
                    classifier_result["status"] = "success"
                    logger.info(f"      ├─ 🔧 代码辅助：受令→category=8")
                elif "早会" in original_msg:
                    classifier_result["category"] = 7
                    classifier_result["status"] = "success"
                    logger.info(f"      ├─ 🔧 代码辅助：早会→category=7")
                elif "异常信号" in original_msg:
                    classifier_result["category"] = 9
                    classifier_result["status"] = "success"
                    logger.info(f"      ├─ 🔧 代码辅助：异常信号→category=9")
                elif "重过载" in original_msg or "过载" in original_msg:
                    classifier_result["category"] = 13
                    classifier_result["status"] = "success"
                    if not classifier_result.get("mode"):
                        classifier_result["mode"] = "total_count"
                    logger.info(f"      ├─ 🔧 代码辅助：重过载→category=13")
                else:
                    classifier_result["category"] = 5
                    classifier_result["status"] = "success"
                    logger.info(f"      ├─ 🔧 代码辅助：未命中现有业务类→category=5（其他对话，不调API）")

            # personName 轻量清洗（LLM 已正确提取时仅去干扰词，未提取时才正则兜底）
            if classifier_result.get("category") == 8:
                raw_name = classifier_result.get("personName", "")
                if not raw_name:
                    match = re.search(
                        r'([\u4e00-\u9fa5]{2,4})\s*(?:是否|有无|能否|可否|的|具备)',
                        original_msg
                    )
                    if match:
                        classifier_result["personName"] = match.group(1)
                        logger.info(f"      ├─ 🔧 正则兜底 personName={match.group(1)}（LLM未提取）")
                else:
                    cleaned = re.sub(r'^(是否|有无|能否|可否)', '', raw_name)
                    cleaned = re.sub(r'(是否|有无|能否|可否)$', '', cleaned)
                    if cleaned and cleaned != raw_name:
                        logger.info(f"      ├─ 🔧 清洗 personName {raw_name}→{cleaned}")
                        classifier_result["personName"] = cleaned

        # ================================================================
        # Round 2: 硬编码映射 — 根据分类结果直接调 API（不调 LLM）
        # ================================================================
        logger.info(f"      ├─ [Round 2/3] 硬编码 API 调用...")

        category = 5  # ★ 默认值，防止 classifier 失败时 UnboundLocalError

        api_result = None
        if classifier_result and classifier_result.get("status") == "success":
            category = classifier_result.get("category", 5)

            # 类别 5（其他对话）：直接回复原始消息，无需调 API
            if category == 5:
                logger.info(f"      ├─ 类别5（其他对话），无需调 API")
                return {
                    "status": "success",
                    "agent_id": self.agent_id,
                    "content": pure_msg,
                    "skill_results": skill_results,
                    "answer_final": pure_msg,
                    "other": {
                        "recommendQuestions": "",
                        "Voice_File": pure_msg,
                        "DataType": "CHAT"
                    }
                }


            # 硬编码映射表：category → API endpoint
            CATEGORY_API_MAP = {
                6: "tiaozha",
                7: "zaohui",
                8: "check_qualification",
                9: "get_abnormal_signals",
                10: "today-chengqu-1h-trip",
                11: "today-baogongdian-trip",
                12: "today-bureau-trip",
                13: "overload",
            }

            endpoint = CATEGORY_API_MAP.get(category)
            if not endpoint:
                logger.warning(f"      └─ ⚠️ 不支持的分类: {category}")
                return {
                    "status": "error",
                    "agent_id": self.agent_id,
                    "message": f"不支持的分类: {category}",
                    "skill_results": skill_results
                }

            # 构造 API 参数
            params = {}
            if category in (6, 7, 10, 11):
                params = {
                    "startTime": classifier_result.get("startTime", ""),
                    "endTime": classifier_result.get("endTime", ""),
                }

                # 🔵 时间填充：LLM 没提取时用 time_parser 结果
                if not params.get("startTime") and parsed_time.get("start_time"):
                    params["startTime"] = parsed_time["start_time"]
                    logger.info(
                        f"      ├─ 🔧 填充 startTime（来自 time_parser）: {params['startTime']}"
                    )
                if not params.get("endTime") and parsed_time.get("end_time"):
                    params["endTime"] = parsed_time["end_time"]
                    logger.info(
                        f"      ├─ 🔧 填充 endTime（来自 time_parser）: {params['endTime']}"
                    )

                # 🔵 终极兜底：填今天
                if not params.get("startTime"):
                    now = datetime.now()
                    params["startTime"] = now.strftime("%Y-%m-%d 00:00:00")
                    params["endTime"] = now.strftime("%Y-%m-%d 23:59:59")
                    logger.info(
                        f"      ├─ 🔧 兜底时间（今天）: {params['startTime']} ~ {params['endTime']}"
                    )

            elif category == 8:
                params = {
                    "personName": classifier_result.get("personName", ""),
                }

            elif category == 9:
                date_val = classifier_result.get("date", "")
                # 🔵 日期填充：LLM 没提取时用 time_parser 结果或今天
                if not date_val:
                    if parsed_time.get("start_time"):
                        date_val = parsed_time["start_time"][:10]
                        logger.info(
                            f"      ├─ 🔧 填充 date（来自 time_parser）: {date_val}"
                        )
                    else:
                        date_val = datetime.now().strftime("%Y-%m-%d")
                        logger.info(
                            f"      ├─ 🔧 兜底 date（今天）: {date_val}"
                        )
                params = {
                    "date": date_val,
                }

            elif category == 12:
                params = {
                    "bureau": classifier_result.get("bureau", ""),
                }
                # 🔵 bureau 兜底：LLM 没提取时，从原文正则提取
                if not params["bureau"]:
                    match = re.search(
                        r'([\u4e00-\u9fa5]{2,6}(?:供电局|局))', original_msg
                    )
                    if match:
                        params["bureau"] = match.group(1)
                        logger.info(
                            f"      ├─ 🔧 正则兜底 bureau={params['bureau']}"
                        )

            elif category == 13:
                raw_area = classifier_result.get("area", "")
                TIME_WORDS = ["今天", "今日", "昨天", "前天", "明天", "这周", "上周", "这月", "上月", "今年", "去年"]
                for tw in TIME_WORDS:
                    if raw_area.startswith(tw):
                        raw_area = raw_area[len(tw):].strip()
                        logger.info(f"      ├─ 🔧 清洗 area 时间前缀: {classifier_result.get('area', '')} → {raw_area}")
                        break
                params = {
                    "mode": classifier_result.get("mode", ""),
                    "area": raw_area,
                    "date": classifier_result.get("date", ""),
                    "days": classifier_result.get("days", 3),
                    "load_threshold": classifier_result.get("load_threshold", 80),
                }
                # 🔵 date 兜底：LLM 没提取时用 time_parser 结果或今天
                if not params["date"]:
                    if parsed_time.get("start_time"):
                        params["date"] = parsed_time["start_time"][:10]
                        logger.info(
                            f"      ├─ 🔧 填充 date（来自 time_parser）: {params['date']}"
                        )
                    else:
                        params["date"] = datetime.now().strftime("%Y-%m-%d")
                        logger.info(
                            f"      ├─ 🔧 兜底 date（今天）: {params['date']}"
                        )

            logger.info(f"      ├─ 调用 API: {endpoint}, params: {json.dumps(params, ensure_ascii=False)}")

            # 直接 import kunming_api 并调用（不经过 _execute_single_skill → 不走 LLM）
            try:
                import importlib.util
                from pathlib import Path
                skill_path = PROJECT_ROOT / "skills" / "kunming_api" / "execute.py"
                if skill_path.exists():
                    spec = importlib.util.spec_from_file_location("kunming_api", skill_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        api_result = module.execute(endpoint=endpoint, params=params)
                else:
                    logger.error(f"      └─ ❌ kunming_api 技能文件不存在")
            except Exception as e:
                logger.error(f"      └─ ❌ API 调用异常: {e}")
                import traceback
                traceback.print_exc()

        if api_result:
            skill_results.append({"skill": "kunming_api", "result": api_result})
            logger.info(f"      ├─ API 结果: {json.dumps(api_result, ensure_ascii=False, default=str)[:300]}")
        else:
            logger.error(f"      └─ ⚠️ API 调用失败或无分类结果")

        # ================================================================
        # Round 3: 代码格式化 — 先检查 API 是否成功
        # ================================================================
        logger.info(f"      ├─ [Round 3/3] 代码格式化...")

        # 🔵 先检查 API 是否真的成功了
        api_success = api_result and api_result.get("status") == "success"
        if not api_success:
            error_msg = api_result.get("message", "API 调用失败") if api_result else "API 无响应"
            return {
                "status": "error",
                "agent_id": self.agent_id,
                "message": error_msg,
                "skill_results": skill_results,
            }

        # ── 公共：提取 API 数据和查询时间 ──
        # api_result["data"] = DM-kunming 原始响应，包含 {data, message, ...}
        data = api_result.get("data", {})
        # API 的 message 字段在 data 内层（tiaozha/zaohui 都有），就是可直接展示的文本
        api_message = data.get("message", "")
        start_time = classifier_result.get("startTime", "") if classifier_result else ""
        end_time = classifier_result.get("endTime", "") if classifier_result else ""
        # 生成时间描述（如 "2026-07-13"、"2026-07-06 ~ 2026-07-12"）
        if start_time and end_time:
            if start_time[:10] == end_time[:10]:
                time_desc = start_time[:10]
            else:
                time_desc = f"{start_time[:10]} ~ {end_time[:10]}"
        else:
            time_desc = ""

        # ── 分支6: 跳闸统计 ──
        if category == 6:
            answer_final = str(api_message) if api_message else "跳闸统计数据查询完成"
            voice_file = str(api_message) if api_message else (f"已生成{time_desc}跳闸统计数据报告" if time_desc else "已生成跳闸统计数据报告")
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": voice_file,
                    "DataType": "CHAT"
                }
            }

        # ── 分支7: 早会材料 ──
        if category == 7:
            answer_final = str(api_message) if api_message else "早会材料数据查询完成"
            voice_file = str(api_message) if api_message else (f"已生成{time_desc}早会材料" if time_desc else "已生成早会材料")
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": voice_file,
                    "DataType": "CHAT"
                }
            }

        # ── 分支8: 受令资格 ──
        if category == 8:
            person_name = classifier_result.get("personName", "") if classifier_result else ""
            result_str = str(data.get("result", ""))
            # 优先使用 API 返回的完整 result 文本（与跳闸/早会逻辑保持一致）
            if result_str and result_str not in ("None", "不具备", "具备"):
                answer_final = result_str
            elif "具备" in result_str and "不" not in result_str:
                answer_final = f"{person_name}具备受令资格"
            elif "不具备" in result_str:
                answer_final = f"{person_name}不具备受令资格"
            else:
                answer_final = f"{person_name}资格查询完成"
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": answer_final,
                    "DataType": "CHAT"
                }
            }

        # ── 分支9: 异常信号统计 ──
        if category == 9:
            result_str = str(data.get("result", ""))
            # 优先使用 API 返回的完整 result 文本
            if result_str:
                answer_final = result_str
            else:
                answer_final = "异常信号统计数据查询完成"
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": answer_final,
                    "DataType": "CHAT"
                }
            }

        # ── 分支10: 城区一小时跳闸 ──
        if category == 10:
            answer_final = str(api_message) if api_message else "今日城区一小时线路跳闸查询完成"
            voice_file = str(api_message) if api_message else "已查询今日城区一小时线路跳闸数据"
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": voice_file,
                    "DataType": "CHAT"
                }
            }

        # ── 分支11: 保供电跳闸 ──
        if category == 11:
            answer_final = str(api_message) if api_message else "今日保供电线路跳闸查询完成"
            voice_file = str(api_message) if api_message else "已查询今日保供电线路跳闸数据"
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": voice_file,
                    "DataType": "CHAT"
                }
            }

        # ── 分支12: 某局跳闸 ──
        if category == 12:
            bureau = classifier_result.get("bureau", "") if classifier_result else ""
            answer_final = str(api_message) if api_message else f"{bureau}今日跳闸查询完成" if bureau else "今日跳闸查询完成"
            voice_file = str(api_message) if api_message else f"已查询{bureau}今日跳闸数据" if bureau else "已查询今日跳闸数据"
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": voice_file,
                    "DataType": "CHAT"
                }
            }

        # ── 分支13: 重过载 ──
        if category == 13:
            result_str = str(data.get("result", "")).strip()
            mode = (classifier_result.get("mode", "") if classifier_result else "") or str(data.get("mode", "")).strip()
            area = (classifier_result.get("area", "") if classifier_result else "") or str(data.get("area", "")).strip()
            row_count = int(data.get("row_count", 0) or 0)
            rows = data.get("data", []) if isinstance(data.get("data"), list) else []

            if result_str and result_str not in ("None", ""):
                answer_final = result_str
            elif mode == "detail":
                if row_count <= 0 or not rows:
                    answer_final = f"{area or '当前条件下'}未查询到重过载明细。"
                else:
                    top_rows = rows[:5]
                    parts = []
                    for item in top_rows:
                        if not isinstance(item, dict):
                            continue
                        line_name = item.get("FDNAME") or item.get("FEEDER") or item.get("DEVNO") or "未知线路"
                        loadrate = item.get("LOADRATE")
                        if loadrate not in (None, ""):
                            parts.append(f"{line_name}负载率{loadrate}%")
                        else:
                            parts.append(str(line_name))
                    detail_text = "；".join(parts) if parts else "无明细"
                    area_prefix = f"{area}今日" if area else "今日"
                    answer_final = f"{area_prefix}共查询到{row_count}条重过载明细，前几项为：{detail_text}。"
            elif mode == "top_feeders":
                if row_count <= 0 or not rows:
                    answer_final = f"{area or '当前条件下'}未查询到重过载排行数据。"
                else:
                    top_rows = rows[:5]
                    parts = []
                    for item in top_rows:
                        if not isinstance(item, dict):
                            continue
                        line_name = item.get("FDNAME") or item.get("FEEDER") or "未知线路"
                        overload_count = item.get("OVERLOAD_COUNT", 0)
                        parts.append(f"{line_name}{overload_count}次")
                    rank_text = "、".join(parts) if parts else "无排行数据"
                    area_prefix = f"{area}今日" if area else "今日"
                    answer_final = f"{area_prefix}重过载次数最多的线路为：{rank_text}。"
            else:
                area_prefix = f"{area}的" if area else ""
                answer_final = f"已完成{area_prefix}重过载数据查询。"

            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": json.dumps(api_result, ensure_ascii=False, default=str),
                "data": data,
                "skill_results": skill_results,
                "answer_final": answer_final,
                "other": {
                    "recommendQuestions": "",
                    "Voice_File": answer_final,
                    "DataType": "CHAT"
                }
            }

        return {
            "status": "error",
            "agent_id": self.agent_id,
            "message": api_result.get("message", "API 调用失败") if api_result else "分类失败",
            "skill_results": skill_results
        }

    def _clean_llm_reasoning(self, text: str) -> str:
        """清洗 LLM 输出中的 reasoning 痕迹
        
        核心策略：找到文本中最后一个包含 answer_final 的完整 JSON，
        如果存在则只返回该 JSON，否则清理推理前缀后返回原文本。
        """
        if not text:
            return text
        # 1. 去除已知 reasoning 标签
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', text, flags=re.DOTALL)
        text = re.sub(r"Here'?s?\s*a\s+thinking\s+process:[\s\S]*?(?=\n|$)", '', text, flags=re.DOTALL)

        # 2. 从右往左找最后一个包含 answer_final 的完整 JSON
        last_brace_start = text.rfind('{')
        last_brace_end = text.rfind('}')
        if last_brace_start != -1 and last_brace_end != -1 and last_brace_end > last_brace_start:
            json_str = text[last_brace_start:last_brace_end + 1]
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and "answer_final" in parsed:
                    return json_str  # ★ 关键修复：只返回 JSON，不返回带推理的原始文本
            except (json.JSONDecodeError, TypeError):
                pass

        # 3. 兜底：尝试正则找第一个 JSON（可能被推理文本包裹）
        json_match = re.search(r'\{[\s\S]*"answer_final"[\s\S]*?\}', text)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                if isinstance(parsed, dict) and "answer_final" in parsed:
                    return json_match.group()
            except (json.JSONDecodeError, TypeError):
                pass

        # 4. 如果以上都不行，去掉推理前缀后返回
        reasoning_prefixes = [
            r'^用户问题是', r'^当前技能列表', r'^仔细看技能',
            r'^有没有可能', r'^所以结论是', r'^我再检查一遍',
            r'^所以，我将回复', r'^但是，等等', r'^不过，作为',
            r'^因此，输出应该是', r'^再仔细看技能列表',
        ]
        for prefix in reasoning_prefixes:
            text = re.sub(prefix, '', text, flags=re.MULTILINE)
        return text.strip()

    def _execute_generic_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """通用智能体执行逻辑：优先执行技能获取真实数据，否则使用 LLM 生成回答"""
        message = input_data.get("message", instruction)

        logger.info(f"   🤖 [{self.agent_id}] 执行通用技能")
        logger.info(f"      └─ 消息: {message[:200]}...")
        logger.info(f"      └─ 技能列表: {skills}")

        skill_results = []
        real_data_context = ""

        # 步骤1：如果配置了技能，执行技能获取真实数据
        if skills:
            logger.info(f"      └─ 检测到 {len(skills)} 个技能，开始执行...")
            for skill_id in skills:
                skill_result = self._execute_single_skill(skill_id, input_data, instruction)
                if skill_result:
                    skill_results.append({"skill": skill_id, "result": skill_result})
                    # ★ 大数据自动摘要：数据量超过5条时，用结构化摘要替代原始JSON
                    data_list = skill_result.get("data", []) if isinstance(skill_result, dict) else []
                    record_count = skill_result.get("row_count", 0) if isinstance(skill_result, dict) else len(data_list)
                    if len(data_list) > 5 or record_count > 5:
                        logger.info(f"      └─ 📊 数据量较大({record_count}条)，使用结构化摘要替代原始数据")
                        context_part = f"\n\n【技能 {skill_id} 返回的数据摘要】\n{self._summarize_data_for_llm(skill_id, skill_result)}"
                    else:
                        if isinstance(skill_result, dict):
                            result_str = json.dumps(skill_result, ensure_ascii=False, default=str)
                        else:
                            result_str = str(skill_result)
                        logger.info(f"      └─ 技能 [{skill_id}] 执行结果: {result_str[:500]}")
                        context_part = f"\n\n【技能 {skill_id} 返回的数据】\n{result_str}"
                    real_data_context += context_part
                else:
                    logger.warning(f"      └─ 技能 [{skill_id}] 执行失败或无返回")
        
        # 步骤2：构建系统提示词，包含真实数据（如果有）
        base_system_prompt = self.config.get("system_prompt", f"你是{self.agent_id}，一个智能助手。")
        
        if real_data_context:
            system_prompt = f"""{base_system_prompt}

【重要】你需要基于以下真实数据来回答用户的问题，而不是编造数据。
如果提供的技能数据为空或查询结果为空，请明确告知用户"无法获取数据"，而不是生成虚假数据。
{real_data_context}"""
        else:
            system_prompt = base_system_prompt

        user_prompt = message

        # 步骤3：调用 LLM 生成回答
        llm_response = self._call_llm(user_prompt, system_prompt)

        if llm_response:
            llm_response = re.sub(r'<think>[\s\S]*?</think>', '', llm_response, flags=re.DOTALL).strip()
            llm_response = self._clean_llm_reasoning(llm_response)
            # 兜底：如果 LLM 输出包含 answer_final JSON，直接提取
            json_match = re.search(r'\{[\s\S]*"answer_final"[\s\S]*?\}', llm_response)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    if isinstance(parsed, dict) and "answer_final" in parsed:
                        llm_response = json.dumps(parsed, ensure_ascii=False)
                except Exception:
                    pass
            return {
                "status": "success",
                "agent_id": self.agent_id,
                "content": llm_response,
                "skill_results": skill_results if skill_results else None
            }

        return {
            "status": "error",
            "agent_id": self.agent_id,
            "message": "模型无响应"
        }

    def _summarize_data_for_llm(self, skill_id: str, skill_result: dict, max_chars: int = 2000) -> str:
        """当数据量大时，用代码生成结构化摘要（不经过LLM），避免LLM输出截断"""
        logger.info(f"      └─ 📝 生成数据摘要 ({skill_id})...")
        
        query_type = skill_result.get("query_type", "unknown")
        time_range = skill_result.get("time_range", {})
        data_list = skill_result.get("data", [])
        risk_summary = skill_result.get("risk_summary", {})
        row_count = skill_result.get("row_count", 0)
        columns = skill_result.get("columns", [])
        
        lines = []
        lines.append(f"【数据摘要 - {query_type}】")
        lines.append(f"时间范围: {time_range.get('start', '')} ~ {time_range.get('end', '')}")
        lines.append(f"总记录数: {row_count}")
        if risk_summary:
            lines.append(f"风险统计: {json.dumps(risk_summary, ensure_ascii=False)}")
        if columns:
            lines.append(f"字段列表: {', '.join(columns)}")
        
        if data_list:
            # 取前3条作为示例
            sample = data_list[:3]
            lines.append(f"\n【数据详情 - 前{len(sample)}条示例】")
            for item in sample:
                # 只显示关键字段（去掉内部标记字段）
                brief = {k: v for k, v in item.items() if not k.startswith('_')}
                lines.append(json.dumps(brief, ensure_ascii=False, default=str))
            
            if len(data_list) > 3:
                rest = data_list[3:]
                # 区域分布统计
                area_key = next((k for k in ["所属区县", "所属区县局", "所属区县局"] if k in data_list[0]), None)
                if area_key:
                    areas = {}
                    for item in rest:
                        area = item.get(area_key, "未知")
                        areas[area] = areas.get(area, 0) + 1
                    lines.append(f"\n【剩余 {len(rest)} 条记录的区域分布】")
                    for area, count in sorted(areas.items(), key=lambda x: -x[1]):
                        lines.append(f"  {area}: {count}条")
                
                # 负载率统计
                rate_keys = [k for k in ["负载率(%)", "负载率(%)"] if any(k in item for item in data_list)]
                if rate_keys:
                    rate_key = rate_keys[0]
                    rates = []
                    for item in data_list:
                        rate = item.get(rate_key)
                        if rate is not None:
                            try:
                                rates.append(float(rate))
                            except (ValueError, TypeError):
                                pass
                    if rates:
                        lines.append(f"\n【负载率统计】")
                        lines.append(f"  最高: {max(rates):.1f}%")
                        lines.append(f"  最低: {min(rates):.1f}%")
                        lines.append(f"  平均: {sum(rates)/len(rates):.1f}%")
        
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...(数据摘要已截断)"
        
        logger.info(f"      └─ ✅ 摘要生成完成 ({len(text)}字符)")
        return text

    def _execute_single_skill(self, skill_id: str, input_data: Dict, instruction: str) -> Any:
        """执行单个技能，返回技能执行结果"""
        import importlib.util
        from pathlib import Path

        skill_path = PROJECT_ROOT / "skills" / skill_id / "execute.py"
        if not skill_path.exists():
            logger.warning(f"      └─ ⚠️ 技能文件不存在: {skill_path}")
            return None

        try:
            spec = importlib.util.spec_from_file_location(skill_id, skill_path)
            if spec is None or spec.loader is None:
                logger.warning(f"      └─ ⚠️ 无法加载技能模块: {skill_path}")
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # ================================================================
            # 读取用户消息
            # ================================================================
            message = input_data.get("message", instruction)

            # ================================================================
            # 读取 SKILL.md 文档
            # ================================================================
            skill_md_path = PROJECT_ROOT / "skills" / skill_id / "SKILL.md"
            skill_doc = ""
            if skill_md_path.exists():
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    skill_doc = f.read()

            # ================================================================
            # 步骤 1：有 SKILL_METADATA + SKILL.md，用 LLM 提取参数
            # ================================================================
            if hasattr(module, 'SKILL_METADATA') and skill_doc:
                meta_params = module.SKILL_METADATA.get("parameters", {})
                
                # ★ kunming_classifier 直接走代码分类（不依赖LLM）
                if skill_id == "kunming_classifier":
                    code_params = self._code_assist_kunming_classifier(message)
                    logger.info(f"      └─ 🛠️ 代码辅助分类: category={code_params['category']}")
                    logger.info(f"      └─ 执行技能 {skill_id}，参数: {list(code_params.keys())}")
                    return module.execute(**code_params)
                
                if meta_params:
                    extracted = self._extract_params_via_llm(
                        skill_id, message, skill_doc, meta_params
                    )
                    if extracted:
                        logger.info(f"      └─ 🤖 LLM提取参数: {json.dumps(extracted, ensure_ascii=False)}")
                        logger.info(f"      └─ 执行技能 {skill_id}，参数: {list(extracted.keys())}")
                        return module.execute(**extracted)
                    logger.warning(f"      └─ ⚠️ LLM参数提取失败，走 fallback 逻辑")

            # ================================================================
            # 步骤 2：有 SKILL_METADATA 走原有逻辑（fallback）
            # ================================================================
            if hasattr(module, 'SKILL_METADATA'):
                params = {}
                meta_params = module.SKILL_METADATA.get("parameters", {})
                for param_name in meta_params:
                    if param_name in input_data:
                        params[param_name] = input_data[param_name]
                    elif param_name == "message":
                        params[param_name] = message

                logger.info(f"      └─ 执行技能 {skill_id}，参数: {list(params.keys())}")
                return module.execute(**params)

            # ================================================================
            # 步骤 3：没有 SKILL_METADATA 但有 execute 函数
            #   尝试从 SKILL.md 推断参数
            # ================================================================
            if hasattr(module, 'execute'):
                if skill_doc:
                    inferred = self._extract_params_via_llm(
                        skill_id, message, skill_doc, None
                    )
                    if inferred:
                        logger.info(f"      └─ 🤖 LLM推断参数: {json.dumps(inferred, ensure_ascii=False)}")
                        return module.execute(**inferred)
                return module.execute()
            else:
                logger.warning(f"      └─ ⚠️ 技能 {skill_id} 没有 execute 函数")
                return None

        except Exception as e:
            logger.error(f"      └─ ❌ 技能执行异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _code_assist_kunming_classifier(self, message: str) -> dict:
        """代码辅助分类：代码主导分类 + 代码粗提取 + LLM精提取（只补缺失参数）
        
        分类规则（按优先级从高到低）：
        12=某局跳闸 > 11=保供电跳闸 > 10=城区一小时跳闸 > 9=异常信号统计
        > 8=受令资格 > 7=早会材料 > 6=跳闸统计 > 13=重过载 > 5=其他对话(不调API)
        
        流程：代码先做分类+粗提取 → 检查参数完整性 → 缺失参数调LLM精提取
        """
        import re
        from src.utils.time_parser import parse_time
        
        # 默认值（未命中业务类→5 其他对话，理论题已下线改由 knowledge_agent 承接）
        params = {
            "query": message,
            "category": 5,
            "startTime": "",
            "endTime": "",
            "personName": "",
            "date": "",
            "bureau": "",
            "mode": "",
            "area": "",
            "days": 3,
            "load_threshold": 80
        }
        
        # =======================================
        # 阶段1：代码分类 + 粗提取参数
        # =======================================
        TIME_WORDS = ["今天", "今日", "昨天", "前天", "明天", "这周", "上周", "这月", "上月", "今年", "去年"]
        TRIP_WORDS = ["跳闸", "跳了", "跳停"]
        
        has_trip = any(tw in message for tw in TRIP_WORDS)
        
        def strip_time_prefix(text):
            cleaned = text
            for tw in TIME_WORDS:
                if cleaned.startswith(tw):
                    cleaned = cleaned[len(tw):].strip()
                    break
            return cleaned
        
        cleaned_msg = strip_time_prefix(message)
        
        # 12=某局跳闸（直接匹配"XX供电局"或"XX局"整体）
        bureau_pattern = r'([\u4e00-\u9fa5]{2,4}供电局|[\u4e00-\u9fa5]{2,3}局)'
        bureau_match = re.search(bureau_pattern, cleaned_msg)
        if bureau_match and (has_trip or "统计" in message or "情况" in message):
            params["category"] = 12
            params["bureau"] = bureau_match.group(1)
        # 11=保供电跳闸
        elif "保供电" in message and (has_trip or "统计" in message):
            params["category"] = 11
        # 10=城区一小时跳闸（放宽条件：接受"线路"或"情况"）
        elif ("城区一小时" in message or "1小时" in message) and (has_trip or "线路" in message or "情况" in message):
            params["category"] = 10
        # 9=异常信号统计
        elif "异常信号" in message:
            params["category"] = 9
        # 8=受令资格（多种语序模式，精确匹配优先）
        elif "受令资格" in message or "调度受令" in message:
            params["category"] = 8
            # 模式1："张良是否具备受令资格" → "张良"（精确匹配：姓名+是否）
            name_match = re.search(r'([\u4e00-\u9fa5]{2,3})是否具备受令资格', message)
            if not name_match:
                # 模式2："查看王五是否具备受令资格" → "王五"（精确匹配：查看+姓名+是否）
                name_match = re.search(r'查看\s*([\u4e00-\u9fa5]{2,3})\s*是否具备受令资格', message)
            if not name_match:
                # 模式3："查一下李四的受令资格" → "李四"（精确匹配：查一下+姓名+的）
                name_match = re.search(r'(?:查一下|查询)\s*([\u4e00-\u9fa5]{2,4})\s+的\s+受令资格', message)
            if not name_match:
                # 模式4："查李四的受令资格" → "李四"（简化模式）
                name_match = re.search(r'查\s*([\u4e00-\u9fa5]{2,4})\s+的\s+受令资格', message)
            if not name_match:
                # 模式5："张三受令资格查询" → "张三"（姓名+受令资格）
                name_match = re.search(r'([\u4e00-\u9fa5]{2,4})\s*受令资格', message)
            if not name_match:
                # 模式6："受令资格查询：张三" → "张三"（兜底模式）
                name_match = re.search(r'受令资格[^\u4e00-\u9fa5]*([\u4e00-\u9fa5]{2,4})', message)
            if name_match:
                params["personName"] = name_match.group(1)
        # 13=重过载（含"重过载/过载"）
        elif "重过载" in message or "过载" in message:
            params["category"] = 13
            params["load_threshold"] = 80
            if "汇总" in message or "全局" in message or "全区" in message:
                params["mode"] = "total_count"
            elif "趋势" in message or "变化" in message or "最近" in message:
                params["mode"] = "trend"
                days_match = re.search(r'最近(\d+)天', message)
                if days_match:
                    params["days"] = int(days_match.group(1))
                else:
                    params["days"] = 3
            elif "详细" in message or "列表" in message:
                params["mode"] = "detail"
            elif "最多" in message or "排行" in message or "top" in message:
                params["mode"] = "top_feeders"
            else:
                bureau_match = re.search(bureau_pattern, cleaned_msg)
                if bureau_match:
                    params["mode"] = "area_count"
                    params["area"] = bureau_match.group(1)
                else:
                    params["mode"] = "total_count"
            if not params["area"]:
                area_match = re.search(bureau_pattern, cleaned_msg)
                if area_match:
                    params["area"] = area_match.group(1)
        # 7=早会材料
        elif "早会材料" in message:
            params["category"] = 7
        # 6=跳闸统计（接受"跳了"作为关键词）
        elif has_trip:
            params["category"] = 6
        
        # 时间解析（使用 time_parser.py）
        _, time_info = parse_time(message)
        if time_info["resolved"]:
            if time_info.get("start_time"):
                params["startTime"] = time_info["start_time"]
            if time_info.get("end_time"):
                params["endTime"] = time_info["end_time"]
            if time_info.get("dates"):
                params["date"] = time_info["dates"][0]
        
        # =======================================
        # 阶段2：检查参数完整性，如果缺失则调用LLM精提取
        # =======================================
        # 需要LLM辅助的条件：
        # - category=12（某局跳闸）但 bureau 为空
        # - category=8（受令资格）但 personName 为空
        # - category=9（异常信号）但 date 为空
        # - category=13（重过载）但 mode 为空
        need_llm_refine = False
        if params["category"] == 12 and not params["bureau"]:
            need_llm_refine = True
        elif params["category"] == 8 and not params["personName"]:
            need_llm_refine = True
        elif params["category"] == 9 and not params["date"]:
            need_llm_refine = True
        elif params["category"] == 13 and not params["mode"]:
            need_llm_refine = True
        
        if need_llm_refine:
            logger.info(f"      └─ ⚠️ 代码提取参数不完整，调用LLM精提取")
            llm_params = self._llm_refine_kunming_params(message, params)
            if llm_params:
                # 只覆盖为空的字段
                for k in ["bureau", "personName", "date", "startTime", "endTime", "mode", "area"]:
                    if not params[k] and llm_params.get(k):
                        params[k] = llm_params[k]
                        logger.info(f"      └─ 🤖 LLM补充参数: {k}={params[k]}")
        
        return params
    
    def _llm_refine_kunming_params(self, message: str, current_params: dict) -> dict:
        """LLM精提取：只提取缺失的参数，不重新分类
        
        用于代码提取不完整时的补充，如：
        - 代码无法识别的局名格式
        - 复杂语序的人名提取
        """
        # 懒加载：如果模型配置还没加载完，同步加载
        if not self.llm_config.get("api_base"):
            logger.info(f"🔄 [{self.agent_id}] 模型配置未就绪，同步加载...")
            self.llm_config = self._load_llm_config()
            if not self.llm_config.get("api_base"):
                logger.warning(f"⚠️ [{self.agent_id}] LLM API not configured，跳过精提取")
                return current_params
        
        category = current_params["category"]
        
        # 根据category确定需要提取的参数
        needed_params = []
        if category == 12 and not current_params["bureau"]:
            needed_params.append("bureau")
        if category == 8 and not current_params["personName"]:
            needed_params.append("personName")
        if not current_params["date"]:
            needed_params.append("date")
        if not current_params["startTime"] or not current_params["endTime"]:
            needed_params.extend(["startTime", "endTime"])
        if category == 13:
            if not current_params["mode"]:
                needed_params.append("mode")
            if not current_params["area"]:
                needed_params.append("area")
        
        if not needed_params:
            return {}
        
        # 构建精提取prompt
        user_prompt = f"""请从用户消息中提取以下参数（只提取，不分类）：

需要提取的参数：{needed_params}
用户消息：{message}
当前日期：{datetime.now().strftime('%Y年%m月%d日')}

参数说明：
- bureau：供电局名称（如"官渡供电局"、"西山局"）
- personName：人员姓名（如"张良"、"李四"）
- date：查询日期（格式 YYYY-MM-DD）
- startTime：查询起始时间（格式 YYYY-MM-DD HH:MM:SS）
- endTime：查询结束时间（格式 YYYY-MM-DD HH:MM:SS）
- mode：重过载查询模式，可选值：area_count（某局数量）、total_count（全局汇总）、trend（趋势）、detail（详细列表）、top_feeders（最多线路）
- area：区局名称（如"官渡供电局"、"西山局"）

请严格只返回一个 JSON 对象，只包含上述需要提取的参数，不要包含category。
如果某个参数无法从消息中提取，请留空字符串。

禁止输出任何思考过程、<think>标签或推理内容。只输出 JSON。"""
        
        try:
            # 调用LLM精提取
            payload = {
                "model": self.llm_config.get("model_name", "Qwen3-30B-A3B/Qwen3-30B-A3B"),
                "messages": [
                    {"role": "system", "content": "禁止输出<think>，禁止输出思考过程，只输出最终结果。"},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False,
                "temperature": 0.3,
                "max_tokens": 256,
                "response_format": {"type": "json_object"}
            }
            
            api_base = self.llm_config["api_base"]
            resp = requests.post(
                f"{api_base}/v1/chat/completions",
                headers={"Content-Type": "application/json", "Authorization": "Bearer not-needed"},
                json=payload,
                timeout=30
            )
            
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                content = re.sub(r'</?think[^>]*>', '', content, flags=re.IGNORECASE)
                return json.loads(content)
        except Exception as e:
            logger.error(f"      └─ ❌ LLM精提取失败: {e}")
        
        return {}

    def _extract_params_via_llm(self, skill_id: str, message: str,
                                 skill_doc: str, meta_params: Optional[dict]) -> Optional[dict]:
        """使用智能体自身的 LLM 从用户消息中提取技能参数"""
        if not skill_doc:
            return None

        # 构建参数定义描述
        if meta_params:
            param_schema = json.dumps(meta_params, ensure_ascii=False, indent=2)
        else:
            param_schema = "请根据 SKILL.md 文档中的所有输入参数说明，提取相应的参数。"

        current_date = datetime.now().strftime("%Y年%m月%d日 %H:%M")

        prompt = f"""你是一个参数提取专家。请根据技能文档和用户消息，提取技能执行所需的参数。

## 技能文档
{skill_doc[:4000]}

## 参数定义
{param_schema}

## 用户消息
{message}

## 当前日期
{current_date}

请严格只返回一个 JSON 对象（不要任何其他内容），根据用户消息提取参数值。
如果消息中未明确指定某个参数，请根据上下文合理推断并填写合理的默认值。
对于有枚举值范围的参数（如 'feeder'/'transformer' 等），请从用户消息中的关键词推断最合适的值。
返回的 JSON 中必须包含参数定义中的所有字段，不要缺少任何字段。
JSON key名必须严格使用参数定义中的字段名，如 category 不是 class。

禁止输出任何思考过程、<think>标签或推理内容。只输出 JSON。"""

        resp = self._call_llm(prompt, max_tokens=512, response_format={"type": "json_object"})
        if not resp:
            return None

        # ★ 预处理：清洗 thinking 内容，避免干扰 JSON 提取
        # Step A: 截掉 </think> 之前的所有内容（Qwen thinking 格式）
        think_end = resp.rfind('</think>')
        if think_end != -1:
            resp = resp[think_end + len('</think>'):].strip()
        # Step B: 通用清洗（<think>标签、reasoning前缀等）
        resp = self._clean_llm_reasoning(resp)
        # Step C: 如果 _clean_llm_reasoning 返回的是纯 JSON（有 answer_final），直接解析
        # 否则走下面的括号计数法

        try:
            # ★ 使用括号计数法提取最外层 JSON 对象
            #    取最后一个完整 JSON（thinking 里的示例 JSON 会被覆盖）
            text = resp.strip()
            json_str = ""
            depth = 0
            in_string = False
            escape = False
            start_idx = None
            for i, ch in enumerate(text):
                if escape:
                    escape = False
                    continue
                if ch == '\\':
                    escape = True
                    continue
                if ch == '"' and not in_string:
                    in_string = True
                    if start_idx is None:
                        start_idx = i
                elif ch == '"' and in_string:
                    in_string = False
                elif not in_string:
                    if ch == '{':
                        if depth == 0:
                            start_idx = i
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0 and start_idx is not None:
                            json_str = text[start_idx:i+1]
                            # 不 break，继续遍历取最后一个完整 JSON

            # 兜底：括号计数失败则用正则
            if not json_str:
                match = re.search(r'\{[\s\S]*?\}', text)
                if match:
                    json_str = match.group()

            if not json_str:
                logger.warning(f"      └─ ⚠️ LLM参数提取未返回 JSON")
                return None

            # 多重 JSON 修复策略
            attempts = [
                json_str,                                    # 原始
                json_str.replace("'", '"'),                  # 单引号→双引号
                re.sub(r',(\s*[}\]])', r'\1', json_str),    # 去掉末尾逗号
                json_str.replace("，", ",").replace("：", ":").replace(""", '"').replace(""", '"'),  # 中文标点
                re.sub(r'(\w+)\s*:', r'"\1":', json_str),   # 字段名加引号
                re.sub(r':\s*([^",}\s][^,}\s]*)', r': "\1"', json_str),  # 值加引号
            ]
            # 去重
            seen = set()
            unique_attempts = []
            for a in attempts:
                if a not in seen:
                    seen.add(a)
                    unique_attempts.append(a)

            extracted = None
            for attempt in unique_attempts:
                try:
                    extracted = json.loads(attempt)
                    break
                except json.JSONDecodeError:
                    continue

            if extracted is None:
                logger.warning(f"      └─ ⚠️ LLM参数提取 JSON 全部解析失败")
                return None

            if meta_params:
                # 过滤：只保留参数定义中存在的 key，且排除空值
                valid = {}
                for k, v in extracted.items():
                    if k in meta_params and v not in (None, "", {}):
                        valid[k] = v
            else:
                valid = {k: v for k, v in extracted.items() if v not in (None, "", {})}

            return valid if valid else None

        except Exception as e:
            logger.warning(f"      └─ ⚠️ LLM参数提取解析失败: {e}")
            return None

    def _execute_sql_generator_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """执行 SQL 生成技能"""
        import os
        import json
        import subprocess
        from pathlib import Path

        original_request = input_data.get("original_request", input_data.get("message", instruction))
        existing_sql = input_data.get("sql_query", "")

        logger.info(f"   🧠 [{self.agent_id}] 执行 SQL 生成")
        logger.info(f"      ├─ 原始请求: {original_request[:300]}...")
        logger.info(f"      └─ 已有 SQL: {existing_sql[:300]}...")

        # ========================================================
        # 核心逻辑 1：通过技能框架调用 dm_meta 技能获取最新元数据
        # ========================================================
        meta_cache_path = Path(__file__).parent.parent.parent / "agents" / "sql_generator_agent" / "meta_cache.json"
        cached_meta = {}
        if meta_cache_path.exists():
            try:
                with open(meta_cache_path, 'r', encoding='utf-8') as f:
                    cached_meta = json.load(f)
            except:
                pass

        logger.info(f"      ├─ 正在获取最新表结构元数据...")
        
        # 检查是否启用了 dm_meta 技能
        if "dm_meta" in skills:
            try:
                import importlib.util
                skill_path = PROJECT_ROOT / "skills" / "dm_meta" / "execute.py"
                if not skill_path.exists():
                    logger.warning(f"      ├─ 技能文件不存在: {skill_path}")
                else:
                    spec = importlib.util.spec_from_file_location("dm_meta", skill_path)
                    if spec is None:
                        logger.warning(f"      ├─ 无法加载技能模块: {skill_path}")
                    else:
                        assert spec is not None  # 帮助类型检查器
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)  # type: ignore
                        meta_response = module.execute()
                        if meta_response.get("status") == "success":
                            new_meta = meta_response.get("data", {})
                            # 对比缓存
                            if json.dumps(new_meta, sort_keys=True) != json.dumps(cached_meta, sort_keys=True):
                                logger.info(f"      ├─ ⚠️ 检测到表结构更新，已刷新本地缓存")
                                with open(meta_cache_path, 'w', encoding='utf-8') as f:
                                    json.dump(new_meta, f, ensure_ascii=False, indent=2)
                                cached_meta = new_meta
                            else:
                                logger.info(f"      ├─ 表结构未发生变化，使用本地缓存")
                        else:
                            logger.warning(f"      ├─ 获取元数据失败: {meta_response.get('message')}")
            except Exception as e:
                logger.warning(f"      ├─ 获取元数据异常: {e}")
        else:
            logger.warning(f"      ├─ dm_meta 技能未启用，使用缓存元数据（如果存在）")

        # 格式化元数据供大模型阅读
        meta_context = "【动态表结构信息】\n获取失败，请基于常识推断"
        if cached_meta:
            meta_context = "【动态表结构信息】\n"
            for t_name, t_info in cached_meta.items():
                meta_context += f"- {t_name}:\n"
                columns = t_info.get('columns', {})
                samples = t_info.get('samples', {})
                for col_name, col_info in columns.items():
                    if isinstance(col_info, dict):
                        desc = col_info.get('desc', '')
                        data_type = col_info.get('type', '')
                        col_samples = samples.get(col_name, [])
                        sample_str = f" 示例:{col_samples}" if col_samples else ""
                        meta_context += f"  - {col_name}({data_type}): {desc}{sample_str}\n"
                    else:
                        # 兼容旧格式（纯字符串comment）
                        meta_context += f"  - {col_name}: {col_info}\n"

        # 读取查询模式
        query_mode = input_data.get("query_mode", "normal")

        # 构建模式指令
        if query_mode == "report":
            mode_instruction = """【当前查询模式: report - 简报/日报模式】
用户请求包含"简报"或"日报"，必须生成3条SQL！
用;分隔输出3条SQL，每条有完整WHERE条件：
1. XOPENS.AI_ANALYSE_FEEDER(馈线重过载): LOADRATE>=80
2. XOPENS.AI_ANALYSE_PB(配变重过载): LOADRATE>=80
3. XOPENS.IFA_INDEX(跳闸故障): 按时间排序"""
        elif query_mode == "tiaozha":
            mode_instruction = """【当前查询模式: tiaozha - 跳闸统计模式】
用户请求明确包含"跳闸"，必须生成3条SQL！
用;分隔输出3条SQL，每条有完整WHERE条件：
1. XOPENS.IFA_INDEX: 按 BDZCODE 分组统计数量
2. XOPENS.TX6_DEV_ZWBDZ: 获取 BDZCODE -> OFAR 映射
3. XOPENS.TX6_DEV_ZWQY: 获取 OFAR -> DESCRIPTION 映射"""
        elif query_mode == "zaohui":
            mode_instruction = """【当前查询模式: zaohui - 早会材料模式】
用户请求明确包含"早会材料"，必须生成1条SQL！
XOPENS.IFA_INDEX: 按 CHZ_CONDITION 分组统计数量（1=瞬时性，0=永久性）"""
        elif query_mode == "guozai_trend":
            mode_instruction = """【当前查询模式: guozai_trend - 重过载趋势模式】
用户请求包含"重过载趋势"、\"过载情况\"、\"过载近期\"，必须生成2条SQL！
用;分隔输出2条SQL，每条有完整的日期范围条件：
1. XOPENS.AI_ANALYSE_FEEDER(馈线重过载): 按日期分组统计数量
2. XOPENS.AI_ANALYSE_PB(配变重过载): 按日期分组统计数量"""
        elif query_mode == "guozai_trend_pb":
            mode_instruction = """【当前查询模式: guozai_trend_pb - 配变重过载趋势模式】
用户明确指定了"配变"，只生成1条SQL！
XOPENS.AI_ANALYSE_PB(配变重过载): 按日期分组统计重过载次数"""
        elif query_mode == "guozai_trend_feeder":
            mode_instruction = """【当前查询模式: guozai_trend_feeder - 馈线重过载趋势模式】
用户明确指定了"馈线"或"线路"，只生成1条SQL！
XOPENS.AI_ANALYSE_FEEDER(馈线重过载): 按日期分组统计重过载次数"""
        else:
            mode_instruction = """【当前查询模式: normal - 普通查询模式】
用户请求不包含特殊模式关键词。
只生成1条SQL！禁止生成多条！
根据用户需求选择最相关的1张表，生成1条精准SQL。"""

        system_prompt = self.config.get("system_prompt", "")
        user_prompt = f"""请根据以下输入生成最终可执行 SQL，并只输出 JSON：

{mode_instruction}

{meta_context}

## 原始请求
{original_request}

## 用户已给出的SQL（可能为空）
{existing_sql}
"""
        llm_response = self._call_llm(user_prompt, system_prompt)
        if not llm_response:
            return {
                "status": "error",
                "agent_id": self.agent_id,
                "message": "SQL 生成失败：模型无响应"
            }

        llm_response = re.sub(r'<think>[\s\S]*?</think>', '', llm_response, flags=re.DOTALL).strip()
        llm_response = re.sub(r'^```json\s*', '', llm_response)
        llm_response = re.sub(r'```\s*$', '', llm_response.strip())

        try:
            parsed = json.loads(llm_response)
        except Exception as e:
            return {
                "status": "error",
                "agent_id": self.agent_id,
                "message": f"SQL 生成结果解析失败: {e}",
                "raw_output": llm_response
            }

        if parsed.get("status") == "error":
            return parsed
        if not parsed.get("sql"):
            return {
                "status": "error",
                "agent_id": self.agent_id,
                "message": "SQL 生成结果缺少 sql 字段",
                "raw_output": parsed
            }

        # ========================================================
        # 核心逻辑 2：SQL 基础校验 - 不做字段级硬阻断
        # 简化校验只做 SELECT 检查 + 去重 + 清理，字段正确性由 prompt 保证
        # ========================================================
        if validate_sql:
            try:
                is_valid, field_errors, detail = validate_sql(parsed.get("sql", ""), cached_meta)
                if not is_valid:
                    logger.warning(f"      ❌ SQL 校验失败，终止: {detail}")
                    return {
                        "status": "error",
                        "agent_id": self.agent_id,
                        "message": f"SQL 校验失败：{detail}",
                        "sql": parsed.get("sql", ""),
                        "raw_output": parsed
                    }

                if field_errors:
                    # 有警告但不阻断，保留原始 SQL 继续执行
                    logger.warning(f"      ⚠️ SQL 校验有警告（继续执行）: {detail}")
                else:
                    logger.info(f"      ✅ SQL 校验通过")
            except Exception as e:
                logger.warning(f"      ⚠️ SQL 校验异常（跳过）: {e}")
        else:
            logger.info(f"      ⚠️ SQL 校验模块未加载，跳过校验")

        # ========================================================
        # 核心逻辑 3：SQL数量校验 - 防止普通模式生成多条SQL
        # ========================================================
        if query_mode == "normal":
            generated_sql = parsed.get("sql", "")
            # 统计SQL条数（按;分割，过滤空串和非SELECT开头）
            sql_parts = [s.strip() for s in generated_sql.split(";") if s.strip() and s.strip().upper().startswith("SELECT")]
            sql_count = len(sql_parts)
            if sql_count > 1:
                logger.warning(f"      ⚠️ [SQL数量警告] 普通模式生成了{sql_count}条SQL，自动截取第1条")
                # 只取第1条SQL
                parsed["sql"] = sql_parts[0] + ";"
                parsed["reason"] = f"[自动截取第1条] {parsed.get('reason', '')}"
                # 更新stream_text
                parsed["stream_text"] = f"SQL：{parsed['sql']}\n原因：{parsed['reason']}"
            elif sql_count == 0:
                logger.warning(f"      ⚠️ [SQL数量警告] 未检测到有效SQL，跳过数量校验")

        return {
            "status": "success",
            "agent_id": self.agent_id,
            "sql": parsed.get("sql", ""),
            "reason": parsed.get("reason", ""),
            "stream_text": f"SQL：{parsed.get('sql', '')}\n原因：{parsed.get('reason', '')}"
        }
            
    def _execute_dm_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """执行 DM 查询专用智能体技能"""
        import os
        import re
        message = input_data.get("message", instruction)
        explicit_sql = input_data.get("sql_query", "")
        query_mode = input_data.get("query_mode", "normal")
        time_info = input_data.get("time_info", {})
        resolved_message = input_data.get("resolved_message", message)
        
        logger.info(f"   🔎 [{self.agent_id}] 开始执行数据查询任务")
        logger.info(f"      ├─ 原始请求: {message}")
        logger.info(f"      ├─ 查询模式: {query_mode}")
        logger.info(f"      ├─ 时间信息: {time_info}")
        logger.info(f"      ├─ 输入键: {list(input_data.keys())}")
        logger.info(f"      └─ 输入快照: {json.dumps(input_data, ensure_ascii=False, default=str)[:800]}")
        
        # 1. 优先使用上游明确传入的 sql_query，否则再从 message 提取
        sql_query = explicit_sql or "SELECT * FROM XOPENS.AI_ANALYSE_FEEDER"
        if not explicit_sql:
            match = re.search(r'(?i)SQL[：:]\s*(SELECT.+)', message)
            if match:
                sql_query = match.group(1).strip()
                # 仅对正则提取的 SQL 做尾随引号/字符清理，避免损坏上游传入的合法 SQL
                while sql_query and sql_query[-1] in ('"', "'", '。', '，', '.', ','):
                    sql_query = sql_query[:-1]
        
        # 2. 检测分号分隔的多条 SQL
        sql_statements = [s.strip() for s in sql_query.split(';') if s.strip()]
        logger.info(f"      ├─ 检测到 {len(sql_statements)} 条 SQL 语句")
        
        # 3. 如果只有一条，保持原有返回格式兼容
        if len(sql_statements) == 1:
            single_result = self._execute_single_dm_query(sql_statements[0])
            if single_result.get("status") == "error":
                return single_result
            # 对查询结果做简短分析
            summary = self._generate_dm_summary(single_result.get("content", {}), sql_statements[0])
            # 保持原有返回结构
            return {
                "status": "success",
                "content": single_result.get("content", {}),
                "sql": sql_statements[0],
                "summary": summary,
                "stream_text": summary,
                "source": "skill_subprocess"
            }
        
        # 4. 多条 SQL：依次执行
        results = []
        all_summaries = []
        for idx, sql in enumerate(sql_statements):
            logger.info(f"      ├─ 执行第 {idx+1} 条 SQL: {sql[:200]}...")
            single_result = self._execute_single_dm_query(sql, query_mode, time_info)
            if single_result.get("status") == "success":
                s = self._generate_dm_summary(single_result.get("content", {}), sql)
                all_summaries.append(f"SQL{idx+1}: {s}")
            results.append({
                "index": idx,
                "sql": sql,
                "result": single_result
            })
        
        # 5. 普通模式：返回合并结果（tiaozha/zaohui不再提前返回，交给analyst_agent处理）
        logger.info(f"      ✅ 所有 SQL 执行完成")
        merged_summary = "\n".join(all_summaries)
        return {
            "status": "success",
            "multi_query": True,
            "query_count": len(sql_statements),
            "results": results,
            "summary": merged_summary,
            "stream_text": merged_summary,
            "source": "skill_subprocess",
            "query_mode": query_mode
        }
    
    def _execute_single_dm_query(self, sql_query: str, query_mode: str = "normal", time_info: dict = None) -> Dict:
        """执行单条 SQL 查询"""
        import os
        import subprocess
        import shutil
        
        skill_path = PROJECT_ROOT / "skills" / "dm_query" / "execute.py"
        if not skill_path.exists():
            logger.error(f"      ❌ 找不到技能文件: {skill_path}")
            return {"status": "error", "message": "找不到 dm_query 技能文件"}
        
        try:
            python_bin = os.environ.get("DM_PYTHON_BIN") or shutil.which("python3") or "python3"
            cmd = [python_bin, str(skill_path), "--sql-query", sql_query]
            if query_mode and query_mode != "normal":
                cmd.extend(["--query-mode", query_mode])
            if time_info:
                cmd.extend(["--time-info", json.dumps(time_info, ensure_ascii=False)])
            
            # 清理环境变量：移除 venv 相关变量，防止系统 python3 加载 venv 下错误的 dmPython
            clean_env = os.environ.copy()
            clean_env.pop("VIRTUAL_ENV", None)
            clean_env.pop("PYTHONPATH", None)
            if "PATH" in clean_env:
                original_path = clean_env["PATH"]
                path_parts = [p for p in original_path.split(os.pathsep) if "venv" not in p and "virtualenv" not in p]
                clean_env["PATH"] = os.pathsep.join(path_parts)
            
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=clean_env, cwd=str(PROJECT_ROOT))
            if proc.returncode != 0:
                return {
                    "status": "error",
                    "message": f"dm_query 子进程执行失败(returncode={proc.returncode})",
                    "data": [],
                    "sql": sql_query,
                    "stderr": proc.stderr.strip(),
                    "source": "skill_subprocess"
                }
            response = json.loads(proc.stdout.strip())
            if isinstance(response, dict) and response.get("status") == "error":
                return {
                    "status": "error",
                    "message": response.get("message", "数据库查询失败"),
                    "data": response.get("data", []),
                    "sql": sql_query,
                    "source": "skill_subprocess"
                }
            return {
                "status": "success",
                "content": response,
                "sql": sql_query,
                "source": "skill_subprocess"
            }
        except Exception as e:
            logger.error(f"      ❌ 技能执行异常: {e}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": f"查询执行失败: {str(e)}"}
    
    def _format_template_output(self, results: list, query_mode: str, time_info: dict, resolved_message: str) -> dict:
        """统计模式模板格式化输出"""
        dates = time_info.get("dates", [])
        date_range = time_info.get("date_range", [])
        
        if query_mode == "tiaozha":
            if not dates:
                date_str = date_range[0] if date_range else resolved_message
            else:
                date_str = dates[0]
            
            sql1_data = results[0].get("result", {}).get("content", {}).get("data", []) if len(results) > 0 else []
            sql2_data = results[1].get("result", {}).get("content", {}).get("data", []) if len(results) > 1 else []
            sql3_data = results[2].get("result", {}).get("content", {}).get("data", []) if len(results) > 2 else []
            
            bdz_map = {}
            for row in sql2_data:
                bdz_map[row.get("CODE", "")] = row.get("OFAR", "")
            
            qy_map = {}
            for row in sql3_data:
                qy_map[row.get("CODE", "")] = row.get("DESCRIPTION", "")
            
            lines = [f"📊 【跳闸统计】 日期：{date_str}", ""]
            lines.append("=" * 60)
            lines.append(f"{'变电站':<15} {'区域':<15} {'跳闸次数':<10}")
            lines.append("-" * 60)
            
            total_count = 0
            for row in sql1_data:
                bdz = row.get("BDZCODE", "")
                cnt = row.get("CNT", 0)
                total_count += cnt
                ofar = bdz_map.get(bdz, bdz)
                qy = qy_map.get(ofar, ofar)
                lines.append(f"{bdz:<15} {qy:<15} {cnt:<10}")
            
            lines.append("-" * 60)
            lines.append(f"{'合计':<30} {total_count:<10}")
            lines.append("=" * 60)
            
            content_text = "\n".join(lines)
            return {
                "status": "success",
                "content": {"data": sql1_data},
                "query_mode": query_mode,
                "time_info": time_info,
                "template_output": content_text,
                "summary": content_text,
                "stream_text": content_text,
                "source": "skill_subprocess"
            }
        
        elif query_mode == "zaohui":
            if not dates:
                date_str = date_range[0] if date_range else resolved_message
            else:
                date_str = dates[0]
            
            sql1_data = results[0].get("result", {}).get("content", {}).get("data", []) if len(results) > 0 else []
            
            total = sum(row.get("CNT", 0) for row in sql1_data)
            instant_count = 0
            permanent_count = 0
            for row in sql1_data:
                if row.get("CHZ_CONDITION") == 1:
                    instant_count = row.get("CNT", 0)
                elif row.get("CHZ_CONDITION") == 0:
                    permanent_count = row.get("CNT", 0)
            
            lines = [f"📋 【早会材料】 日期：{date_str}", ""]
            lines.append("=" * 60)
            lines.append("故障分类统计：")
            lines.append(f"  瞬时性故障：{instant_count} 次")
            lines.append(f"  永久性故障：{permanent_count} 次")
            lines.append(f"  合计：{total} 次")
            if total > 0:
                instant_ratio = instant_count * 100.0 / total
                permanent_ratio = permanent_count * 100.0 / total
                lines.append(f"  瞬时性占比：{instant_ratio:.1f}%")
                lines.append(f"  永久性占比：{permanent_ratio:.1f}%")
            lines.append("=" * 60)
            
            content_text = "\n".join(lines)
            return {
                "status": "success",
                "content": {"data": sql1_data},
                "query_mode": query_mode,
                "time_info": time_info,
                "template_output": content_text,
                "summary": content_text,
                "stream_text": content_text,
                "source": "skill_subprocess"
            }
        
        merged_summary = "\n".join([
            results[i].get("result", {}).get("content", {}).get("data", []) for i in range(len(results))
        ])
        return {
            "status": "success",
            "query_mode": query_mode,
            "results": results,
            "summary": merged_summary,
            "stream_text": merged_summary,
            "source": "skill_subprocess"
        }
    
    def _generate_dm_summary(self, query_content: Any, sql: str) -> str:
        """对 DM 查询结果生成简短分析摘要（2-3句话）"""
        data_list = []
        if isinstance(query_content, list):
            data_list = query_content
        elif isinstance(query_content, dict):
            for key in ["result", "data", "rows", "records", "items", "results"]:
                if key in query_content and isinstance(query_content[key], list):
                    data_list = query_content[key]
                    break

        total = len(data_list)
        if total == 0:
            return "未查询到相关数据。"

        # 从 SQL 提取表名提示
        table_hint = ""
        sql_upper = sql.upper()
        if "AI_ANALYSE_FEEDER" in sql_upper:
            table_hint = "馈线"
        elif "AI_ANALYSE_PB" in sql_upper:
            table_hint = "配变"
        elif "IFA_INDEX" in sql_upper:
            table_hint = "跳闸故障"

        lines = [f"共查询到{total}条{table_hint}记录。" if table_hint else f"共查询到{total}条记录。"]

        # 统计关键指标
        if total > 0 and isinstance(data_list[0], dict):
            high_load_count = 0
            max_loadrate = 0.0
            names = []
            for item in data_list[:50]:
                if isinstance(item, dict):
                    loadrate = item.get("LOADRATE") or item.get("loadrate")
                    if loadrate is not None:
                        try:
                            val = float(loadrate)
                            if val > max_loadrate:
                                max_loadrate = val
                            if val >= 80:
                                high_load_count += 1
                        except (ValueError, TypeError):
                            pass
                    for name_key in ["FEEDER", "FDNAME", "TRANNAME", "DEVNO"]:
                        if item.get(name_key) and len(names) < 3:
                            names.append(str(item[name_key]))

            if high_load_count > 0:
                lines.append(f"其中重过载（≥80%）{high_load_count}条，最大负载率{max_loadrate:.1f}%。")
            if names:
                lines.append(f"涉及设备：{'、'.join(names)}{'等' if total > 3 else ''}。")

        return "".join(lines)

    def _execute_analyst_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """执行分析师技能"""
        message = input_data.get("message", "")
        original_request = input_data.get("original_request", instruction)
        sql_query = input_data.get("sql_query", "")
        query_result = input_data.get("query_result", input_data.get("upstream_result", message))

        logger.info(f"   📊 [{self.agent_id}] 执行数据分析")
        logger.info(f"      ├─ 原始请求: {original_request[:200]}...")
        logger.info(f"      ├─ SQL: {sql_query[:300]}...")
        logger.info(f"      └─ 上一步结果: {str(query_result)[:300]}...")
        if isinstance(query_result, dict) and query_result.get("status") == "error":
            return {"status": "error", "message": query_result.get("message", "上游查询失败"), "source": "upstream_guard"}

        # 截断 query_result，避免 prompt 过长导致 400
        result_str = json.dumps(query_result, ensure_ascii=False, default=str)
        if len(result_str) > 3000:
            result_str = result_str[:3000] + f"\n... [数据已截断，共 {len(result_str)} 字符]"

        # 构建系统提示
        system_prompt = self.config.get("system_prompt", "")
        if not system_prompt:
            logger.error(f"❌ [{self.agent_id}] system_prompt 未配置！请在 config.json 中设置")
            return {"status": "error", "message": f"{self.agent_id} 的 system_prompt 未配置"}

        # 检测 query_mode（从上游 dm_agent 的返回结果中读取）
        query_mode = "normal"
        if isinstance(query_result, dict):
            query_mode = query_result.get("query_mode", "normal")
            # 如果是多表查询结果，说明有聚合数据
            if query_result.get("multi_query"):
                logger.info(f"      ├─ 检测到多表查询结果, query_mode={query_mode}")

        # 根据 query_mode 构建模板指令
        template_instruction = ""
        if query_mode == "zaohui":
            template_instruction = """
【输出模板：早会材料】
请使用以下模板格式输出，数据取自查询结果中的字段：

📋 【早会材料】 日期：{从数据中提取日期}
════════════════════════════════════════════════════
故障分类统计：
  瞬时性故障（CHZ_CONDITION=1）：{数量} 次
  永久性故障（CHZ_CONDITION=0）：{数量} 次
  合计：{总数} 次
  瞬时性占比：{百分比}%
  永久性占比：{百分比}%
════════════════════════════════════════════════════

详细故障列表（如有多个结果表，自动关联 BDZCODE→变电站名称）：
| 时间 | 馈线 | 故障描述 | 跳闸开关 | 重合闸状态 | 损失负荷(MW) |
|------|------|----------|----------|------------|-------------|
| ... | ... | ... | ... | ... | ... |

"""
        elif query_mode == "tiaozha":
            template_instruction = """
【输出模板：跳闸统计】
请使用以下模板格式输出，利用多表查询结果自动关联：
- 结果表1（IFA_INDEX）：跳闸原始记录（BDZCODE, FEEDER, FTIME, DESCRIPTION, CHZST等）
- 结果表2（TX6_DEV_ZWBDZ）：变电站 CODE→OFAR（所属区域）映射
- 结果表3（TX6_DEV_ZWQY）：区域 CODE→DESCRIPTION 映射

📊 【跳闸统计】 日期：{从数据中提取日期范围}
════════════════════════════════════════════════════
| 变电站 | 区域 | 跳闸次数 |
|--------|------|----------|
| ... | ... | ... |
---------------------------------------------
| 合计 | | {总数} |
════════════════════════════════════════════════════

详细跳闸事件列表：
| 时间 | 馈线 | 类型 | 描述 | 开关 | 损失负荷(MW) | 重合闸 |
|------|------|------|------|------|-------------|--------|
| ... | ... | ... | ... | ... | ... | 成功/失败 |

"""
        elif query_mode == "report":
            template_instruction = """
【输出模板：故障简报】
整合三个结果表的数据：
- 馈线重过载表：FEEDER, FDNAME, LOADRATE, DATE
- 配变重过载表：TRANNAME, FEEDER, LOADRATE, DATE  
- 跳闸表IFA_INDEX：FTIME, FEEDER, TYPE, DESCRIPTION, TOPKG

📋 【故障简报】 日期：{日期}

一、馈线重过载（LOADRATE≥80%）
| 馈线 | 线路名称 | 负载率 | 日期 |
|------|----------|--------|------|
| ... | ... | ...% | ... |

二、配变重过载（LOADRATE≥80%）
| 配变名称 | 馈线 | 负载率 | 日期 |
|----------|------|--------|------|
| ... | ... | ...% | ... |

三、跳闸故障
| 时间 | 馈线 | 类型 | 描述 | 开关 |
|------|------|------|------|------|
| ... | ... | ... | ... | ... |

"""
        elif query_mode.startswith("guozai_trend"):
            template_instruction = """
【输出模板：重过载趋势分析】
整合馈线和配变重过载数据，按日期分组统计：
- AI_ANALYSE_FEEDER: 按日期统计馈线重过载次数
- AI_ANALYSE_PB: 按日期统计配变重过载次数

📈 【重过载趋势分析】 时间范围：{从数据提取}
════════════════════════════════════════════════════

当前周期重过载逐日统计：
| 日期 | 馈线重过载次数 | 配变重过载次数 | 合计 |
|------|---------------|---------------|------|
| ... | ... | ... | ... |

趋势判断：{上升/下降/平稳}，最近一天共发生 {总数} 次。

具体分布：
- 馈线重过载：{top3设备列表}
- 配变重过载：{top3设备列表}

分析结论：
{XX区域}过去{N}天重过载次数呈{趋势}，昨日共发生{M}次，主要集中在{时间段}。
"""

        user_prompt = f"""请分析以下查询结果数据，根据 query_mode 选择对应模板输出。

## 原始请求
{original_request}

## SQL
{sql_query}

## 查询结果（结构化 JSON）
{result_str}

{template_instruction}

【通用规则】
1. 只基于查询结果中实际存在的数据输出，没有数据就说"无数据"
2. 如果 query_mode 不是 zaohui/tiaozha/report/guozai_trend（即为 normal 模式），则输出自由格式的分析结论即可
3. 利用结果中的字段含义（见 meta_cache）理解每列数据的业务含义
4. 多表结果自动关联填充（如 BDZCODE→TX6_DEV_ZWBDZ→变电站名称）
5. 注意 CHZ_CONDITION=1 表示瞬时性故障/重合成功，CHZ_CONDITION=0 表示永久性故障/重合失败
6. 数据为空时直接说明"未查询到相关数据"

禁止输出思考过程。必须输出纯JSON：{{"status":"success","agent_id":"analyst_agent","content":"按模板输出的分析内容"}}"""

        # 调用 LLM
        logger.info("🤖 Calling LLM for data analysis...")
        llm_response = self._call_llm(user_prompt, system_prompt)
        
        if llm_response:
            logger.info(f"✅ LLM analysis response received ({len(llm_response)} chars)")
            llm_response = re.sub(r'<think>[\s\S]*?</think>', '', llm_response, flags=re.DOTALL).strip()
            llm_response = re.sub(r'```(?:json)?\s*|\s*```', '', llm_response).strip()
            
            # 尝试解析 LLM 返回的 JSON，提取纯文本内容
            try:
                parsed = json.loads(llm_response)
                if isinstance(parsed, dict) and "content" in parsed:
                    llm_response = parsed["content"]
            except (json.JSONDecodeError, TypeError):
                pass
            
            result = {
                "analysis_result": llm_response,
                "stream_text": llm_response,
                "status": "success",
                "source": "llm"
            }
        else:
            # LLM 调用失败，基于真实数据生成简单统计，绝不写死假数据
            logger.warning("⚠️ LLM call failed, using data-aware fallback")
            fallback_text = self._generate_data_fallback(query_result, original_request)
            result = {
                "analysis_result": fallback_text,
                "stream_text": fallback_text,
                "status": "success",
                "source": "fallback"
            }

        logger.info(f"      ✅ 分析完成")
        return result

    def _generate_data_fallback(self, query_result: Any, original_request: str) -> str:
        """基于真实查询结果生成简单统计（LLM 失败时降级，避免写死假数据）"""
        data_list = []
        if isinstance(query_result, list):
            data_list = query_result
        elif isinstance(query_result, dict):
            for key in ["result", "data", "rows", "records", "items", "results"]:
                if key in query_result and isinstance(query_result[key], list):
                    data_list = query_result[key]
                    break

        total = len(data_list)
        if total == 0:
            return "📊 数据分析结果\n\n查询结果为空，未获取到相关数据。"

        lines = ["📊 数据分析结果", "", f"共查询到 {total} 条记录。"]

        # 统计高负载
        high_load_count = 0
        max_loadrate = 0.0
        names = []
        if total > 0 and isinstance(data_list[0], dict):
            for item in data_list[:50]:
                if isinstance(item, dict):
                    loadrate = item.get("LOADRATE") or item.get("loadrate")
                    if loadrate is not None:
                        try:
                            val = float(loadrate)
                            if val > max_loadrate:
                                max_loadrate = val
                            if val >= 80:
                                high_load_count += 1
                        except (ValueError, TypeError):
                            pass
                    for name_key in ["FEEDER", "FDNAME", "TRANNAME", "DEVNO"]:
                        if item.get(name_key) and len(names) < 3:
                            names.append(str(item[name_key]))

        if high_load_count > 0:
            lines.append(f"其中高负载（≥80%）记录 {high_load_count} 条，最大负载率{max_loadrate:.1f}%。")
        if names:
            lines.append(f"涉及设备：{'、'.join(names)}{'等' if total > 3 else ''}。")

        return "\n".join(lines)
    
    def _execute_reporter_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """执行报告员技能"""
        analysis_data = input_data.get("analysis_result", input_data.get("result", "无数据"))
        original_request = input_data.get("original_request", instruction)
        sql_query = input_data.get("sql_query", "")
        execution_flow = input_data.get("execution_flow", [])

        logger.info(f"   📝 [{self.agent_id}] 执行报告生成")
        logger.info(f"      ├─ 原始请求: {original_request[:200]}...")
        logger.info(f"      ├─ SQL: {sql_query[:300]}...")
        logger.info(f"      ├─ 输入数据类型: {type(analysis_data).__name__}")
        logger.info(f"      ├─ 执行流程: {execution_flow}")
        if isinstance(analysis_data, str):
            logger.info(f"      └─ 数据摘要: {analysis_data[:100]}...")
        else:
            logger.info(f"      └─ 数据键: {list(analysis_data.keys()) if isinstance(analysis_data, dict) else 'N/A'}")

        # 错误检查
        if isinstance(analysis_data, dict) and analysis_data.get("status") == "error":
            return {"status": "error", "message": analysis_data.get("message", "上游分析失败"), "source": "upstream_guard"}

        # 构建系统提示
        system_prompt = self.config.get("system_prompt", "")
        if not system_prompt:
            logger.error(f"❌ [{self.agent_id}] system_prompt 未配置！请在 config.json 中设置")
            return {"status": "error", "message": f"{self.agent_id} 的 system_prompt 未配置"}

        # 构建包含 execution_flow 的用户提示
        user_prompt = f"""请根据以下数据生成结构化总结：

## 原始请求
{original_request}

## SQL
{sql_query}

## 执行流程
{execution_flow}

## 数据和分析结果
{analysis_data}

请生成结构化总结，200-500字，包含核心发现、关键数据摘要和结论。"""

        # 调用 LLM
        logger.info("🤖 Calling LLM for report generation...")
        llm_response = self._call_llm(user_prompt, system_prompt)

        if llm_response:
            logger.info(f"✅ LLM report generated ({len(llm_response)} chars)")
            llm_response = re.sub(r'<think>[\s\S]*?</think>', '', llm_response, flags=re.DOTALL).strip()
            
            # 尝试解析 LLM 返回的 JSON，提取纯文本内容
            # 注意：不再删除所有 ```，只处理 json 代码块，保留 mermaid 代码块
            try:
                cleaned = re.sub(r'^```json\s*', '', llm_response, flags=re.MULTILINE)
                json_match = re.search(r'\{[\s\S]*\}', cleaned)
                if json_match:
                    parsed = json.loads(json_match.group())
                    if isinstance(parsed, dict) and "content" in parsed:
                        llm_response = parsed["content"]
            except (json.JSONDecodeError, TypeError):
                pass
            
            # 检查是否包含 Mermaid 流程图
            if "```mermaid" not in llm_response:
                logger.warning("⚠️ LLM未生成流程图，使用兜底方案")
                flowchart = self._generate_fallback_flowchart(original_request, execution_flow)
                llm_response += "\n\n## 解决流程图\n" + flowchart
            
            # Mermaid 流程图格式验证与自动修复
            try:
                from src.utils.mermaid_validator import ensure_mermaid_format
                llm_response = ensure_mermaid_format(llm_response)
            except ImportError:
                logger.warning("mermaid_validator not found, skip mermaid validation")
            
            return {
                "report_content": llm_response,
                "stream_text": llm_response,
                "status": "success",
                "source": "llm"
            }

        # LLM 调用失败，透传上游数据，不写死假数据
        logger.warning("⚠️ LLM call failed, using data-aware template fallback")
        if isinstance(analysis_data, str):
            report_content = analysis_data
        else:
            report_content = json.dumps(analysis_data, ensure_ascii=False, default=str)[:500]
        
        # 添加兜底流程图
        flowchart = self._generate_fallback_flowchart(original_request, execution_flow)
        report_content += "\n\n## 解决流程图\n" + flowchart
        
        return {
            "report_content": f"查询结果：{report_content}",
            "stream_text": f"查询结果：{report_content}",
            "status": "success",
            "source": "template"
        }
    
    def _generate_fallback_flowchart(self, original_request: str, execution_flow: list) -> str:
        """LLM驱动的流程图生成，动态生成详细步骤描述"""
        # 生成执行链描述
        flow_desc = ""
        if execution_flow:
            agents = [step.get("agent", "") for step in execution_flow]
            flow_desc = f"执行链: {' → '.join(agents)}"
        
        # 使用LLM生成流程图步骤描述
        prompt = f"""请为以下查询生成详细的流程图步骤描述（每个步骤2-3句话）：
查询：{original_request}
执行流程：{flow_desc}

请按以下格式输出5个步骤的详细描述：
1. 信号接收：[详细描述]
2. 意图识别：[详细描述]
3. 知识检索：[详细描述]
4. 逻辑推理：[详细描述]
5. 结论生成：[详细描述]

要求：
- 每个描述至少20字，包含具体的处理内容
- 语言简洁专业，符合电网调度场景
- 逻辑推理步骤中请体现实际执行链"""
        
        llm_response = self._call_llm(prompt, "你是流程图步骤描述专家，擅长为电网调度任务生成详细的处理步骤描述")
        
        # 解析LLM返回的描述
        descriptions = ["", "", "", "", ""]
        if llm_response:
            lines = llm_response.strip().split('\n')
            for i, line in enumerate(lines[:5]):
                match = re.search(r'[\d一二三四五]+\.\s*[\u4e00-\u9fa5]+\s*：\s*(.+)', line)
                if match:
                    descriptions[i] = match.group(1).strip()[:50]  # 限制长度
        
        # 如果LLM没有生成有效的描述，使用默认描述
        if not descriptions[0]:
            descriptions = [
                f"收到用户查询请求：{original_request[:30]}...",
                "分析用户需求，识别查询意图和目标",
                "检索电网相关知识库和历史数据",
                f"进行逻辑推理分析{flow_desc}",
                "生成最终报告并输出结果"
            ]
        
        mermaid = """```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'background': '#0A2A44',
    'primaryColor': '#4A9EFF',
    'primaryTextColor': '#FFFFFF',
    'primaryBorderColor': '#8EC8FF',
    'lineColor': '#6AB0FF',
    'secondaryColor': '#1E4468',
    'tertiaryColor': '#002A4F',
    'clusterBkg': '#0A2A44',
    'edgeLabelBackground':'#0A2A44'
  }
}}%%
flowchart LR
    Start([开始]) --> A[信号接收]
    A -->|""" + descriptions[0] + """| B[意图识别]
    B -->|""" + descriptions[1] + """| C[知识检索]
    C -->|""" + descriptions[2] + """| D[逻辑推理]
    D -->|""" + descriptions[3] + """| E[结论生成]
    E -->|""" + descriptions[4] + """| End([结束])
```"""
        
        return mermaid
    
    def _execute_file_manager_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
        """执行文件管理员技能"""
        report_content = input_data.get("report_content", input_data.get("result", "无内容"))
        
        logger.info(f"   📁 [{self.agent_id}] 执行文件保存")
        if isinstance(report_content, str):
            logger.info(f"      ├─ 内容长度: {len(report_content)} 字符")
        else:
            logger.info(f"      ├─ 内容类型: {type(report_content).__name__}")
            report_content = str(report_content)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = PROJECT_ROOT / "data" / "reports"
        filename = f"grid_load_report_{timestamp}.md"
        filepath = output_dir / filename

        output_dir.mkdir(parents=True, exist_ok=True)
        filepath.write_text(report_content, encoding='utf-8')
        
        filesize = filepath.stat().st_size
        logger.info(f"      ├─ 保存路径: {filepath}")
        logger.info(f"      └─ 文件大小: {filesize} 字节")
        
        # 使用 LLM 生成文件摘要
        summary = self._generate_file_summary(report_content, filepath.name)
        
        return {
            "filepath": str(filepath),
            "filesize": filesize,
            "status": "success",
            "message": f"报告已保存: {filepath}",
            "summary": summary,
            "source": "llm" if summary else "template"
        }
    
    def _generate_file_summary(self, content: str, filename: str) -> str:
        """使用 LLM 生成文件摘要"""
        logger.info(f"   📝 [{self.agent_id}] 生成文件摘要")
        
        system_prompt = self.config.get("summary_prompt", "提取文档关键信息，生成100字以内简洁摘要。")
        
        user_prompt = f"""请为以下文档生成简洁的摘要（100字以内）：

文档名称：{filename}

文档内容：
{content[:3000]}

请生成摘要。"""

        try:
            summary = self._call_llm(user_prompt, system_prompt)
            if summary:
                logger.info(f"   ✅ 摘要生成成功 ({len(summary)} 字符)")
                return summary
        except Exception as e:
            logger.warning(f"   ⚠️ 摘要生成失败: {e}")
        
        return None
    
    def _extract_intent_tags(self, instruction: str):
        """
        从指令中提取意图标签
        """
        tags = []
        instruction_lower = instruction.lower()
        
        # 仅对sql_generator_agent添加意图标签
        if self.agent_id != "sql_generator_agent":
            return tags
            
        # 故障简报/日报相关
        if any(keyword in instruction_lower for keyword in ["简报", "日报", "故障简报"]):
            tags.append("fault_report")
            
        # 馈线重过载相关
        if any(keyword in instruction_lower for keyword in ["馈线", "feeder", "线路"]) and ("过载" in instruction_lower or "重载" in instruction_lower):
            tags.append("feeder_overload")
            
        # 配变重过载相关
        if any(keyword in instruction_lower for keyword in ["配变", "变压器", "pb"]) and ("过载" in instruction_lower or "重载" in instruction_lower):
            tags.append("pb_overload")
            
        # 区域统计相关
        if any(keyword in instruction_lower for keyword in ["区域", "area", "各区域", "统计"]):
            tags.append("area_statistics")
            
        # 转电操作相关
        if any(keyword in instruction_lower for keyword in ["转电", "转供", "负荷转移"]):
            tags.append("transformer_operation")
            
        # 图形查询相关
        if any(keyword in instruction_lower for keyword in ["接线图", "单线图", "svg", "gis", "拓扑图"]):
            tags.append("graph_query")
            
        return tags
    
    def _learn_from_execution(self, instruction: str, result: Any, start_time: float,
                              user_id: str = ""):
        """
        从执行中学习，更新长期记忆（按用户隔离）
        
        Args:
            instruction: 执行指令
            result: 执行结果
            start_time: 开始时间
            user_id: 当前请求的用户 ID
        """
        execution_time_ms = int((time.time() - start_time) * 1000)
        success = isinstance(result, dict) and result.get("status") == "success"
        mm = self._get_memory_mgr(user_id)
        
        # 1. 记录成功模式
        if success:
            pattern = f"指令:{instruction[:50]}..., 执行成功, 耗时:{execution_time_ms}ms"
            # 提取意图标签
            intent_tags = self._extract_intent_tags(instruction)
            all_tags = [self.agent_id, "execution"] + intent_tags
            mm.add_to_long_term(
                "successful_patterns",
                pattern,
                tags=all_tags
            )
            logger.debug(f"📚 记录成功模式: {pattern[:80]}...")
        
        # 2. 记录专业知识补充
        if isinstance(result, dict) and result.get("analysis_result"):
            # Analyst的分析结果可以作为专业知识存储
            # 提取意图标签
            intent_tags = self._extract_intent_tags(instruction)
            all_tags = [self.agent_id, "analysis"] + intent_tags
            mm.add_to_long_term(
                "professional_knowledge",
                f"分析任务结果: {result.get('analysis_result', '')[:200]}",
                tags=all_tags
            )


def serve(agent_id: str, zk_hosts: str):
    """启动gRPC服务"""
    logger.info(f"🚀 正在启动 {agent_id}...")
    
    # 1. 分配端口（自动避免冲突）
    port = get_available_port()
    logger.info(f"🎯 使用端口: {port}")
    
    # 2. 连接到Zookeeper
    registry = ZKServiceRegistry(zk_hosts=zk_hosts)
    if not registry.connect():
        logger.error("❌ Zookeeper连接失败")
        release_port(port)
        return
    
    # 3. 创建gRPC服务器
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    dfecrab_pb2_grpc.add_AgentServiceServicer_to_server(
        AgentServiceImpl(agent_id), server
    )
    
    # 4. 绑定端口并启动
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    
    # 5. 注册服务到Zookeeper（★ 命名统一：全部 worker 一律注册为 worker_agent；
    #    旧 default_agent 类型已废弃——dfecrab 由 metadata.agent_id 标识，agent_type 由 gateway 按 agent_id 推导）
    hostname = socket.gethostname()
    service_id = f"{agent_id}_{hostname}_{int(time.time())}_{uuid4().hex[:6]}"
    service_type = "worker_agent"
    
    registry.register_service(
        service_name=service_type,
        service_id=service_id,
        host="127.0.0.1",
        port=port,
        metadata={
            "agent_id": agent_id,
            "version": "1.0.0"
        }
    )
    
    logger.info(f"✅ {agent_id} 已启动")
    logger.info(f"   📍 地址: 127.0.0.1:{port}")
    logger.info(f"   📝 Zookeeper: {zk_hosts}")
    logger.info(f"   🆔 服务ID: {service_id}")
    
    # 6. 启动 ZK 注册守护线程（每10秒检查一次，断连后自动重注册）
    logger.info("🔄 启动 ZK 注册守护线程（每 10 秒检查一次）...")
    
    def _worker_watchdog():
        instance_path = f"{registry.base_path}/{service_type}/{service_id}"
        while True:
            try:
                if registry.zk and registry.zk.connected:
                    if not registry.zk.exists(instance_path):
                        logger.warning("⚠️ ZK 临时节点已丢失，重新注册...")
                        registry.register_service(
                            service_name=service_type,
                            service_id=service_id,
                            host="127.0.0.1",
                            port=port,
                            metadata={"agent_id": agent_id, "version": "1.0.0"}
                        )
                else:
                    logger.debug("⏳ ZK 未连接，等待重连...")
            except Exception as e:
                logger.debug(f"⏳ 注册守护线程异常: {e}")
            time.sleep(10)
    
    t = threading.Thread(target=_worker_watchdog, daemon=True)
    t.start()
    
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info(f"\n👋 正在停止 {agent_id}...")
        registry.deregister_service(service_type, service_id)
        release_port(port)
        server.stop(0)
        registry.close()
        logger.info(f"✅ {agent_id} 已停止")


def main():
    from config.config_loader import config as _cfg
    parser = argparse.ArgumentParser(description="Agent gRPC Service")
    parser.add_argument("--agent-id", required=True, help="Agent ID (如: analyst_agent)")
    parser.add_argument("--zk-hosts", default=_cfg.zk_hosts, help="Zookeeper地址")
    args = parser.parse_args()
    
    serve(args.agent_id, args.zk_hosts)


if __name__ == "__main__":
    main()
