"""
Agent 调用器 - 主程序
功能：调用 Agent API，记录完整的 Agent 调用过程，用于后续微调或强化学习
增强：全链路日志、trace追踪、并发工具明细、异常完整堆栈，输出至 agent-task.log
"""

import json
import logging
import os
import re
import sys
import traceback
import uuid
import asyncio
from datetime import datetime
from typing import List, Dict, Any, AsyncGenerator, Union, Optional, Tuple
from openai import OpenAI, AsyncOpenAI
# 请保证 config、tools 模块正常存在
from .config import config
from .tools import TOOLS, execute_tool
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextvars import ContextVar

# ===================== 协程上下文，存储当前请求追踪ID（解决FastAPI并发日志串扰） =====================
TRACE_ID: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)

def get_trace_id() -> str:
    tid = TRACE_ID.get()
    if not tid:
        tid = str(uuid.uuid4())
        TRACE_ID.set(tid)
    return tid


def bind_trace_id(trace_id: Optional[str] = None) -> str:
    """为当前请求或任务绑定新的 trace_id。"""
    trace_id = trace_id or str(uuid.uuid4())
    TRACE_ID.set(trace_id)
    return trace_id


def _preview_text(content: Any, limit: Optional[int] = None) -> str:
    """统一截断日志内容，避免大段文本影响排查。"""
    if content is None:
        return ""
    text = str(content)
    preview_limit = limit or getattr(config, "TASK_LOG_PREVIEW_CHARS", 800)
    return text[:preview_limit] + ("..." if len(text) > preview_limit else "")

# ============================================================
# 全局日志配置 —— 输出到 agent-task.log
# ============================================================
class TraceFormatter(logging.Formatter):
    """自定义日志格式，自动追加trace_id"""
    def format(self, record):
        tid = get_trace_id()
        setattr(record, "trace_id", tid)
        return super().format(record)

def _setup_task_logger() -> logging.Logger:
    """创建并配置 agent-task 文件日志记录器"""
    logger = logging.getLogger("agent-task")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 不向根 logger 传递，避免重复输出

    # 避免重复添加 handler（多次 import 时防护）
    if logger.handlers:
        return logger

    # 任务日志使用独立目录 agent_logs，与调用记录 JSON 目录 logs 区分开
    task_log_dir = getattr(config, "TASK_LOG_DIR", None)
    if not task_log_dir:
        base_log_dir = getattr(config, "LOG_DIR", os.path.join(os.path.dirname(__file__), "logs"))
        task_log_dir = os.path.join(os.path.dirname(base_log_dir), "agent_logs")
    os.makedirs(task_log_dir, exist_ok=True)

    log_filename = getattr(config, "TASK_LOG_FILE", "agent-task.log")
    log_path = os.path.join(task_log_dir, log_filename)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    fmt = TraceFormatter(
        "[%(asctime)s][%(levelname)s][%(name)s][%(trace_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 同时输出到控制台，方便开发调试
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger

task_logger = _setup_task_logger()

class AgentCallLogger:
    """Agent 调用日志记录器 - 详细记录每次调用的全过程"""

    def __init__(self):
        self.call_history = []  # 存储所有调用记录
        trace_id = get_trace_id()
        self.current_session = {
            "trace_id": trace_id,
            "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "start_time": datetime.now().isoformat(),
            "conversations": []
        }

    def log_user_input(self, user_input: str):
        """记录用户输入"""
        print(f"\n{'='*60}")
        print(f"用户输入: {user_input}")
        print(f"{'='*60}\n")
        task_logger.info("[处理告警信息] %s", _preview_text(user_input))

        self.current_session["conversations"].append({
            "type": "user_input",
            "timestamp": datetime.now().isoformat(),
            "content": user_input
        })

    def log_api_request(self, request_data: Dict[str, Any]):
        """记录发送给 API 的请求数据"""
        print(f"\n发送给 Agent API 的请求:")
        print(f"模型: {request_data.get('model', 'N/A')}")
        print(f"消息历史长度: {len(request_data.get('messages', []))} 条")
        task_logger.info(
            "[流程步骤] 准备调用大模型 | model=%s | message_count=%d | temperature=%s | max_tokens=%s",
            request_data.get("model", "N/A"),
            len(request_data.get("messages", [])),
            request_data.get("temperature", "N/A"),
            request_data.get("max_tokens", "N/A")
        )

        # 打印最近的消息内容（最多显示最后3条）
        messages = request_data.get('messages', [])
        print(f"\n 最近消息内容:")
        for msg in messages[-3:]:
            # 处理可能是字典或 Pydantic 对象的消息
            if hasattr(msg, 'model_dump'):
                # 是 Pydantic 对象，转换为字典
                msg_dict = msg.model_dump()
            elif isinstance(msg, dict):
                # 已经是字典
                msg_dict = msg
            else:
                # 未知类型，跳过
                continue

            role = msg_dict.get('role', 'unknown')
            content = msg_dict.get('content', '')
            if content:
                content_preview = content[:100] + '...' if len(content) > 100 else content
                print(f"[{role}]: {content_preview}")
                task_logger.info("[流程步骤] 最近消息 | role=%s | content=%s", role, _preview_text(content, 200))
            elif msg_dict.get('tool_calls'):
                print(f"[{role}]: [调用了 {len(msg_dict['tool_calls'])} 个工具]")
            elif role == 'tool':
                print(f"[{role}]: [工具执行结果]")

        # 将请求数据中的 Pydantic 对象转换为字典，以便保存为 JSON
        serializable_request_data = {
            "model": request_data.get("model"),
            "temperature": request_data.get("temperature"),
            "max_tokens": request_data.get("max_tokens"),
            "messages": [
                msg.model_dump() if hasattr(msg, 'model_dump') else msg
                for msg in request_data.get("messages", [])
            ],
            "tools": request_data.get("tools", [])
        }

        self.current_session["conversations"].append({
            "type": "api_request",
            "timestamp": datetime.now().isoformat(),
            "request_data": serializable_request_data
        })

    def log_api_response(self, response_data: Dict[str, Any]):
        """记录 API 返回的原始响应数据"""
        print(f"\nQwen API 原始响应:")
        print(f"响应 ID: {response_data.get('id', 'N/A')}")
        print(f"模型: {response_data.get('model', 'N/A')}")
        task_logger.info(
            "[流程步骤] 大模型响应返回 | response_id=%s | model=%s",
            response_data.get("id", "N/A"),
            response_data.get("model", "N/A")
        )

        if response_data.get('usage'):
            usage = response_data['usage']
            task_logger.info("[流程步骤] token消耗 | usage=%s", _preview_text(usage, 300))

        if response_data.get('choices'):
            choice = response_data['choices'][0]
            message = choice.get('message', {})
            print(f"完成原因: {choice.get('finish_reason', 'N/A')}")
            task_logger.info("[流程步骤] 模型完成原因 | finish_reason=%s", choice.get("finish_reason", "N/A"))

            if message.get('content'):
                content_preview = message['content'][:150] + '...' if len(message['content']) > 150 else message['content']
                print(f"响应内容: {content_preview}")
                task_logger.info("[流程步骤] 模型输出预览 | content=%s", _preview_text(message["content"]))

            if message.get('tool_calls'):
                print(f"工具调用: {len(message['tool_calls'])} 个")
                for tc in message['tool_calls']:
                    print(f"- {tc.get('function', {}).get('name', 'unknown')}")

        self.current_session["conversations"].append({
            "type": "api_response",
            "timestamp": datetime.now().isoformat(),
            "response_data": response_data
        })

    def log_agent_thinking(self, message: Dict[str, Any]):
        """记录 Agent 思考过程（第一次响应）"""
        print(f"\nAgent 正在思考...")

        if message.get("content"):
            print(f"思考内容: {message['content'][:300]}")
            task_logger.info("[流程步骤] 模型推理输出 | content=%s", _preview_text(message["content"]))

        self.current_session["conversations"].append({
            "type": "agent_thinking",
            "timestamp": datetime.now().isoformat(),
            "content": message.get("content", ""),
            "model": message.get("model", ""),
            "role": message.get("role", "")
        })

    def log_tool_call(self, tool_call: Dict[str, Any], tool_result: str):
        """记录工具调用详情"""
        tool_name = tool_call.function.name
        tool_args = json.loads(tool_call.function.arguments)

        print(f"\nAgent 决定调用工具:")
        print(f"工具名称: {tool_name}")
        print(f"工具参数: {json.dumps(tool_args, ensure_ascii=False, indent=6)}")
        task_logger.info(
            "[流程步骤] 工具Observation入模 | tool=%s | args=%s | observation=%s",
            tool_name,
            _preview_text(json.dumps(tool_args, ensure_ascii=False), 300),
            _preview_text(tool_result)
        )

        self.current_session["conversations"].append({
            "type": "tool_call",
            "timestamp": datetime.now().isoformat(),
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_call_id": tool_call.id,
            "tool_result": tool_result
        })

    def log_final_response(self, response_content: str, usage: Dict[str, Any] = None):
        """记录 Agent 最终响应"""
        print(f"\n{'='*60}")
        print(f"Agent 最终回复:")
        print(f"{response_content}")
        print(f"{'='*60}")
        task_logger.info("[流程步骤] 最终回复生成 | content=%s", _preview_text(response_content))
        if usage:
            task_logger.info("[流程步骤] 最终回复token消耗 | usage=%s", _preview_text(usage, 300))

        self.current_session["conversations"].append({
            "type": "final_response",
            "timestamp": datetime.now().isoformat(),
            "content": response_content,
            "usage": usage
        })

    def save_session(self):
        """保存当前会话到文件"""
        if not config.SAVE_CALL_LOGS:
            return

        self.current_session["end_time"] = datetime.now().isoformat()

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = config.LOG_FILE_FORMAT.format(timestamp=timestamp)
        filepath = os.path.join(config.LOG_DIR, filename)

        # 保存为 JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.current_session, f, ensure_ascii=False, indent=2)

        print(f"\n会话记录已保存到: {filepath}")
        task_logger.info(f"会话JSON记录持久化完成，路径: {filepath}")

    def reset_session(self):
        """重置会话（用于新的对话）"""
        trace_id = get_trace_id()
        self.current_session = {
            "trace_id": trace_id,
            "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "start_time": datetime.now().isoformat(),
            "conversations": []
        }


class QwenAgent:
    """Qwen Agent 调用器"""

    @staticmethod
    def is_operation_alarm(alert_content: str) -> bool:
        """
        基于规则判断告警信号是否为操作告警（用于阶段1预分类）。

        满足 全部 以下 3 条判定为操作告警：
        1. 告警信号有对应线路（格式：xx站 Fxx，例如 平乐站 F70）
        2. 告警信号描述包含正向关键词之一：事故分闸 / 合闸 / 动作
        3. 告警信号描述 不 包含负向关键词之一：母线失压 / 全站失压 / 重合闸 / 母线馈线保护

        参数:
            alert_content: 告警信号原文（user_input）
        返回: True=操作告警(阶段2用MODEL), False=非操作告警(阶段2用MODEL2)
        """
        if not alert_content:
            return False

        # 条件1：告警内容同时包含「xx站」片段 与（馈线 Fxx 或 母线 xxM）片段（二者可被其他文字隔开，不需紧邻）
        has_station = re.search(r'\S+站', alert_content) is not None
        has_feeder = re.search(r'F\d+', alert_content) is not None
        has_bus = re.search(r'\d+M', alert_content) is not None
        if not (has_station and (has_feeder or has_bus)):
            return False

        # 条件2：包含正向关键词
        positive_keywords = ['事故分闸', '合闸', '动作']
        has_positive = any(kw in alert_content for kw in positive_keywords)
        if not has_positive:
            return False

        # 条件3：不包含负向关键词
        negative_keywords = ['母线失压', '全站失压', '重合闸', '母线馈线保护']
        has_negative = any(kw in alert_content for kw in negative_keywords)
        if has_negative:
            return False

        return True

    @staticmethod
    def extract_alert_content(user_input: str) -> str:
        """优先从 user_input JSON 中提取 alert_content，失败则回退到原始输入。"""
        try:
            data = json.loads(user_input)
            if isinstance(data, dict):
                return data.get("alert_content") or user_input
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return user_input

    @staticmethod
    def is_accident_summary_signal(alert_content: str) -> bool:
        """事故总信号短路规则：只要 alert_content 包含“事故总”即可直接判定。"""
        return bool(alert_content) and ("事故总" in alert_content)

    @staticmethod
    def get_accident_summary_direct_result() -> Tuple[str, str]:
        """返回事故总信号的固定 Thought 和 Final Answer。"""
        thought = (
            '1.用户传来了一个告警信号,"alert_content"包含关键字"事故总"，'
            '直接判断故障类型为"事故总"信号。'
            '2.根据事故总的判断规则，事故总信号直接判断为正常信号。'
        )
        final_answer = (
            '"alert_content"包含关键字"事故总"，判断当前信号为事故总信号。'
            '事故总信号直接判断为正常信号，所以判断该信号为正常信号。'
        )
        return thought, final_answer

    @staticmethod
    def get_deepseek_model2() -> str:
        """兜底访问 DEEPSEEK_MODEL2，缺省时回退到 DEEPSEEK_MODEL，避免 AttributeError。"""
        return getattr(config, "DEEPSEEK_MODEL2", None) or config.DEEPSEEK_MODEL

    @staticmethod
    def select_model_by_alert(alert_content: str) -> str:
        """
        根据告警内容选择阶段2正式研判模型：
          操作告警 → MODEL；非操作告警 → MODEL2。
        同时写入阶段1分类日志。
        """
        if QwenAgent.is_operation_alarm(alert_content):
            model = config.DEEPSEEK_MODEL
            task_logger.info("[阶段1-规则预分类] 判定=操作告警 | 阶段2模型=%s", model)
            return model
        else:
            model = QwenAgent.get_deepseek_model2()
            task_logger.info("[阶段1-规则预分类] 判定=非操作告警 | 阶段2模型=%s", model)
            return model

    def __init__(self):
        # 验证配置
        config.validate()

        # 初始化 OpenAI 客户端（Qwen 兼容 OpenAI API）
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY or "sk-local-deployment",
            base_url=config.DEEPSEEK_BASE_URL
        )
        import httpx
        self.async_client = AsyncOpenAI(
            api_key=config.DEEPSEEK_API_KEY or "sk-local-deployment",
            base_url=config.DEEPSEEK_BASE_URL,
            http_client=httpx.AsyncClient(trust_env=False)
        )

        # 初始化日志记录器
        self.logger = AgentCallLogger()

        # 消息历史
        self.messages = [
            {"role": "system", "content": config.SYSTEM_PROMPT}
        ]

        task_log_dir = getattr(config, "TASK_LOG_DIR", os.path.join(os.path.dirname(__file__), "agent_logs"))
        task_log_file = os.path.join(task_log_dir, getattr(config, "TASK_LOG_FILE", "agent-task.log"))

        _model2 = QwenAgent.get_deepseek_model2()
        print(" Agent 初始化成功")
        print(f"阶段1：规则预分类（线路+正向关键词+负向关键词排除）")
        print(f"  → 操作告警  判定条件：含【xx站 Fxx】+【事故分闸/合闸/动作】 且 不含【母线失压/全站失压/重合闸/母线馈线保护】")
        print(f"  → 事故总：含【事故总】直接短路，固定研判输出")
        print(f"阶段2-正式研判模型：")
        print(f"  - 操作告警  使用: {config.DEEPSEEK_MODEL}")
        print(f"  - 非操作告警 使用: {_model2}")
        print(f"可用工具: {len(TOOLS)} 个")
        print(f"调用记录目录: {config.LOG_DIR}")
        print(f"任务日志文件: {task_log_file}")

        task_logger.info("=" * 60)
        task_logger.info("QwenAgent 初始化成功")
        task_logger.info(
            "阶段1:事故总短路 + 规则预分类(线路+正关键词-负关键词) | 阶段2操作告警模型=%s | 阶段2非操作告警模型=%s | 可用工具=%d | 调用记录=%s | 任务日志=%s",
            config.DEEPSEEK_MODEL,
            _model2,
            len(TOOLS),
            config.LOG_DIR,
            task_log_file
        )
        task_logger.info("=" * 60)

    def _format_ticket_observation(self, results: List[str], station: str, line_name: str) -> str:
        """
        格式化操作票查询结果。

        参数:
            results: 工具执行结果列表
            station: 工具调用时传入的站点名称（如"牛湖站"）
            line_name: 工具调用时传入的馈线名称（如"F19"）

        处理逻辑：
        1. 记录查询到的操作票数量
        2. 判断是否为停电票
        3. 如果有停电票，检查 operator 中是否有"断开该station该line_name的开关"字样
        4. 如果没有该字样，记录停电票的 code
        5. 如果没有停电票，检查 operaTask 中是否有"合环转供电"字样，有则记录 code
        """
        # 存储统计信息
        stats = {
            'count': 0,
            'has_blackout': False,
            'missing_codes': [],  # 缺失断开操作的停电票code列表
            'hehuan_codes': []    # 合环转供电的code列表
        }

        for res_str in results:
            try:
                # 尝试解析结果为 JSON
                data = json.loads(res_str)
                # 如果是列表，处理列表；如果是字典，转为列表处理
                items = data if isinstance(data, list) else [data]

                for item in items:
                    if isinstance(item, dict):
                        # 获取操作票类型、编号和任务描述
                        op_type = item.get("operaType", "")
                        code = item.get("code", "")
                        opera_task = item.get("operaTask", "")
                        operators = item.get("operator", [])

                        # 统计操作票数量
                        stats['count'] += 1

                        # 处理停电票
                        if op_type == "停电票":
                            stats['has_blackout'] = True

                            # 检查 operator 中是否有"断开该station该line_name的开关"字样
                            has_disconnect = False
                            # 构建断开操作的匹配模式
                            disconnect_pattern = rf"断开.*{station}.*{line_name}.*开关"

                            for op_item in operators:
                                if isinstance(op_item, dict):
                                    operator_desc = op_item.get("operator", "")
                                    if re.search(disconnect_pattern, operator_desc):
                                        has_disconnect = True
                                        break

                            # 如果没有找到断开操作，记录该停电票的编号
                            if not has_disconnect and code:
                                stats['missing_codes'].append(code)

                        # 处理非停电票，检查是否有合环转供电
                        else:
                            if "合环转供电" in opera_task and code:
                                stats['hehuan_codes'].append(code)

            except Exception as e:
                print(f"解析操作票数据失败: {e}")
                task_logger.error(f"解析操作票数据异常: {str(e)} \n{traceback.format_exc()[:800]}")
                continue

        if stats['count'] == 0:
            text = f"{station}{line_name}查到操作票数量为0"
            obs = {"opera_ticket": text}
            return f"Observation:{json.dumps(obs, ensure_ascii=False)}"

        # 构建输出字符串
        part = f"{station}{line_name}查到操作票数量为{stats['count']}"

        if stats['has_blackout']:
            part += '，包含"停电票"'
            # 只有当存在缺失断开操作的停电票时，才输出code字段
            if stats['missing_codes']:
                codes_str = '", "'.join(stats['missing_codes'])
                part += f'，"code"字段为["{codes_str}"]'
        else:
            part += '，不包含"停电票"'
            # 添加合环转供电的操作票编号
            if stats['hehuan_codes']:
                codes_str = '", "'.join(stats['hehuan_codes'])
                part += f'，"code"字段为["{codes_str}"]'

        obs = {"opera_ticket": part}
        return f"Observation:{json.dumps(obs, ensure_ascii=False)}"

    def _format_diaodulog_observation(self, results: List[str], station: str) -> str:
        """
        格式化调度日志查询结果。

        参数:
            results: 工具执行结果列表
            station: 站点名称（如"新督变电站"）

        处理逻辑（逐条日志独立判断，任意一条满足即判定满足）：
        1. logType = "站内日志"
        2. eventdesc 同时包含：XX变电站(站) + 封锁全站电压 + 封锁全站信号
        3. isEnd = "否"
        4. 该条日志的 logContent 中，不存在 "解除全站电压" 且不存在 "解除全站信号"
        5. 如果存在任意一条满足全部条件，则输出满足条件的 Observation
        6. 如果所有日志都不满足或结果为空，输出不满足条件的 Observation
        """
        # 提取场站名称（去掉"变电站"等后缀）
        station_name = station
        if station_name.endswith("变电站"):
            station_name = station_name[:-3]
        elif station_name.endswith("站"):
            station_name = station_name[:-1]

        for res_str in results:
            try:
                data = json.loads(res_str)
                items = data if isinstance(data, list) else [data]

                for item in items:
                    if isinstance(item, dict):
                        log_type = item.get("logType", "")
                        event_desc = item.get("eventdesc", "")
                        is_end = item.get("isEnd", "")
                        log_data = item.get("logdata", [])

                        # 检查条件1: logType = "站内日志"
                        if log_type != "站内日志":
                            continue

                        # 检查条件2: eventdesc 同时包含站点名称、封锁全站电压、封锁全站信号
                        if station not in event_desc:
                            continue
                        if "封锁全站电压" not in event_desc:
                            continue
                        if "封锁全站信号" not in event_desc:
                            continue

                        # 检查条件3: isEnd = "否"
                        if is_end != "否":
                            continue

                        # 检查条件4: 所有 logContent 中 不存在 "解除全站电压" 且 不存在 "解除全站信号"
                        has_release = False
                        for log_item in log_data:
                            if isinstance(log_item, dict):
                                log_content = log_item.get("logContent", "")
                                if "解除全站电压" in log_content or "解除全站信号" in log_content:
                                    has_release = True
                                    break

                        if not has_release:
                            # 满足所有条件
                            return f"Observation:{{{station_name}站调度日志满足以下条件：日志类型是站内日志，包含封锁全站电压和封锁全站信号的内容且isEnd为否，且日志细节不存在解除全站电压和解除全站信号}}"

            except Exception as e:
                print(f"解析调度日志数据失败: {e}")
                task_logger.error(f"解析调度日志异常: {str(e)} \n{traceback.format_exc()[:800]}")
                continue

        # 不满足条件或结果为空
        text = f"{station_name}站调度日志不满足以下条件：日志类型是站内日志，包含封锁全站电压和封锁全站信号的内容且isEnd为否，且日志细节不存在解除全站电压和解除全站信号"
        obs = {"log": text}
        return f"Observation:{json.dumps(obs, ensure_ascii=False)}"

    def _format_taizhang_observation(self, results: List[str], station: str) -> str:
        """
        格式化台账查询结果，与训练数据格式一致

        训练数据格式: Observation:{"taizhang_list": [...]}

        参数:
            results: 工具执行结果列表
            station: 站点名称

        返回:
            格式化后的 Observation
        """
        try:
            # 解析工具返回结果
            all_items = []
            for res_str in results:
                try:
                    data = json.loads(res_str)
                    items = data if isinstance(data, list) else [data]
                    all_items.extend(items)
                except Exception:
                    continue

            # 包装成训练数据格式
            obs_dict = {"taizhang_list": all_items}
            obs_json = json.dumps(obs_dict, ensure_ascii=False)
            return f'Observation:{obs_json}'

        except Exception as e:
            print(f"格式化台账数据失败: {e}")
            task_logger.error(f"台账结果格式化异常: {str(e)}")
            obs_dict = {"taizhang_list": []}
            obs_json = json.dumps(obs_dict, ensure_ascii=False)
            return f'Observation:{obs_json}'

    def _normalize_ticket_queries(self, tool_args: Dict[str, Any]) -> List[Dict[str, str]]:
        """将操作票参数规范化为查询列表，兼容 queries 批量格式和 station+line_name 单条格式。"""
        if not tool_args:
            return []

        # 如果模型传了 queries（批量），从中提取
        queries = tool_args.get("queries")
        if isinstance(queries, list) and len(queries) > 0:
            normalized = []
            for item in queries:
                if isinstance(item, dict):
                    station = item.get("station", "")
                    line_name = item.get("line_name", "")
                    if station or line_name:
                        normalized.append({"station": station, "line_name": line_name})
            return normalized

        # 单条 station + line_name
        station = tool_args.get("station", "")
        line_name = tool_args.get("line_name", "")
        if station or line_name:
            return [{"station": station, "line_name": line_name}]
        return []

    def _coerce_ticket_results(self, raw_results: List[str], queries: List[Dict[str, str]]) -> List[str]:
        """兼容单条服务结果与批量服务结果的格式。"""
        if not raw_results:
            return []
        if not queries:
            return raw_results

        if len(raw_results) == len(queries) and len(queries) > 1:
            return raw_results

        if len(raw_results) == 1:
            try:
                parsed = json.loads(raw_results[0])
            except (TypeError, json.JSONDecodeError):
                return raw_results

            if isinstance(parsed, list):
                if len(parsed) >= len(queries):
                    coerced = []
                    for item in parsed[:len(queries)]:
                        if isinstance(item, dict):
                            coerced.append(json.dumps(item, ensure_ascii=False))
                        else:
                            coerced.append(str(item))
                    return coerced
                return [json.dumps(parsed, ensure_ascii=False)]

            if isinstance(parsed, dict):
                for key in ("results", "data", "items"):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        coerced = []
                        for item in value:
                            if isinstance(item, dict):
                                coerced.append(json.dumps(item, ensure_ascii=False))
                            else:
                                coerced.append(str(item))
                        if coerced:
                            return coerced

        return raw_results

    def _format_batch_ticket_observation(self, batch_results: List[tuple]) -> str:
        """
        将多条馈线的操作票查询结果合并为一条 Observation。

        参数:
            batch_results: [(station, line_name, [result_str, ...]), ...]

        返回:
            汇总的 Observation 字符串，例如:
            Observation:{石岩站F69查到操作票数量为3，不包含"停电票"}
        """
        parts = []
        for station, line_name, results in batch_results:
            # 复用已有的单馈线格式化逻辑
            single = self._format_ticket_observation(results, station, line_name)
            # 去掉开头的 "Observation:" 前缀，取出内容
            content = single.replace("Observation:", "", 1).strip()
            # 去掉外层的大括号（如果有），因为我们后续会拼接
            if content.startswith("{") and content.endswith("}"):
                content = content[1:-1]
            parts.append(content)

        # 用中文句号连接多条馈线的结果
        combined = "。".join(parts)
        obs = {"opera_ticket": combined}
        return f"Observation:{json.dumps(obs, ensure_ascii=False)}"

    def _parse_action_inputs(self, input_str: str) -> List[Dict[str, Any]]:
        """解析 Action Input 中的一个或多个 JSON 对象"""
        # 处理 Markdown 代码块
        if input_str.startswith('```'):
            input_str = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', input_str, flags=re.DOTALL)

        input_str = input_str.strip()

        # 尝试直接解析（单个 JSON）
        try:
            return [json.loads(input_str)]
        except json.JSONDecodeError:
            # 尝试解析多个连续的 JSON 对象，例如 {"a":1}, {"b":2}
            # 使用正则匹配所有的 { ... } 结构
            objs = []
            # 这是一个简单的匹配逻辑，可能需要根据实际复杂的嵌套情况进行调整
            matches = re.finditer(r'\{.*?\}', input_str, re.DOTALL)
            for match in matches:
                try:
                    objs.append(json.loads(match.group()))
                except json.JSONDecodeError:
                    continue
            return objs

    def reset_history(self):
        """重置对话历史，只保留系统提示词
        """
        self.messages = [
            {"role": "system", "content": config.SYSTEM_PROMPT}
        ]
        print(" 对话历史已重置")
        task_logger.info("对话历史重置，仅保留system prompt")

    async def async_call(self, user_input: str) -> AsyncGenerator[Dict[str, Any], None]:
        """异步调用 Agent 处理用户输入，并生成流式事件
        两阶段流程：
          阶段1：基于规则直接判定操作告警（线路+正关键词-负关键词），无需调用LLM
          阶段2：操作告警→用 MODEL 正式研判（输出完整过程）；非操作告警→用 MODEL2 正式研判（输出完整过程）
        """
        trace_id = bind_trace_id()
        task_logger.info("[任务开始] trace_id=%s | mode=async", trace_id)

        # 记录用户输入
        self.logger.log_user_input(user_input)

        # ---------- 阶段1：规则预分类（纯规则，不调用LLM）----------
        self.reset_history()
        task_logger.info("[两阶段流程] 阶段1开始：基于用户输入直接做规则预分类（线路+关键词）")
        try:
            _raw = QwenAgent.extract_alert_content(user_input)
            if QwenAgent.is_accident_summary_signal(_raw):
                thought_text, final_answer = QwenAgent.get_accident_summary_direct_result()
                task_logger.info(
                    "[事故总短路] alert_content 命中“事故总”，跳过LLM，2s后按Agent区段结构(thought/final_answer)流式输出固定研判结果"
                )
                # 用户要求：判断为事故总后先延迟 2 秒，再开始流式输出，更贴近大模型思考/启动时延。
                await asyncio.sleep(2.0)
                # 与 LLM 真实路径的“区段式输出结构”完全对齐：
                # 1) thought 区段 → section=thought 纯正文增量（不带 Thought: 前缀）
                # 2) final_answer 区段 → section=final_answer 纯正文增量（不带 Final Answer: 前缀）
                # 下游 sse_event_generator 会分别映射为 SSE type=thought / type=task_complete，
                # 前端展示结构与真实 Agent 研判一致，不会出现 Thought:/Final Answer: 字面标记。
                async def _stream_accident_section(section_name: str, body_text: str):
                    _cursor = 0
                    _total = len(body_text)
                    while _cursor < _total:
                        _chunk_size = 1 if (_total - _cursor == 1) else max(1, min(3, _total - _cursor))
                        _seg = body_text[_cursor:_cursor + _chunk_size]
                        _cursor += _chunk_size
                        await asyncio.sleep(0.020 + (hash((_cursor, _seg)) & 0b11111) / 1000.0)
                        yield {"type": "llm_output", "content": _seg, "section": section_name}

                async for _evt in _stream_accident_section("thought", thought_text):
                    yield _evt
                async for _evt in _stream_accident_section("final_answer", final_answer):
                    yield _evt
                yield {"type": "final_answer", "content": final_answer}
                return
            _is_op = QwenAgent.is_operation_alarm(_raw)
        except Exception as e:
            task_logger.error("[两阶段流程] 阶段1规则判定异常，降级为非操作告警: %s", str(e))
            _is_op = False

        if _is_op:
            selected_model = config.DEEPSEEK_MODEL
        else:
            selected_model = QwenAgent.get_deepseek_model2()

        task_logger.info("[两阶段流程] 阶段1结束 | 判定为: %s | 阶段2正式研判模型: %s",
                         "操作告警" if _is_op else "非操作告警", selected_model)

        # ---------- 阶段2：正式研判，完整输出流式内容 ----------
        self.reset_history()

        # ---------- 日志：告警处理开始 ----------
        task_logger.info("=" * 60)
        task_logger.info("[告警处理-开始(阶段2)] 用户输入长度: %d 字符", len(user_input))
        task_logger.info("[告警原始内容] %s", user_input[:800] if len(user_input) > 800 else user_input)
        task_logger.info("[信号类型] %s (阶段1判定) | [阶段2使用模型] %s | 最大推理轮数：%d",
                         "操作告警" if _is_op else "非操作告警", selected_model, config.MAX_CONVERSATION_ROUNDS)
        task_logger.info("-" * 60)

        # 添加用户消息到历史
        self.messages.append({
            "role": "user",
            "content": user_input
        })

        # 开始 Agent 调用循环
        for round_num in range(config.MAX_CONVERSATION_ROUNDS):
            print(f"\n 第 {round_num + 1} 轮推理...")
            task_logger.info("[流程-第%d轮推理] 开始 | 当前消息历史: %d 条", round_num + 1, len(self.messages))

            # 准备请求数据
            request_data = {
                "model": selected_model,
                "messages": self.messages,
                "temperature": config.TEMPERATURE,
                "max_tokens": config.MAX_TOKENS
            }

            # 记录请求数据
            self.logger.log_api_request(request_data)

            # 调用 API（流式返回）
            try:
                task_logger.info("[流程步骤] 第%d轮开始调用流式大模型接口", round_num + 1)
                response = await self.async_client.chat.completions.create(
                    model=selected_model,
                    messages=self.messages,
                    temperature=config.TEMPERATURE,
                    max_tokens=config.MAX_TOKENS,
                    stream=True
                )
            except Exception as e:
                err_msg = f"调用大模型API异常：{str(e)}"
                stack = traceback.format_exc()
                print(err_msg)
                task_logger.error("[系统报错原因] 阶段=调用大模型API | 错误=%s\n%s", err_msg, stack)
                yield {"type": "error", "content": err_msg}
                return

            # 按 chunk 逐段流式发送内容。
            # 这里维护一个“当前区段状态机”，按 Thought:/Action:/Action Input:/Final Answer: 的边界
            # 实时切换流式片段的语义类型，并且保证：
            # 1）Thought 正文 → thought 事件
            # 2）Action / Action Input 正文（带上“工具: / 工具参数: ”中文前缀） → chat_stream 事件
            # 3）Final Answer 正文 → task_complete 事件
            # 4）tool_start / tool_end 作为生命周期事件仍然单独发，不拆
            content_parts: List[str] = []
            final_answer_marker_seen = False

            section_state: Dict[str, Any] = {
                "current": "other",
                "buffer": "",
                "started": False,
            }

            section_markers: List[Tuple[str, str]] = [
                ("thought", "Thought:"),
                ("action", "Action:"),
                ("action_input", "Action Input:"),
                ("final_answer", "Final Answer:"),
            ]

            def _emit_with_type(section_state: Dict[str, Any], buf: str) -> Optional[str]:
                if not buf:
                    return None
                current = section_state["current"]
                if current in {"thought", "final_answer"}:
                    return current
                return "chat_stream_section"

            def _transition_if_marker(section_state: Dict[str, Any], to_emit: List[Tuple[str, str]]) -> None:
                buf = section_state["buffer"]
                if not buf:
                    return
                content_type = _emit_with_type(section_state, buf)
                if content_type:
                    to_emit.append((content_type, buf))
                section_state["buffer"] = ""

            def _on_enter_section(next_section_type: str, to_emit: List[Tuple[str, str]]) -> None:
                """
                进入新区段时，如果需要前缀（例如 Action 区段进入时补“工具: ”，Action Input 区段
                进入时补“\n工具参数: ”），则在这里作为同类型的第一条流式内容输出。
                Thought / Final Answer 区段我们不在这里加前缀，因为 marker 后面内容已经是纯正文，
                SSE 最终展示要求就是不带 Thoughts: / Final Answer: 前缀的正文。
                """
                if next_section_type == "action":
                    to_emit.append(("chat_stream_section", "工具: "))
                elif next_section_type == "action_input":
                    to_emit.append(("chat_stream_section", "\n工具参数: "))

            def _feed_delta_into_sections(section_state: Dict[str, Any], delta_content: str) -> List[Tuple[str, str]]:
                section_state["buffer"] += delta_content
                to_emit: List[Tuple[str, str]] = []

                guard = 0
                while guard < 8:
                    guard += 1
                    buf = section_state["buffer"]

                    earliest: Optional[Tuple[int, str]] = None
                    for section_type, marker in section_markers:
                        pos = buf.find(marker)
                        if pos == -1:
                            continue
                        prefix = buf[:pos]
                        if prefix and not prefix.endswith("\n"):
                            continue
                        if earliest is None or pos < earliest[0]:
                            earliest = (pos, section_type)

                    if earliest is None:
                        break

                    marker_pos, next_section_type = earliest
                    marker_str = dict(section_markers)[next_section_type]

                    before = buf[:marker_pos]
                    if before.strip():
                        section_state["buffer"] = before
                        _transition_if_marker(section_state, to_emit)

                    section_state["current"] = next_section_type
                    section_state["started"] = True
                    section_state["buffer"] = buf[marker_pos + len(marker_str):]

                    if next_section_type == "final_answer" and not final_answer_marker_seen:
                        task_logger.info("[流程步骤] 流式输出已识别 Final Answer 标记")

                    _on_enter_section(next_section_type, to_emit)

                buf = section_state["buffer"]
                if len(buf) > 8:
                    keep_tail = 8
                    current_chunk = buf[:-keep_tail]
                    section_state["buffer"] = buf[-keep_tail:]
                    if current_chunk:
                        content_type = _emit_with_type(section_state, current_chunk)
                        if content_type:
                            to_emit.append((content_type, current_chunk))

                return to_emit

            def _flush_section_tail(section_state: Dict[str, Any]) -> List[Tuple[str, str]]:
                tail = section_state["buffer"]
                section_state["buffer"] = ""
                if not tail:
                    return []
                content_type = _emit_with_type(section_state, tail)
                if content_type:
                    return [(content_type, tail)]
                return []

            async for chunk in response:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue

                delta = choices[0].delta
                delta_content = getattr(delta, "content", None) or ""
                if not delta_content:
                    continue

                content_parts.append(delta_content)
                accumulated_content = "".join(content_parts)

                for seg_type, seg_text in _feed_delta_into_sections(section_state, delta_content):
                    yield {"type": "llm_output", "content": seg_text, "section": seg_type}

                if (not final_answer_marker_seen) and ("Final Answer:" in accumulated_content):
                    final_answer_marker_seen = True

            # 响应结束时把段尾 flush 出去
            for seg_type, seg_text in _flush_section_tail(section_state):
                yield {"type": "llm_output", "content": seg_text, "section": seg_type}

            content = "".join(content_parts)
            usage = {}

            # 记录原始响应和思考
            self.logger.log_api_response({
                "choices": [{"message": {"content": content}}],
                "model": getattr(response, "model", selected_model)
            })
            self.logger.log_agent_thinking({
                "content": content,
                "model": getattr(response, "model", selected_model),
                "role": "assistant"
            })

            # 添加 assistant 消息到历史
            self.messages.append({
                "role": "assistant",
                "content": content
            })

            # 1. 检查是否是最终回答
            if "Final Answer:" in content:
                final_answer = content.split("Final Answer:")[1].strip()
                self.logger.log_final_response(final_answer, usage)
                self.logger.save_session()
                # 结束一轮对话后重置历史
                self.reset_history()

                # ---------- 日志：最终回答 ----------
                task_logger.info("[流程-最终回答] 第%d轮 | 回答长度: %d 字符",
                                 round_num + 1, len(final_answer))
                task_logger.info("[最终回答内容] %s", final_answer[:800])
                task_logger.info("[告警处理-结束] 成功 | 总推理轮数: %d", round_num + 1)
                task_logger.info("=" * 60)

                yield {"type": "final_answer", "content": final_answer}
                return

            # 2. 检查是否需要调用工具 (解析 Action 和 Action Input)
            if "Action:" in content and "Action Input:" in content:
                try:
                    # 使用正则表达式更精确地提取工具名称和参数
                    action_match = re.search(r"Action:\s*(.*?)(?:\n|Action Input:|$)", content, re.DOTALL)
                    # 匹配 Action Input: 之后的所有内容
                    input_match = re.search(r"Action Input:\s*(.*)", content, re.DOTALL)

                    if action_match and input_match:
                        tool_name = action_match.group(1).strip()
                        tool_args_str = input_match.group(1).strip()

                        # 解析多个可能的参数对象
                        all_tool_args = self._parse_action_inputs(tool_args_str)

                        # ---------- 日志：工具调用（含并发）----------
                        is_concurrent = len(all_tool_args) > 1
                        task_logger.info("[流程-第%d轮推理] 识别工具调用 | 工具: %s | 并发调用数量: %d",
                                         round_num + 1, tool_name, len(all_tool_args))
                        if is_concurrent:
                            task_logger.info("[并发工具调用-启动] 工具名称: %s，共%d组参数待执行", tool_name, len(all_tool_args))
                            for idx, args in enumerate(all_tool_args):
                                task_logger.info("[并发-%d/%d] 调用参数: %s", idx + 1, len(all_tool_args),
                                                 json.dumps(args, ensure_ascii=False))

                        all_results = []
                        loop = asyncio.get_event_loop()

                        for idx, tool_args in enumerate(all_tool_args):
                            subtask_label = f"{idx + 1}/{len(all_tool_args)}"
                            # 发送工具调用信息给前端
                            yield {"type": "tool_call", "tool_name": tool_name, "tool_args": tool_args}
                            task_logger.info(
                                "[%s工具执行-%s] 开始 | tool=%s | args=%s",
                                "并发子任务" if is_concurrent else "工具",
                                subtask_label,
                                tool_name,
                                _preview_text(json.dumps(tool_args, ensure_ascii=False), 300)
                            )
                            # 执行工具 (在线程池中执行同步工具函数)
                            try:
                                tool_result = await loop.run_in_executor(None, execute_tool, tool_name, tool_args)
                            except Exception as tool_exc:
                                tool_error_msg = f"执行工具 {tool_name} 失败：{str(tool_exc)}"
                                task_logger.error(
                                    "[系统报错原因] 阶段=工具执行 | tool=%s | subtask=%s | args=%s\n%s",
                                    tool_name,
                                    subtask_label,
                                    _preview_text(json.dumps(tool_args, ensure_ascii=False), 300),
                                    traceback.format_exc()
                                )
                                yield {"type": "error", "content": tool_error_msg}
                                self.messages.append({
                                    "role": "user",
                                    "content": f"Observation: 错误 - {tool_error_msg}"
                                })
                                all_results = []
                                break
                            all_results.append(tool_result)
                            task_logger.info(
                                "[%s工具执行-%s] 完成 | result=%s",
                                "并发子任务" if is_concurrent else "工具",
                                subtask_label,
                                _preview_text(tool_result, 300)
                            )
                            # 发送工具执行结果给前端
                            yield {"type": "tool_result", "tool_name": tool_name, "result": tool_result}

                        if not all_results:
                            task_logger.warning("[流程步骤] 本轮工具执行未产出有效结果，进入下一轮推理")
                            continue

                        # 处理结果汇总，使用所有工具结果进行格式化
                        first_args = all_tool_args[0] if all_tool_args else {}
                        if tool_name == "search_caozuotickets":
                            ticket_queries = self._normalize_ticket_queries(first_args)
                            if len(all_tool_args) > 1:
                                # 多参数：将每个参数与其结果配对，批量格式化
                                batch_results = [
                                    (args.get("station", ""), args.get("line_name", ""), [result])
                                    for args, result in zip(all_tool_args, all_results)
                                ]
                                formatted_result = self._format_batch_ticket_observation(batch_results)
                            elif ticket_queries and len(ticket_queries) > 1:
                                coerced_results = self._coerce_ticket_results(all_results, ticket_queries)
                                batch_results = [
                                    (query.get("station", ""), query.get("line_name", ""), [result])
                                    for query, result in zip(ticket_queries, coerced_results if len(coerced_results) == len(ticket_queries) else [coerced_results[0]] * len(ticket_queries))
                                ]
                                formatted_result = self._format_batch_ticket_observation(batch_results)
                            elif ticket_queries and len(ticket_queries) == 1:
                                # 单条 queries 情况，从 ticket_queries 中提取 station/line_name
                                q = ticket_queries[0]
                                station = q.get("station", "")
                                line_name = q.get("line_name", "")
                                formatted_result = self._format_ticket_observation(all_results, station, line_name)
                            else:
                                station = first_args.get("station", "")
                                line_name = first_args.get("line_name", "")
                                formatted_result = self._format_ticket_observation(all_results, station, line_name)
                        elif tool_name == "search_diaodulog":
                            station = first_args.get("station", "")
                            formatted_result = self._format_diaodulog_observation(all_results, station)
                        elif tool_name == "search_taizhang":
                            station = first_args.get("station", "")
                            formatted_result = self._format_taizhang_observation(all_results, station)
                        else:
                            # search_livework_ticket 或其他工具
                            if len(all_results) == 1:
                                observation = f"Observation:{{{all_results[0]}}}"
                            else:
                                try:
                                    observation = f"Observation:{{{json.dumps(all_results, ensure_ascii=False)}}}"
                                except Exception:
                                    observation = f"Observation:{{{str(all_results)}}}"

                        # 记录工具调用 (取第一个作为记录或记录全部)
                        class MockToolCall:
                            def __init__(self, name, args, id):
                                self.id = id
                                self.function = type('obj', (object,), {'name': name, 'arguments': json.dumps(args)})

                        mock_tool_call = MockToolCall(tool_name, first_args, f"call_{round_num}")
                        observation = formatted_result
                        self.logger.log_tool_call(mock_tool_call, observation)
                        task_logger.info("[工具结果汇总] 组装完成Observation: %s", observation[:600])

                        # 添加工具结果到消息历史（发送给模型的是处理过的 observation）
                        self.messages.append({
                            "role": "user",
                            "content": observation
                        })

                        # 继续下一轮推理
                        continue

                except Exception as e:
                    error_msg = f"解析工具调用失败: {str(e)}"
                    stack_info = traceback.format_exc()
                    print(f"{error_msg}")
                    # ---------- 日志：工具解析报错 ----------
                    task_logger.error("[系统报错原因] 阶段=工具解析 | 第%d轮 | 错误=%s\n堆栈信息:\n%s",
                                      round_num + 1, str(e), stack_info[:1200])
                    yield {"type": "error", "content": error_msg}
                    self.messages.append({
                        "role": "user",
                        "content": f"Observation: 错误 - {error_msg}"
                    })
                    continue

            # 3. 如果既没有 Final Answer 也没有 Action，可能模型输出了普通文本
            if content:
                print("模型未输出 Final Answer 关键字，但给出了回复内容。")
                self.logger.log_final_response(content, usage)
                self.logger.save_session()
                # 结束一轮对话后重置历史
                self.reset_history()

                # ---------- 日志：非标准格式的最终回答 ----------
                task_logger.warning("[流程-非标准最终回答] 模型未输出Final Answer标记，直接使用输出作为结果")
                task_logger.info("[流程-非标准最终回答] 第%d轮 | 回答长度: %d 字符", round_num + 1, len(content))
                task_logger.info("[告警处理-结束] (非标准格式) 总轮数: %d", round_num + 1)
                task_logger.info("=" * 60)

                yield {"type": "final_answer", "content": content}
                return

        # 超过最大轮数
        error_msg = "达到最大对话轮数限制"
        print(f"\n{error_msg}")
        self.logger.save_session()
        # 异常结束也重置历史
        self.reset_history()

        # ---------- 日志：达到最大轮数 ----------
        task_logger.warning("[流程-达到最大轮数限制] 已执行 %d 轮推理，超出阈值", config.MAX_CONVERSATION_ROUNDS)
        task_logger.info("[告警处理-结束] 异常终止，达到最大轮数")
        task_logger.info("=" * 60)

        yield {"type": "error", "content": error_msg}

    def call(self, user_input: str) -> str:
        """
        调用 Agent 处理用户输入 (支持文本 ReAct 格式)
        两阶段流程：
          阶段1：基于规则直接判定操作告警（线路+正关键词-负关键词），无需调用LLM
          阶段2：操作告警→用 MODEL 正式研判并输出；非操作告警→用 MODEL2 正式研判并输出
        """
        trace_id = bind_trace_id()
        task_logger.info("[任务开始] trace_id=%s | mode=sync", trace_id)

        # 记录用户输入
        self.logger.log_user_input(user_input)

        # ---------- 阶段1：规则预分类（纯规则，不调用LLM）----------
        self.reset_history()
        task_logger.info("[两阶段流程-同步] 阶段1开始：基于用户输入直接做规则预分类（线路+关键词）")
        try:
            _raw = QwenAgent.extract_alert_content(user_input)
            if QwenAgent.is_accident_summary_signal(_raw):
                thought_text, final_answer = QwenAgent.get_accident_summary_direct_result()
                task_logger.info("[事故总短路-同步] alert_content 命中“事故总”，跳过LLM直接输出固定研判结果")
                return f"Thought:{thought_text}\nFinal Answer:{final_answer}"
            _is_op = QwenAgent.is_operation_alarm(_raw)
        except Exception as e:
            task_logger.error("[两阶段流程-同步] 阶段1规则判定异常，降级为非操作告警: %s", str(e))
            _is_op = False

        if _is_op:
            selected_model = config.DEEPSEEK_MODEL
        else:
            selected_model = QwenAgent.get_deepseek_model2()

        task_logger.info("[两阶段流程-同步] 阶段1结束 | 判定为: %s | 阶段2正式研判模型: %s",
                         "操作告警" if _is_op else "非操作告警", selected_model)

        # ---------- 阶段2：正式研判 ----------
        self.reset_history()

        # ---------- 日志：告警处理开始 ----------
        task_logger.info("=" * 60)
        task_logger.info("[同步模式告警处理-开始(阶段2)] 用户输入长度: %d 字符", len(user_input))
        task_logger.info("[告警原始内容] %s", user_input[:800] if len(user_input) > 800 else user_input)
        task_logger.info("[信号类型] %s (阶段1判定) | [阶段2使用模型] %s | 最大推理轮数：%d",
                         "操作告警" if _is_op else "非操作告警", selected_model, config.MAX_CONVERSATION_ROUNDS)
        task_logger.info("-" * 60)

        # 添加用户消息到历史
        self.messages.append({
            "role": "user",
            "content": user_input
        })

        # 开始 Agent 调用循环
        for round_num in range(config.MAX_CONVERSATION_ROUNDS):
            print(f"\n 第 {round_num + 1} 轮推理...")
            task_logger.info("[同步流程-第%d轮推理] 开始 | 当前消息历史: %d 条", round_num + 1, len(self.messages))

            # 准备请求数据
            request_data = {
                "model": selected_model,
                "messages": self.messages,
                "temperature": config.TEMPERATURE,
                "max_tokens": config.MAX_TOKENS
            }

            # 记录请求数据
            self.logger.log_api_request(request_data)

            # 调用 API
            try:
                task_logger.info("[同步流程步骤] 第%d轮开始调用非流式大模型接口", round_num + 1)
                response = self.client.chat.completions.create(
                    model=selected_model,
                    messages=self.messages,
                    temperature=config.TEMPERATURE,
                    max_tokens=config.MAX_TOKENS
                )
            except Exception as e:
                err_msg = f"同步模式调用大模型API异常：{str(e)}"
                stack = traceback.format_exc()
                print(err_msg)
                task_logger.error("[系统报错原因] 阶段=同步调用大模型API | 错误=%s\n%s", err_msg, stack)
                return err_msg

            # 获取响应内容
            response_message = response.choices[0].message
            content = response_message.content or ""
            usage = response.usage.model_dump() if response.usage else {}

            # 记录原始响应和思考
            self.logger.log_api_response(response.model_dump())
            self.logger.log_agent_thinking({
                "content": content,
                "model": response.model,
                "role": response_message.role
            })

            # 添加 assistant 消息到历史
            self.messages.append({
                "role": "assistant",
                "content": content
            })

            # 1. 检查是否是最终回答
            if "Final Answer:" in content:
                final_answer = content.split("Final Answer:")[1].strip()
                self.logger.log_final_response(final_answer, usage)
                self.logger.save_session()
                # 结束一轮对话后重置历史
                self.reset_history()

                # ---------- 日志：最终回答 ----------
                task_logger.info("[同步流程-最终回答] 第%d轮 | 回答长度: %d 字符",
                                 round_num + 1, len(final_answer))
                task_logger.info("[同步告警处理-结束] 成功 | 总轮数: %d", round_num + 1)
                task_logger.info("=" * 60)

                return final_answer

            # 2. 检查是否需要调用工具 (解析 Action 和 Action Input)
            if "Action:" in content and "Action Input:" in content:
                try:
                    # 使用正则表达式更精确地提取工具名称和参数
                    action_match = re.search(r"Action:\s*(.*?)(?:\n|Action Input:|$)", content, re.DOTALL)
                    input_match = re.search(r"Action Input:\s*(.*)", content, re.DOTALL)

                    if action_match and input_match:
                        tool_name = action_match.group(1).strip()
                        tool_args_str = input_match.group(1).strip()

                        # 解析多个可能的参数对象
                        all_tool_args = self._parse_action_inputs(tool_args_str)

                        # ---------- 日志：工具调用（含并发）----------
                        is_concurrent = len(all_tool_args) > 1
                        task_logger.info("[同步流程-第%d轮推理] 识别工具调用 | 工具: %s | 并发调用数: %d",
                                         round_num + 1, tool_name, len(all_tool_args))
                        if is_concurrent:
                            task_logger.info("[同步并发工具启动] 工具:%s，共%d组参数", tool_name, len(all_tool_args))
                            for idx, args in enumerate(all_tool_args):
                                task_logger.info("[同步并发-%d] 参数:%s", idx+1, json.dumps(args, ensure_ascii=False))

                        all_results = []
                        for idx, tool_args in enumerate(all_tool_args):
                            subtask_label = f"{idx + 1}/{len(all_tool_args)}"
                            task_logger.info(
                                "[%s同步工具执行-%s] 开始 | tool=%s | args=%s",
                                "并发子任务" if is_concurrent else "工具",
                                subtask_label,
                                tool_name,
                                _preview_text(json.dumps(tool_args, ensure_ascii=False), 300)
                            )
                            # 执行工具
                            try:
                                tool_result = execute_tool(tool_name, tool_args)
                            except Exception as tool_exc:
                                tool_error_msg = f"执行工具 {tool_name} 失败：{str(tool_exc)}"
                                task_logger.error(
                                    "[系统报错原因] 阶段=同步工具执行 | tool=%s | subtask=%s | args=%s\n%s",
                                    tool_name,
                                    subtask_label,
                                    _preview_text(json.dumps(tool_args, ensure_ascii=False), 300),
                                    traceback.format_exc()
                                )
                                self.messages.append({
                                    "role": "user",
                                    "content": f"Observation: 错误 - {tool_error_msg}"
                                })
                                all_results = []
                                break
                            all_results.append(tool_result)
                            task_logger.info(
                                "[%s同步工具执行-%s] 完成 | result=%s",
                                "并发子任务" if is_concurrent else "工具",
                                subtask_label,
                                _preview_text(tool_result, 300)
                            )

                        if not all_results:
                            task_logger.warning("[同步流程步骤] 本轮工具执行未产出有效结果，进入下一轮推理")
                            continue

                        # 处理结果汇总
                        first_args = all_tool_args[0] if all_tool_args else {}
                        if tool_name == "search_caozuotickets":
                            ticket_queries = self._normalize_ticket_queries(first_args)
                            if len(all_tool_args) > 1:
                                # 多参数：将每个参数与其结果配对，批量格式化
                                batch_results = [
                                    (args.get("station", ""), args.get("line_name", ""), [result])
                                    for args, result in zip(all_tool_args, all_results)
                                ]
                                observation = self._format_batch_ticket_observation(batch_results)
                            elif ticket_queries and len(ticket_queries) > 1:
                                coerced_results = self._coerce_ticket_results(all_results, ticket_queries)
                                batch_results = [
                                    (query.get("station", ""), query.get("line_name", ""), [result])
                                    for query, result in zip(ticket_queries, coerced_results if len(coerced_results) == len(ticket_queries) else [coerced_results[0]] * len(ticket_queries))
                                ]
                                observation = self._format_batch_ticket_observation(batch_results)
                            elif ticket_queries and len(ticket_queries) == 1:
                                q = ticket_queries[0]
                                station = q.get("station", "")
                                line_name = q.get("line_name", "")
                                observation = self._format_ticket_observation(all_results, station, line_name)
                            else:
                                station = first_args.get("station", "")
                                line_name = first_args.get("line_name", "")
                                observation = self._format_ticket_observation(all_results, station, line_name)
                        elif tool_name == "search_diaodulog":
                            station = first_args.get("station", "")
                            observation = self._format_diaodulog_observation(all_results, station)
                        elif tool_name == "search_taizhang":
                            station = first_args.get("station", "")
                            observation = self._format_taizhang_observation(all_results, station)
                        else:
                            # search_livework_ticket 或其他工具
                            if len(all_results) == 1:
                                observation = f"Observation:{{{all_results[0]}}}"
                            else:
                                try:
                                    observation = f"Observation:{{{json.dumps(all_results, ensure_ascii=False)}}}"
                                except Exception:
                                    observation = f"Observation:{{{str(all_results)}}}"

                        # 记录工具调用 (取第一个作为记录或记录全部)
                        class MockToolCall:
                            def __init__(self, name, args, id):
                                self.id = id
                                self.function = type('obj', (object,), {'name': name, 'arguments': json.dumps(args)})

                        mock_tool_call = MockToolCall(tool_name, all_tool_args[0] if all_tool_args else {}, f"call_{round_num}")
                        self.logger.log_tool_call(mock_tool_call, observation)
                        task_logger.info("[同步工具结果汇总] Observation组装完成：%s", observation[:600])

                        # 添加工具结果到消息历史（发送格式化后的内容给大模型）
                        self.messages.append({
                            "role": "user",
                            "content": observation
                        })

                        # 继续下一轮推理
                        continue

                except Exception as e:
                    error_msg = f"解析工具调用失败: {str(e)}"
                    stack_info = traceback.format_exc()
                    print(f"{error_msg}")
                    task_logger.error("[系统报错原因] 阶段=同步工具解析 | 错误=%s\n%s", str(e), stack_info[:1200])
                    self.messages.append({
                        "role": "user",
                        "content": f"Observation: 错误 - {error_msg}"
                    })
                    continue

            # 3. 如果既没有 Final Answer 也没有 Action，可能模型输出了普通文本
            if content:
                # 如果模型没有按格式回复，但给出了内容，我们也尝试将其作为最终回答
                print("模型未输出 Final Answer 关键字，但给出了回复内容。")
                self.logger.log_final_response(content, usage)
                self.logger.save_session()
                # 结束一轮对话后重置历史
                self.reset_history()
                task_logger.warning("[同步流程] 模型未输出Final Answer标记，直接返回原始输出")
                task_logger.info("[同步告警处理-结束] 非标准格式，总轮数: %d", round_num + 1)
                task_logger.info("=" * 60)
                return content

        # 超过最大轮数
        error_msg = "达到最大对话轮数限制"
        print(f"\n {error_msg}")
        self.logger.save_session()
        # 异常结束也重置历史
        self.reset_history()
        task_logger.warning("[同步流程] 达到最大推理轮数限制，任务终止")
        task_logger.info("=" * 60)
        return error_msg

    def interactive_mode(self):
        """交互式对话模式"""
        print("\n" + "="*60)
        print("Agent 交互模式")
        print("="*60)
        print("输入 'quit' 或 'exit' 退出")
        print("输入 'clear' 清除对话历史")
        print("="*60 + "\n")

        while True:
            try:
                user_input = input("\n用户: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['quit', 'exit', '退出']:
                    print("\n再见！")
                    break

                if user_input.lower() in ['clear', '清除']:
                    self.messages = [
                        {"role": "system", "content": config.SYSTEM_PROMPT}
                    ]
                    self.logger.reset_session()
                    print("\n对话历史已清除")
                    task_logger.info("交互模式：执行clear，清空对话历史")
                    continue

                # 调用 Agent
                response = self.call(user_input)
                print(f"\nAgent: {response}")

            except KeyboardInterrupt:
                print("\n\n再见！")
                break
            except Exception as e:
                print(f"\n发生错误: {str(e)}")
                stack = traceback.format_exc()
                task_logger.error(f"交互模式全局异常：{str(e)} \n{stack}")


# 工具名称映射（与 agent_ws_handler.py 保持一致）
TOOL_NAME_MAPPING = {
    "search_taizhang": "台账",
    "search_diaodulog": "调度日志",
    "search_caozuotickets": "操作票",
    "search_livework_ticket": "带电作业工单"
}


def _map_tool_name(tool_name: str) -> str:
    return TOOL_NAME_MAPPING.get(tool_name, tool_name)


def _strip_final_answer_prefix(content: str) -> str:
    if not content:
        return ""
    return re.sub(r"^\s*Final Answer:\s*", "", content).strip()


def _format_chat_stream_content(content: str) -> str:
    """
    将模型输出中的 Action / Action Input 转为更易展示的中文字段。
    """
    if not content:
        return ""

    formatted = content

    def replace_action(match: re.Match) -> str:
        tool_name = match.group(1).strip()
        return f"工具: {_map_tool_name(tool_name)}"

    formatted = re.sub(r"(?m)^Action:\s*(.+)$", replace_action, formatted)
    formatted = re.sub(r"(?m)^Action Input:\s*", "工具参数: ", formatted)
    return formatted.strip()


def _normalize_stream_type(stream_type: Any) -> str:
    """统一流式消息类型，避免大写或枚举值泄露。"""
    try:
        stream_type = stream_type.value
    except Exception:
        pass
    type_str = str(stream_type or "").strip()
    if not type_str:
        return "chat_stream"
    type_lower = type_str.lower()
    if type_lower == "chat_stream" or type_lower == "chat_stream":
        return "chat_stream"
    if type_lower == "thought":
        return "thought"
    if type_lower in {"task_complete", "final_answer"}:
        return "task_complete"
    if type_lower == "tool_start":
        return "tool_start"
    if type_lower == "tool_end":
        return "tool_end"
    return type_lower


def _split_llm_content(content: str) -> list[tuple[str, str]]:
    """
    将 LLM 输出拆分为 Thought 和后续结构化内容。
    返回格式: [(message_type, message_content), ...]
    """
    cleaned = re.sub(r"[\s\S]*?\s*", "", content or "").strip()
    if not cleaned:
        return []

    thought_index = cleaned.find("Thought:")
    if thought_index == -1:
        return [("chat_stream", cleaned)]

    parts: list[tuple[str, str]] = []

    prefix = cleaned[:thought_index].strip()
    if prefix:
        parts.append(("chat_stream", prefix))

    thought_and_rest = cleaned[thought_index:]
    marker = re.search(r"\n(?=Action:|Final Answer:|Observation:)", thought_and_rest)
    if marker:
        thought_content = thought_and_rest[:marker.start()].strip()
        remainder = thought_and_rest[marker.start():].strip()
    else:
        thought_content = thought_and_rest.strip()
        remainder = ""

    if thought_content.startswith("Thought:"):
        thought_content = thought_content[len("Thought:"):].strip()

    if thought_content:
        parts.append(("thought", thought_content))
    if remainder:
        parts.append(("chat_stream", _format_chat_stream_content(remainder)))

    return parts


# 创建 FastAPI 应用
app = FastAPI(title="Agent SSE Server")

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def sse_event_generator(user_input: str, correlation_id: str = "") -> AsyncGenerator[str, None]:
    """
    生成 SSE 格式的事件流，与 WebSocket 输出结构完全一致
    事件类型包括：
    - CHAT_STREAM: 聊天流内容
    - THOUGHT: 思考内容
    - TOOL_START: 工具开始
    - TOOL_END: 工具结束
    - TASK_COMPLETE: 任务完成
    - ERROR: 错误
    
    每条消息包含以下字段：
    - type: 消息类型
    - id: 唯一消息ID
    - data: 消息数据
    - timestamp: ISO格式时间戳
    - correlation_id: 关联ID（与请求关联）
    """
    final_sent = False
    correlation_id = correlation_id or str(uuid.uuid4())  # 为整个对话生成一个关联ID
    bind_trace_id(correlation_id)
    task_logger.info("[SSE请求开始] correlation_id=%s | user_input=%s", correlation_id, _preview_text(user_input))
    agent = QwenAgent()

    llm_output_count = 0
    tool_call_count = 0
    tool_result_count = 0
    final_answer_count = 0
    error_count = 0
    # 记录最终结论是否已经通过流式增量输出（section=final_answer）推送过。
    # 如果推送过，整轮结束的 final_answer -> task_complete 就不再重复发，避免前端重复渲染；
    # 但最后仍会把所有 task_complete 增量拼接汇总为一条 task_finish。
    final_answer_streamed = False
    # 收集所有 task_complete 的增量，最后拼接成完整最终回答
    task_complete_chunks: List[str] = []
    # 若流式阶段没推送过，兜底走 final_answer 完整内容时，也记下来给 task_finish 使用
    fallback_complete_answer = None

    try:
        async for event in agent.async_call(user_input):
            event_type = event.get("type")

            if event_type == "llm_output":
                llm_output_count += 1
            elif event_type == "tool_call":
                tool_call_count += 1
                task_logger.info(
                    "[SSE关键事件] type=tool_call | correlation_id=%s | seq=%d | tool=%s | args=%s",
                    correlation_id,
                    tool_call_count,
                    event.get("tool_name"),
                    _preview_text(event.get("tool_args"), 300),
                )
            elif event_type == "tool_result":
                tool_result_count += 1
                task_logger.info(
                    "[SSE关键事件] type=tool_result | correlation_id=%s | seq=%d | tool=%s | result=%s",
                    correlation_id,
                    tool_result_count,
                    event.get("tool_name"),
                    _preview_text(event.get("raw_result") or event.get("result"), 300),
                )
            elif event_type == "final_answer":
                final_answer_count += 1
                task_logger.info(
                    "[SSE关键事件] type=final_answer | correlation_id=%s | seq=%d | content=%s",
                    correlation_id,
                    final_answer_count,
                    _preview_text(event.get("content"), 400),
                )
            elif event_type == "error":
                error_count += 1
                task_logger.error(
                    "[SSE关键事件] type=error | correlation_id=%s | seq=%d | content=%s",
                    correlation_id,
                    error_count,
                    _preview_text(event.get("content"), 400),
                )

            if event_type == "llm_output":
                # 如果上游已经按区段切好了（section 存在），严格按 section 的语义映射到用户约定类型：
                # - thought 区段 -> thought 事件（流式增量）
                # - chat_stream_section 区段（Action/Action Input 正文） -> chat_stream 事件（流式增量）
                # - final_answer 区段 -> task_complete 事件（流式增量，每 chunk 一条独立 task_complete）
                section_hint = event.get("section") or ""
                if section_hint:
                    message_content = event.get("content", "")
                    if not message_content:
                        continue

                    if section_hint == "thought":
                        normalized_type = "thought"
                        sse_data = {
                            "type": normalized_type,
                            "id": str(uuid.uuid4()),
                            "data": {
                                "content": message_content
                            },
                            "timestamp": datetime.now().isoformat(),
                            "correlation_id": correlation_id
                        }
                        yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
                        continue

                    if section_hint == "chat_stream_section":
                        normalized_type = "chat_stream"
                        sse_data = {
                            "type": normalized_type,
                            "id": str(uuid.uuid4()),
                            "data": {
                                "content": message_content
                            },
                            "timestamp": datetime.now().isoformat(),
                            "correlation_id": correlation_id
                        }
                        yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
                        continue

                    if section_hint == "final_answer":
                        # task_complete 流式增量：每一段 token 增量都作为一条独立的 type=task_complete 推送
                        final_answer_streamed = True
                        task_complete_chunks.append(message_content)
                        sse_data = {
                            "type": "task_complete",
                            "id": str(uuid.uuid4()),
                            "data": {
                                "content": message_content
                            },
                            "timestamp": datetime.now().isoformat(),
                            "correlation_id": correlation_id
                        }
                        yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
                        continue

                    # 未知 section：兜底归到 chat_stream
                    sse_data = {
                        "type": "chat_stream",
                        "id": str(uuid.uuid4()),
                        "data": {
                            "content": message_content
                        },
                        "timestamp": datetime.now().isoformat(),
                        "correlation_id": correlation_id
                    }
                    yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
                    continue

                # 兜底：如果上游没有 section，仍然做一次粗略拆分
                split_messages = _split_llm_content(event.get("content", ""))
                for message_type, message_content in split_messages:
                    if not message_content:
                        continue

                    # Final Answer 标记的正文：直接作为 task_complete 流式增量推送
                    if message_content.startswith("Final Answer:"):
                        final_answer_streamed = True
                        stripped = _strip_final_answer_prefix(message_content)
                        task_complete_chunks.append(stripped)
                        sse_data = {
                            "type": "task_complete",
                            "id": str(uuid.uuid4()),
                            "data": {
                                "content": stripped
                            },
                            "timestamp": datetime.now().isoformat(),
                            "correlation_id": correlation_id
                        }
                        yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
                        continue

                    normalized_type = _normalize_stream_type(message_type)
                    if normalized_type not in {"thought", "chat_stream", "task_complete"}:
                        normalized_type = "chat_stream"
                    # 兜底粗略拆分里，若非 Final Answer 区段被误判为 task_complete，降级为 chat_stream
                    if normalized_type == "task_complete":
                        normalized_type = "chat_stream"

                    sse_data = {
                        "type": normalized_type,
                        "id": str(uuid.uuid4()),
                        "data": {
                            "content": message_content
                        },
                        "timestamp": datetime.now().isoformat(),
                        "correlation_id": correlation_id
                    }
                    yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"

            elif event_type == "tool_call":
                # 工具开始事件：完整单条输出（不拆）
                sse_data = {
                    "type": "tool_start",
                    "id": str(uuid.uuid4()),
                    "data": {
                        "tool_name": _map_tool_name(event.get("tool_name")),
                        "tool_args": event.get("tool_args")
                    },
                    "timestamp": datetime.now().isoformat(),
                    "correlation_id": correlation_id
                }
                task_logger.info(
                    "[SSE输出] type=tool_start | correlation_id=%s | tool=%s | args=%s",
                    correlation_id,
                    _map_tool_name(event.get("tool_name")),
                    _preview_text(json.dumps(event.get("tool_args"), ensure_ascii=False) if isinstance(event.get("tool_args"), (dict, list)) else str(event.get("tool_args") or ""), 300),
                )
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"

            elif event_type == "tool_result":
                # 工具结束事件：完整单条输出（不拆）
                sse_data = {
                    "type": "tool_end",
                    "id": str(uuid.uuid4()),
                    "data": {
                        "tool_name": _map_tool_name(event.get("tool_name")),
                        "result": event.get("raw_result") or event.get("result")
                    },
                    "timestamp": datetime.now().isoformat(),
                    "correlation_id": correlation_id
                }
                task_logger.info(
                    "[SSE输出] type=tool_end | correlation_id=%s | tool=%s | result=%s",
                    correlation_id,
                    _map_tool_name(event.get("tool_name")),
                    _preview_text((event.get("raw_result") or event.get("result") or "") if isinstance(event.get("raw_result") or event.get("result"), str) else json.dumps(event.get("raw_result") or event.get("result") or {}, ensure_ascii=False), 300),
                )
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"

            elif event_type == "final_answer":
                # 最终完整事件：如果流式阶段已经按 task_complete 推送过增量，就不再重复推送整条；
                # 但无论走兜底时会记录下来给最后一条 task_finish 使用。
                if not final_sent and not final_answer_streamed:
                    complete_answer = _strip_final_answer_prefix(event.get("content", ""))
                    fallback_complete_answer = complete_answer
                    sse_data = {
                        "type": "task_complete",
                        "id": str(uuid.uuid4()),
                        "data": {
                            "content": complete_answer
                        },
                        "timestamp": datetime.now().isoformat(),
                        "correlation_id": correlation_id
                    }
                    task_logger.info(
                        "[SSE输出] type=task_complete(兜底) | correlation_id=%s | 回答长度=%d 字符 | 预览=%s",
                        correlation_id,
                        len(complete_answer or ""),
                        _preview_text(complete_answer or "", 400),
                    )
                    yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
                    final_sent = True

            elif event_type == "error":
                # 错误事件
                sse_data = {
                    "type": "error",
                    "id": str(uuid.uuid4()),
                    "data": {
                        "content": event.get("content", "")
                    },
                    "timestamp": datetime.now().isoformat(),
                    "correlation_id": correlation_id
                }
                yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"

        # 正常结束后，如果有 task_complete 增量或兜底完整内容，输出一条总结 task_finish
        if error_count == 0 and (task_complete_chunks or fallback_complete_answer is not None):
            if task_complete_chunks:
                final_summary = "".join(task_complete_chunks)
            else:
                final_summary = fallback_complete_answer or ""
            sse_data = {
                "type": "task_finish",
                "id": str(uuid.uuid4()),
                "data": {
                    "content": final_summary
                },
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id
            }
            task_logger.info(
                "[SSE输出] type=task_finish | correlation_id=%s | 总结长度=%d 字符 | 预览=%s",
                correlation_id,
                len(final_summary or ""),
                _preview_text(final_summary or "", 400),
            )
            yield f"data: {json.dumps(sse_data, ensure_ascii=False)}\n\n"
    finally:
        task_logger.info(
            "[SSE请求结束] correlation_id=%s | llm_output_chunks=%d | tool_calls=%d | tool_results=%d | final_answers=%d | errors=%d",
            correlation_id,
            llm_output_count,
            tool_call_count,
            tool_result_count,
            final_answer_count,
            error_count,
        )


async def _sse_event_generator_wrapper(user_input: str) -> AsyncGenerator[bytes, None]:
    """
    将字符串 SSE 事件显式编码并分段 flush，减少 Postman/nginx/ASGI 中间件的缓冲导致的“不流式”。
    """
    async for event_text in sse_event_generator(user_input):
        chunk = event_text.encode("utf-8")
        # 每段事件直接 flush，降低“整段返回”的概率
        yield chunk


def extract_user_message(data: Any) -> str:
    """
    智能提取用户消息，处理各种嵌套格式
    """
    if not data:
        return ""
    
    # 如果是字符串，尝试解析为 JSON
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            return data.strip()
    
    # 如果是字典，尝试提取 message 或 data.message
    if isinstance(data, dict):
        # 尝试直接获取 message
        if "message" in data:
            return extract_user_message(data["message"])
        
        # 尝试获取 data 字段
        if "data" in data:
            return extract_user_message(data["data"])
    
    # 如果是其他类型，转成字符串
    return str(data).strip()


@app.post("/chat")
async def chat_endpoint(request: Request):
    """
    SSE 聊天端点
    支持多种请求格式：
    
    格式 1（简单）：
    {
        "message": "你好，介绍下你自己"
    }
    
    格式 2（嵌套）：
    {
        "message": {
            "type": "chat_stream",
            "data": {
                "message": "实际消息内容"
            }
        }
    }
    """
    try:
        request_trace_id = bind_trace_id()
        body = await request.json()
        user_input = extract_user_message(body)
        client_host = request.client.host if request.client else "unknown"
        task_logger.info(
            "[HTTP请求接收] trace_id=%s | client=%s | path=%s | body=%s",
            request_trace_id,
            client_host,
            request.url.path,
            _preview_text(body)
        )
        
        if not user_input:
            task_logger.warning("[HTTP请求校验失败] 消息内容为空")
            return {"error": "消息内容不能为空"}
        
        print(f"接收到用户输入: {user_input[:100]}..." if len(user_input) > 100 else f"接收到用户输入: {user_input}")

        # 关键点：
        # 1. StreamingResponse 要求生成器输出 bytes（而不是 str），避免 uvicorn/Starlette 重新编码造成缓冲。
        # 2. media_type 与 charset 明确声明，避免某些客户端/代理按 text/plain 做缓冲或转码。
        # 3. 增加 Transfer-Encoding / X-Accel-Buffering / Cache-Control，降低 nginx、Postman、uwsgi 等中间件做“整段聚合”的概率。
        return StreamingResponse(
            _sse_event_generator_wrapper(user_input),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            }
        )
    except Exception as e:
        task_logger.error("[系统报错原因] 阶段=HTTP请求解析 | 错误=%s\n%s", str(e), traceback.format_exc())
        return {"error": f"请求解析失败: {str(e)}"}


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok"}


def main():
    """
    主函数 - 支持两种模式：
    1. 交互模式（默认）：直接运行 agent_caller.py 进入交互模式
    2. 服务器模式：运行 agent_caller.py server 启动 HTTP + SSE 服务器
    """
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        # 服务器模式：启动 FastAPI 服务器
        print("启动 Agent HTTP + SSE 服务器...")
        print("服务器地址: http://192.168.103.88:6799")
        print("健康检查: http://192.168.103.88:6799/health")
        print("聊天端点: http://192.168.103.88:6799/chat")
        
        uvicorn.run(
            app,
            host="192.168.103.88",
            port=6799,
            log_level="info"
        )
    else:
        # 交互模式
        agent = QwenAgent()
        agent.interactive_mode()


if __name__ == "__main__":
    main()
