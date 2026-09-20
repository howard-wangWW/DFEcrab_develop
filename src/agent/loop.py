"""
react_loop.py - ReAct 循环模块

实现 LLM 的 Reasoning + Acting 循环，让模型能够自主选择和调用技能。
集成 ToolRegistry 作为工具执行后端。
集成 UnifiedMemoryManager 实现记忆注入与沉淀。

使用示例：
    from src.agent.loop import ReActLoop
    from src.skill.registry import get_tool_registry
    
    loop = ReActLoop(llm_adapter, tool_registry)
    
    async for event in loop.run(
        messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
        agent_id="dfecrab"
    ):
        etype = event["type"]
        data = event.get("data", {})
        if etype == "tool_call":
            print(f"调用工具: {data.get('tool_name', '')}")
        elif etype == "message_end":
            print(f"最终回复: {data.get('full_response', '')}")
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.skill.registry import ToolRegistry, get_tool_registry
from src.skill.loader import SkillLoader, get_skill_loader
from src.agent.llm.adapter import LLMAdapter
from src.agent.agent_config import normalize_agent_id
from src.core.event_types import ReactEventType, make_event
from src.agent.multi.confirmation import ConfirmStatus
from src.utils.context_usage import DEFAULT_CONTEXT_LENGTH

logger = logging.getLogger("dfecrab.react")

# ──────────────────────────────────────────────────────────────
# ★ ReAct 运行时配置（对标 LibreChat：maxToolResultChars / 宽松轮次 + 保锚点裁剪）
# 来自 config/dfecrab.json 的 react 段，模块加载时读一次。
# ──────────────────────────────────────────────────────────────
_MAX_TOOL_RESULT_CHARS = 12000   # 单条工具结果回填上限（字符），超长截断
_MAX_CONTEXT_MESSAGES = 16       # 传给模型的上下文消息条数上限（保锚点裁剪）
# ★ deferred 工具（对标 LibreChat deferred_tools，默认关闭）：工具总数过多时按意图只下发子集
_TOOL_DEFER_ENABLED = False
_TOOL_DEFER_KEEP = 15            # 剪枝后保留的工具数
_TOOL_DEFER_MIN_TOOLS = 18       # 工具总数超过该值才启用剪枝
# ★ 工具结果预算（批次8 多现场自适应）：现场差异只体现在 provider 的 context_length。
#   单条 = min(max_tool_result_chars, 窗口 × tool_result_budget_ratio)
#   单轮累计 = 窗口 × tool_round_budget_ratio（事前配额，不做事后降级）
_TOOL_RESULT_BUDGET_RATIO = 0.25
_TOOL_ROUND_BUDGET_RATIO = 0.4
# ★ answer gate（步骤2）：工具型最终回复语义验证门控（Assessor.verify）
#   对标 CodeBuddy Craft「规划→执行→验证→修复」：正文先缓存，验证通过才流式展示，
#   不通过则带验证反馈重试（每请求至多 _ANSWER_GATE_MAX_RETRY 次，防死循环）。
_ANSWER_GATE_ENABLED = True
_ANSWER_GATE_MAX_RETRY = 1
_ANSWER_GATE_TIMEOUT = 60
# ★ 空回复兜底（对齐 vLLM 等网关偶发"空补全"——无 reasoning/content/tool_calls 即结束）：
#   已用过工具时注入提示重试至多 _EMPTY_REPLY_MAX_RETRY 次，仍为空则降级为占位提示，
#   绝不把空字符串当最终答案发给前端。配 react.empty_reply_max_retry 可覆盖。
_EMPTY_REPLY_MAX_RETRY = 1
# ★ Markdown 输出提示（步骤5，默认关）：对齐 LibreChat「前端渲染 GFM」链路——前端渲染依赖
#   模型输出结构化 Markdown；本地弱模型输出格式不稳定时可置 react.markdown_output_hint=true 开启。
_MARKDOWN_OUTPUT_HINT = False
# ★ ReAct 内 AutoCompact：上下文占用接近窗口阈值时，把旧轮压缩为"进展摘要"
# 对标 Claude Code AutoCompact / LibreChat summarization。
# 段合并兼容：阈值/保留轮数先读 react 段，回落旧 context_engine 段（下个大版本移除回落）。
_AUTO_COMPACT_THRESHOLD = 0.85
_COMPACT_KEEP_RECENT = 2
# ★ 进展便签（批次11-C2，对标 Claude Code scratchpad / OpenHands condenser）：
#   每轮工具调用后维护一条"到目前为止"的权威摘要注入 system，
#   让模型第 N 轮直接接着干，不再从"好的，用户让我…"重新复述任务。
#   纯程序化摘要（工具名+状态+结果关键标量），零关键词表；配 react.scratchpad / scratchpad_max_chars。
_SCRATCHPAD_ENABLED = True
_SCRATCHPAD_MAX_CHARS = 1500
_SCRATCH_MARKER = "【调查进展】"
# ★ ParamGuard（弱模型参数兜底，对齐"模型填充优先 + 代码兜底修复"）：
#   执行工具前纯规则校验；参数错/缺且代码能从用户原话确定性推导时自动修复。
#   强模型现场几乎零触发；弱模型现场修复率即"模型能力仪表盘"（见 param_guard 日志）。
_PARAM_GUARD_ENABLED = True
# ★ 查询/读类工具失败免人工确认的前缀（原逻辑对失败工具一律弹确认等 30s，
#   现场前端未实现确认 UI 时会静默等满超时；查询类失败直接回填错误交模型重试）。
_CONFIRM_EXEMPT_PREFIXES: List[str] = []
# ★ 直答工具（弱模型「收尾轮」不可靠时的确定性输出）：
#   命中工具成功返回后，直接把工具数据作为 message 输出并结束循环，
#   不再让模型组织第二轮回答。仅对配置的工具生效（如昆明 kunming_api），
#   其它智能体/工具流程完全不变。配 react.direct_answer_tools。
_DIRECT_ANSWER_TOOLS: List[str] = []
# ★ 单点加载：dfecrab.json 统一经 src/config/app_config.py 读取（步骤6 收敛，消除双段重复读）
try:
    from src.config.app_config import get_dfecrab
    _cfg_all = get_dfecrab() or {}
    _react_cfg = _cfg_all.get("react") or {}
    _ce_old = _cfg_all.get("context_engine") or {}
    if _react_cfg.get("max_tool_result_chars"):
        _MAX_TOOL_RESULT_CHARS = int(_react_cfg["max_tool_result_chars"])
    if _react_cfg.get("context_msg_limit"):
        _MAX_CONTEXT_MESSAGES = int(_react_cfg["context_msg_limit"])
    if _react_cfg.get("deferred_tools") is not None:
        _TOOL_DEFER_ENABLED = bool(_react_cfg["deferred_tools"])
    if _react_cfg.get("deferred_keep"):
        _TOOL_DEFER_KEEP = int(_react_cfg["deferred_keep"])
    if _react_cfg.get("tool_result_budget_ratio"):
        _TOOL_RESULT_BUDGET_RATIO = float(_react_cfg["tool_result_budget_ratio"])
    if _react_cfg.get("tool_round_budget_ratio"):
        _TOOL_ROUND_BUDGET_RATIO = float(_react_cfg["tool_round_budget_ratio"])
    if _react_cfg.get("answer_gate") is not None:
        _ANSWER_GATE_ENABLED = bool(_react_cfg["answer_gate"])
    if _react_cfg.get("answer_gate_max_retry") is not None:
        _ANSWER_GATE_MAX_RETRY = max(0, int(_react_cfg["answer_gate_max_retry"]))
    if _react_cfg.get("answer_gate_timeout"):
        _ANSWER_GATE_TIMEOUT = int(_react_cfg["answer_gate_timeout"])
    if _react_cfg.get("empty_reply_max_retry") is not None:
        _EMPTY_REPLY_MAX_RETRY = max(0, int(_react_cfg["empty_reply_max_retry"]))
    if _react_cfg.get("markdown_output_hint") is not None:
        _MARKDOWN_OUTPUT_HINT = bool(_react_cfg["markdown_output_hint"])
    if _react_cfg.get("scratchpad") is not None:
        _SCRATCHPAD_ENABLED = bool(_react_cfg["scratchpad"])
    if _react_cfg.get("scratchpad_max_chars"):
        _SCRATCHPAD_MAX_CHARS = int(_react_cfg["scratchpad_max_chars"])
    if _react_cfg.get("param_guard") is not None:
        _PARAM_GUARD_ENABLED = bool(_react_cfg["param_guard"])
    _exempt = _react_cfg.get("confirm_exempt_prefixes")
    if isinstance(_exempt, list):
        _CONFIRM_EXEMPT_PREFIXES = [str(p) for p in _exempt if str(p).strip()]
    _direct = _react_cfg.get("direct_answer_tools")
    if isinstance(_direct, list):
        _DIRECT_ANSWER_TOOLS = [str(t) for t in _direct if str(t).strip()]
    _thr = _react_cfg.get("auto_compact_threshold", _ce_old.get("auto_compact_threshold"))
    if _thr:
        _AUTO_COMPACT_THRESHOLD = float(_thr)
    _keep = _react_cfg.get("compact_keep_recent", _ce_old.get("compact_keep_recent"))
    if _keep is not None:
        _COMPACT_KEEP_RECENT = int(_keep)
except Exception:
    pass


def _is_confirm_exempt(tool_name: str) -> bool:
    """查询/读类工具（配置前缀命中）失败时免人工确认，错误直接回填给模型重试。"""
    if not tool_name or not _CONFIRM_EXEMPT_PREFIXES:
        return False
    return any(tool_name.startswith(p) for p in _CONFIRM_EXEMPT_PREFIXES)


def _tool_result_budget(context_length: int) -> int:
    """单条工具结果基础预算 = min(max_tool_result_chars, 窗口×ratio)"""
    if context_length and context_length > 0:
        return min(_MAX_TOOL_RESULT_CHARS, max(2000, int(context_length * _TOOL_RESULT_BUDGET_RATIO)))
    return _MAX_TOOL_RESULT_CHARS


def _tool_round_budget(context_length: int) -> int:
    """单轮工具结果累计预算 = 窗口×round_ratio（事前配额，多工具轮次保护）"""
    if context_length and context_length > 0:
        return max(4000, int(context_length * _TOOL_ROUND_BUDGET_RATIO))
    return _MAX_TOOL_RESULT_CHARS * 2


def _flatten_tool_result(tool_result) -> Any:
    """展平工具结果的多层协议包装，只保留服务端数据本体。

    包装链：ToolResult → execute_cached_tool{status,content,server,tool}
    → MCP result{content[].text / structuredContent}。
    保守策略：只剥已知包装键；isError 错误信号保留；剥不出已知结构则原样返回。
    """
    try:
        obj = tool_result.to_dict() if hasattr(tool_result, "to_dict") else tool_result
    except Exception:
        return tool_result
    # 1) ToolResult 层
    if isinstance(obj, dict) and set(obj.keys()) <= {"status", "content", "error"}:
        if obj.get("status") == "error" and obj.get("error"):
            return {"error": obj.get("error"), "content": obj.get("content")}
        obj = obj.get("content", obj)
    # 2) execute_cached_tool 层
    if isinstance(obj, dict) and set(obj.keys()) <= {"status", "content", "server", "tool"}:
        obj = obj.get("content", obj)
    # 3) MCP result 层（isError 须在 obj 被替换前取出）
    if isinstance(obj, dict):
        _is_err = bool(obj.get("isError"))
        flat = obj.get("structuredContent") if "structuredContent" in obj else None
        if flat is None and isinstance(obj.get("content"), list):
            texts = [i.get("text", "") for i in obj["content"]
                     if isinstance(i, dict) and i.get("type") == "text"]
            if texts:
                joined = "\n".join(texts)
                try:
                    flat = json.loads(joined)
                except Exception:
                    flat = joined
        if flat is not None:
            obj = flat
        if _is_err:
            obj = dict(obj) if isinstance(obj, dict) else {"data": obj}
            obj["_isError"] = True
    return obj


# ★ 直答可用的「人话文本」字段（各接口不同名，按优先级匹配）：
#   tiaozha/zaohui/today-*-trip/generate-excel → message
#   check_qualification/get_abnormal_signals/overload → result
#   注意：不能含 "content"（ToolResult 包装键），也不能含 "data"（结构化数据）
_DIRECT_TEXT_KEYS = ("message", "result", "text", "summary", "answer")


def _render_rows_text(columns: Any, rows: Any, limit: int = 8000) -> str:
    """SQL 查询结果（columns + data）→ 简易文本表格。"""
    cols = [str(c) for c in columns] if isinstance(columns, list) else []
    if not isinstance(rows, list) or not rows:
        return "查询成功，无数据。" if cols else "查询成功，无数据。"
    lines = [" | ".join(cols)] if cols else []
    for row in rows[:50]:
        if isinstance(row, dict):
            lines.append(" | ".join(str(row.get(c, "")) for c in cols) if cols else json.dumps(row, ensure_ascii=False, default=str))
        elif isinstance(row, (list, tuple)):
            lines.append(" | ".join(str(x) for x in row))
        else:
            lines.append(str(row))
    if len(rows) > 50:
        lines.append(f"...（共 {len(rows)} 行，仅展示前 50 行）")
    return "\n".join(lines)[:limit]


def _direct_answer_text(flat: Any, limit: int = 8000) -> str:
    """直答渲染：把工具返回渲染成可直接展示给用户的文本（不经 LLM）。

    优先级：
      1) 逐层剥包装时命中「人话文本」字段（message / result / text / summary…）
         —— 覆盖昆明全部接口的两种返回形态
      2) SQL 查询结果（columns + data）→ 文本表格
      3) 字符串本体 → 直接返回
      4) 保底：剥掉 status/endpoint 等包装层后 pretty JSON
    """
    if isinstance(flat, str):
        return flat[:limit]

    # 1) 逐层找文本字段（兼容 {status,content:{…,data:{message}}}/{status,data:{result}} 等）
    node = flat
    for _ in range(5):
        if not isinstance(node, dict):
            break
        for key in _DIRECT_TEXT_KEYS:
            val = node.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:limit]
        nxt = node.get("content")
        if not isinstance(nxt, dict):
            nxt = node.get("data")
        node = nxt

    # 2) SQL 查询结果（/query）→ 文本表格
    node = flat
    for _ in range(4):
        if not isinstance(node, dict):
            break
        if isinstance(node.get("columns"), list) and isinstance(node.get("data"), list):
            return _render_rows_text(node.get("columns"), node.get("data"), limit)
        nxt = node.get("content")
        if not isinstance(nxt, dict):
            nxt = node.get("data")
        node = nxt

    # 3) 保底：剥包装层渲染数据本体
    payload = flat
    for _ in range(3):
        if isinstance(payload, dict) and "data" in payload:
            payload = payload.get("data")
        else:
            break
    if isinstance(payload, str):
        return payload[:limit]
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = str(payload)
    return text[:limit]


def _smart_truncate_json_text(content: str, limit: int) -> str:
    """超大工具结果的智能截断（对标 LibreChat maxToolResultChars + 结构化保留）：
    可解析 JSON → 保留结构与统计字段；长列表元素做『语义投影』（只留标识/状态/数值字段），
    避免整份塞入；不可解析 → 硬切。均标注省略信息。"""
    if len(content) <= limit:
        return content
    try:
        obj = json.loads(content)
    except Exception:
        return content[:limit] + f"\n…[结果过长已截断，原长 {len(content)} 字符]"

    # ★ 语义投影字段：长列表中每个对象的保留键（标识 + 状态 + 数值类），其余省略
    _PROJECT_KEYS = (
        "id", "name", "label", "tag", "rawName", "dispatchNumber", "cabinet",
        "feederNo", "feederId", "file", "closed", "energized", "tiePoint",
        "status", "count", "total", "display", "color", "current",
    )

    def _project_item(d: dict):
        out = {}
        for k, v in d.items():
            if k in _PROJECT_KEYS:
                out[k] = _project_item(v) if isinstance(v, dict) else v
            elif isinstance(v, (int, float, bool)) or v is None:
                out[k] = v
            elif isinstance(v, str) and len(v) <= 60:
                out[k] = v
            # 长文本 / 大嵌套对象：省略
        return out

    def _shrink(v, depth=0):
        if depth > 3:
            return v
        if isinstance(v, str) and len(v) > 2000:
            return v[:2000] + f"…(截断，原 {len(v)} 字符)"
        if isinstance(v, list):
            if v and isinstance(v[0], dict):
                proj = [_project_item(x) for x in v]
                if len(proj) > 50:
                    return proj[:50] + [f"…(已省略 {len(proj) - 50} 项)"]
                return proj
            if len(v) > 50:
                return v[:50] + [f"…(已省略 {len(v) - 50} 项)"]
            return v
        if isinstance(v, dict):
            return {k: _shrink(x, depth + 1) for k, x in v.items()}
        return v

    shrunk = json.dumps(_shrink(obj), ensure_ascii=False, default=str)
    if len(shrunk) <= limit:
        return shrunk
    return shrunk[:limit] + f"\n…[结果过长已截断，原长 {len(content)} 字符]"


def _defer_tools_schema(tools_schema: List[Dict], user_text: str):
    """按用户意图剪枝工具（对标 LibreChat deferred_tools；默认关闭 `react.deferred_tools`）。
    仅当启用且工具总数超过 `_TOOL_DEFER_MIN_TOOLS` 时生效：按『工具名+描述』与用户消息的
    字符 2-gram 重叠打分，保留 top `_TOOL_DEFER_KEEP` 个；剪枝前后打印日志便于观察误剪。
    返回 (剪枝后的 schema, 被剪掉的工具名列表)。"""
    if not _TOOL_DEFER_ENABLED or len(tools_schema) <= _TOOL_DEFER_MIN_TOOLS:
        return tools_schema, []
    text = (user_text or "").strip()
    if not text:
        return tools_schema, []

    def _bigrams(s: str):
        s = s.lower()
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}

    query_grams = _bigrams(text)
    if not query_grams:
        return tools_schema, []

    scored = []
    for t in tools_schema:
        fn = t.get("function", {}) or {}
        blob = f"{fn.get('name', '')} {fn.get('description', '')}"
        scored.append((len(query_grams & _bigrams(blob)), t))
    scored.sort(key=lambda x: (-x[0], x[1].get("function", {}).get("name", "")))
    kept = [t for _, t in scored[:_TOOL_DEFER_KEEP]]
    kept_names = {t.get("function", {}).get("name", "") for t in kept}
    dropped = [t.get("function", {}).get("name", "")
               for t in tools_schema
               if t.get("function", {}).get("name", "") not in kept_names]
    logger.info(f"[ReAct] deferred_tools: {len(tools_schema)}→{len(kept)} 按意图下发，剪枝: {dropped}")
    return kept, dropped


# ──────────────────────────────────────────────────────────────
# 进展便签（批次11-C2，对标 Claude Code scratchpad / OpenHands condenser）
# ──────────────────────────────────────────────────────────────

def _scratch_compact_args(arguments: Any, limit: int = 100) -> str:
    """把工具调用参数压成一行（纯程序化，零关键词）：供便签记录"上轮用了什么定位条件"。"""
    try:
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        s = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        s = str(arguments)
    if len(s) > limit:
        return s[:limit] + "…"
    return s


def _scratchpad_text(lines: List[str], max_chars: int = 1500) -> str:
    """把便签行列表组合为一条 system 摘要（保留最新，超长从最旧截断）。

    固定附一句"接续引导"（行为准则，非关键词匹配），提示模型不要重述任务。
    """
    if not lines:
        return ""
    body = "\n".join(lines)
    guide = "\n> 上轮工具结果见上方 tool 消息。请直接基于已取结果继续推进/收尾，不要重新复述任务。"
    # 超长：优先保最新行（后进先裁 → 从最旧行删）
    if len(body) > max_chars:
        kept = [lines[-1]]
        acc = len(lines[-1])
        for ln in reversed(lines[:-1]):
            if acc + len(ln) + 1 > max_chars:
                break
            kept.insert(0, ln)
            acc += len(ln) + 1
        body = "\n".join(kept)
    return _SCRATCH_MARKER + "\n" + body + guide


async def _react_compact_history(llm_adapter, chat_messages: List[Dict], keep_recent: int = 2):
    """ReAct 循环内 AutoCompact：把『原始任务之后、最近 keep_recent 轮之前』的旧轮次，
    用 LLM 压缩为一条"先前调查进展"摘要消息并替换。
    失败/无可压缩 → 返回 None（调用方降级不压缩，不阻塞循环）。"""
    try:
        anchor = None
        for i, m in enumerate(chat_messages):
            if m.get("role") != "system":
                anchor = i
                break
        if anchor is None:
            return None
        cut = len(chat_messages) - keep_recent * 2   # 每轮约 2 条(assistant+tool)
        if cut <= anchor + 1:
            return None
        old = chat_messages[anchor:cut]
        text_parts = []
        for m in old:
            _c = str(m.get("content", "")) if m.get("content") is not None else ""
            if m.get("tool_calls"):
                _names = [t.get("function", {}).get("name", "") for t in m.get("tool_calls", [])]
                _c += f" [调用工具: {','.join(_names)}]"
            text_parts.append(f"[{m.get('role', '?')}] {_c[:500]}")
        prompt = (
            "以下是多步工具调查任务中已经完成的部分（较早的将不再展示）。请把它压缩成一段"
            "「先前调查进展」，保留：已确认的关键事实/已定位的对象、已排除的干扰项、下一步意图。\n"
            "控制在 200 字以内的要点式，不要编造。\n\n" + "\n".join(text_parts)[:3000]
        )
        summary_result = await llm_adapter.chat_with_tools(
            messages=[{"role": "system", "content": prompt}],
            tools=[],
            tool_choice="none",
            temperature=0.2,
            max_tokens=300,
        )
        summary = (summary_result.get("content") or "").strip().strip("`") if isinstance(summary_result, dict) else str(summary_result).strip()
        if not summary:
            return None
        return chat_messages[:anchor] + [
            {"role": "system", "content": f"【先前调查进展（已完成部分已压缩）】\n{summary}"}
        ] + chat_messages[cut:]
    except Exception as e:
        logger.warning(f"[ReAct] 历史压缩失败（降级不压缩）: {e}")
        return None


class ReActLoop:
    """ReAct 循环
    
    实现 LLM 驱动的工具调用循环：
    1. 将可用工具注册到 LLM
    2. LLM 返回工具调用指令
    3. 执行工具并将结果添加到上下文
    4. 继续循环直到 LLM 返回最终回复
    """
    
    def __init__(
        self,
        llm_adapter: LLMAdapter,
        tool_registry: Optional[ToolRegistry] = None,
        skill_loader: Optional[SkillLoader] = None,
        max_iterations: int = 3
    ):
        """初始化 ReAct 循环
        
        Args:
            llm_adapter: LLM 适配器实例
            tool_registry: 工具注册表实例
            max_iterations: 最大循环次数（防止死循环）
        """
        self.llm_adapter = llm_adapter
        self.tool_registry = tool_registry or get_tool_registry()
        self.skill_loader = skill_loader or get_skill_loader()
        self.max_iterations = max_iterations
        # ★ S5.1: Assessor（延迟初始化）
        self._assessor = None

    @staticmethod
    def _extract_user_text(messages: List[Dict]) -> str:
        user_messages = [
            str(msg.get("content", "")).strip()
            for msg in messages
            if msg.get("role") == "user" and msg.get("content")
        ]
        if not user_messages:
            return ""
        return "\n".join(user_messages[-3:]).strip()

    @staticmethod
    def _merge_system_prompts(base_prompt: str, skill_prompt: str) -> str:
        if base_prompt and skill_prompt:
            return f"{base_prompt}\n\n{skill_prompt}"
        return base_prompt or skill_prompt or ""

    @staticmethod
    def _compose_usage(
        llm_usage: Optional[Dict],
        system_prompt: str,
        memory_text: str,
        skill_prompt: str,
        tools: List[Any],
        history: List[Dict],
        current: str,
        tool_results: List[Dict],
        context_length: int = DEFAULT_CONTEXT_LENGTH,
        model: str = "",
    ) -> Dict:
        """构建上下文占用统计（message_end 事件携带，供前端展示 token 占比）。

        参考 CodeBuddy / Claude Code 的 context usage 指示器：分类为本地估算（
        history/current/tool_results 细分），token 总数优先用 LLM 返回的 usage，
        未返回时本地估算兜底；LLM usage 时分类会归一化到 prompt_tokens。
        model 记录实际使用模型，供多模型对话时按模型统计。
        """
        from src.utils.context_usage import build_context_usage
        return build_context_usage(
            llm_usage=llm_usage,
            system_prompt=system_prompt,
            memory_text=memory_text,
            skill_prompt=skill_prompt,
            tools=tools,
            history=history,
            current=current,
            tool_results=tool_results,
            context_length=context_length,
            model=model,
        )

    async def _assess_response(
        self,
        content: str,
        ctx: Dict[str, Any],
    ) -> "Assessment":
        """★ S5.1: 调用 Assessor 评估回复质量

        Args:
            content: 回复文本
            ctx: 上下文（tools_used, iterations, message）

        Returns:
            Assessment: 评估结果
        """
        try:
            from src.agent.multi.assessor import get_self_assessor, Assessment
            if self._assessor is None:
                self._assessor = get_self_assessor()
                self._assessor.set_llm_adapter(self.llm_adapter)

            return await self._assessor.assess(content, ctx)
        except Exception as e:
            logger.warning(f"[ReAct] Assessor 调用异常，默认通过: {e}")
            from src.agent.multi.assessor import Assessment, AssessmentStatus
            return Assessment(
                quality_score=0.6,
                quality_level="medium",
                need_help=False,
                reason=f"Assessor异常降级: {e}",
                assessment_method="skipped",
                status=AssessmentStatus.SKIPPED,
            )

    async def _verify_final_answer(
        self,
        user_text: str,
        final_content: str,
        tool_names: List[str],
    ) -> tuple:
        """★ answer gate：语义验证最终回复（Assessor.verify，纯语义判定，无关键词表）。

        Returns:
            (passed: bool, feedback: str)；任何异常默认放行 (True, "")，不阻塞主流程。
        """
        try:
            from src.agent.multi.assessor import get_self_assessor
            if self._assessor is None:
                self._assessor = get_self_assessor()
                self._assessor.set_llm_adapter(self.llm_adapter)
            _verification = await self._assessor.verify(
                content=final_content,
                ctx={
                    "message": user_text,
                    "tool_names": tool_names,
                    "tools_used": len(tool_names),
                },
            )
            return _verification.passed, _verification.feedback
        except Exception as e:
            logger.warning(f"[AnswerGate] verify 调用异常，默认放行: {e}")
            return True, ""

    async def run(
        self,
        messages: List[Dict],
        agent_id: str = "dfecrab",
        enabled_skills: Optional[List[str]] = None,
        system_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tool_choice: str = "auto",
        mcp_servers: Optional[List[str]] = None,
        user_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """运行 ReAct 循环
        
        Args:
            messages: 初始消息列表
            agent_id: Agent ID
            enabled_skills: 启用的技能列表（None表示使用ToolRegistry中所有可用技能）
            system_prompt: 系统提示
            temperature: 温度参数
            max_tokens: 最大 token 数
            tool_choice: 工具选择策略 (auto/required/none)，默认 auto。
                       required 仅约束第 1 轮（强制先调工具取数），后续轮自动回退 auto 便于收尾
            mcp_servers: 可选，运行时临时覆盖该 agent 可用的 MCP 服务名列表（对话传参，不落盘）
            
        Yields:
            协议事件字典: {"type": str, "data": dict, "timestamp": float}
            type 取值: tool_call | tool_result | message_end | error | confirmation | skill_match
        """
        # 0. 兼容旧 ID（default → dfecrab），确保记忆/工具路径解析正确
        agent_id = normalize_agent_id(agent_id) or "dfecrab"

        # ★ 单轮 LLM 超时：agent_defaults.llm_timeout（AgentConfig 合并，agent 级可覆盖），兜底 180s
        _llm_timeout = 180
        try:
            from src.agent.agent_config import AgentConfig
            _llm_timeout = int(getattr(AgentConfig.from_id(agent_id), "llm_timeout", 180) or 180)
        except Exception:
            pass
        _loop_timeout = max(_llm_timeout * 3, 300)  # 外层总超时：单轮的 3 倍起步，兜底 300s

        # 0. ★ P0-2: 获取记忆上下文并注入 system prompt（用户画像 + 相关经验 + 近期日志）
        memory_context_text = ""
        used_tools: List[str] = []
        try:
            from src.memory.unified_manager import get_unified_manager
            memory_mgr = get_unified_manager()
            memory_context_text = await memory_mgr.build_context_text(
                agent_id=agent_id, user_id=user_id or None)
            if memory_context_text:
                memory_context_text = "## 相关历史记忆\n" + memory_context_text
                logger.info(f"[ReAct] 已加载记忆上下文 (agent={agent_id})")
        except Exception as e:
            logger.warning(f"[ReAct] 加载记忆上下文失败（降级继续）: {e}")

        # ★ S4.2: 按 agent_id 过滤工具列表（Agent 级技能隔离）
        #   enabled_skills 是外部传入的运行时过滤（通常为 None），
        #   list_tools_for_agent 读取 agents/{agent_id}/config.json 的 skills_whitelist；
        #   mcp_servers 为运行时临时覆盖该 agent 的 MCP 服务（对话传参，不落盘）
        tools_schema = self.tool_registry.list_tools_for_agent(
            agent_id, bound_servers_override=mcp_servers
        )
        
        # 1.5 根据用户输入自动匹配技能说明，并注入到 system prompt
        user_text = self._extract_user_text(messages)
        skill_context = self.skill_loader.build_injected_prompt(
            user_text=user_text,
            enabled_skills=enabled_skills
        )

        # ★ deferred 工具（默认关闭 `react.deferred_tools`）：工具总数过多时按用户意图只下发相关子集
        tools_schema, _ = _defer_tools_schema(tools_schema, user_text)

        composed_system_prompt = self._merge_system_prompts(
            system_prompt,
            skill_context.get("prompt", "")
        )
        # ★ P0-2: 记忆上下文前置到 system prompt
        if memory_context_text:
            composed_system_prompt = f"{memory_context_text}\n\n{composed_system_prompt}"

        if skill_context.get("matched_skills"):
            logger.info(
                "[ReAct] 自动匹配技能: %s",
                [
                    {
                        "skill_id": item["skill_id"],
                        "score": item["score"],
                    }
                    for item in skill_context["matched_skills"]
                ]
            )
            # ★ v4.0: skill_match 作为独立事件，不再混入 thinking
            yield {
                "type": "skill_match",
                "data": {
                    "skills": skill_context["matched_skills"],
                    "agent_id": agent_id,
                },
                "timestamp": time.time(),
            }

        # ★ 工具注入筛选（v4.4，参考成熟平台）：
        #   本地技能按 agent 白名单(enabled_skills)全量保留——不再按 skill_match/消息关键词砍本地技能
        #   （修复 v4.2 误杀 code_executor/knowledge_qa 等本地技能导致"无工具可用"的故障）；
        #   MCP 由 registry.list_tools_for_agent 决定（仅显式传 mcp_servers 才装配），此处不再二次筛除。
        if enabled_skills:
            _local_names = self.tool_registry.local_tool_names
            tools_schema = [
                t for t in tools_schema
                if t["function"]["name"] in enabled_skills          # 本地按白名单保留
                or t["function"]["name"] not in _local_names        # MCP 工具放行
            ]
        if tools_schema:
            logger.info(f"[ReAct] 工具注入筛选后: {[t['function']['name'] for t in tools_schema]}")

        # ★ S1.3: 有工具时引导模型优先调工具（auto 决策，不强制首轮必须调）
        #   注：用筛选后的工具名单，避免模型被告知的工具多于实际下发的 Schema（幻觉调用风险）
        if tools_schema:
            tool_names = [t["function"]["name"] for t in tools_schema]
            tool_constraint = (
                "\n\n## 工具调用规则（必须遵守）\n"
                "1. 若用户请求可用工具完成，你应优先调用工具回答，不要凭知识直接给答案\n"
                "2. 除非所有工具都执行失败，否则不能以\"我不知道\"结束\n"
                "3. 工具返回结果后，用自然语言向用户解释结果\n"
                "4. 若已调用过工具并拿到结果，请直接基于工具返回结果组织最终回答，不要重复分析用户需求\n"
                f"5. 可用工具列表: {', '.join(tool_names)}\n"
            )
            composed_system_prompt += tool_constraint

        # ★ Markdown 输出规范（步骤5，默认关；开启见 react.markdown_output_hint）。
        #   对齐 LibreChat：前端按 GFM 渲染，后端只需让模型输出结构化 Markdown。
        if _MARKDOWN_OUTPUT_HINT:
            composed_system_prompt += (
                "\n\n## 输出格式要求（必须遵守）\n"
                "回复使用 Markdown 组织：分节用 # 标题；多项对比用 | 表格 |；"
                "操作/步骤用有序列表；关键结论用 **加粗**。"
            )

        if not tools_schema:
            # 无可用工具，直接调用 LLM（流式，思考 + 正文实时输出）
            # ★ v4.4: 补齐 message_start/message 逐 token 事件，与工具分支同构（纯聊也流式）
            logger.info(f"[ReAct] 无可用工具，直接调用 LLM（流式）")
            full_response = ""
            full_reasoning = ""
            _usage = None
            _msg_started = False
            yield make_event(ReactEventType.THINK_START, phase="worker", iteration=0)
            async for event in self.llm_adapter.call_stream(
                prompt=messages[-1]["content"] if messages else "",
                system_prompt=composed_system_prompt
            ):
                if event["type"] == "reasoning":
                    full_reasoning += event["content"]
                    yield make_event(ReactEventType.THINK, chunk=event["content"], phase="worker", iteration=0)
                elif event["type"] == "token":
                    full_response += event["content"]
                    # ★ 正文首 token 前补发 think_end + message_start，然后逐 token 转发
                    if not _msg_started:
                        yield make_event(ReactEventType.THINK_END, full_reasoning=full_reasoning, phase="worker", iteration=0)
                        yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                        _msg_started = True
                    yield make_event(ReactEventType.MESSAGE, chunk=event["content"], iteration=0)
                elif event["type"] == "usage":
                    _usage = event.get("usage", {})
            if not _msg_started:
                # 无正文 token（纯思考），仍需发 think_end + message_start 保证事件序列完整
                yield make_event(ReactEventType.THINK_END, full_reasoning=full_reasoning, phase="worker", iteration=0)
                yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
            yield make_event(
                ReactEventType.MESSAGE_END,
                full_response=full_response, iterations=0, tools_used=[],
                usage=self._compose_usage(
                    _usage, system_prompt, memory_context_text,
                    skill_context.get("prompt", ""), [],
                    messages[:-1] if len(messages) > 1 else [],
                    messages[-1].get("content", "") if messages else "",
                    [],
                    getattr(self.llm_adapter, "context_length", DEFAULT_CONTEXT_LENGTH),
                    getattr(self.llm_adapter, "model_name", ""),
                ),
            )
            return
        
        logger.info(f"[ReAct] 启动循环，可用工具: {[t['function']['name'] for t in tools_schema]}")

        # ★ S2.5: 预留 plan_created 事件（阶段3 接通 Planner 后生效）
        #   当前 complex 模式不创建真实 plan，阶段3 会在此处调用 planner.create_plan()
        #   并通过 use_plan 参数决定是否走 plan 模式
        # yield make_event(
        #     ReactEventType.PLAN_CREATED,
        #     plan_id=f"plan_{uuid.uuid4().hex[:8]}",
        #     steps=[t["function"]["name"] for t in tools_schema],
        #     total_steps=len(tools_schema),
        # )
        
        # 2. 构建消息列表
        chat_messages = []
        if composed_system_prompt:
            chat_messages.append({"role": "system", "content": composed_system_prompt})
        chat_messages.extend(messages)

        # ★ 批次8：工具结果预算按当前模型窗口动态计算（多现场自适应，代码零分支）
        _ctx_len = getattr(self.llm_adapter, "context_length", 0) or 0
        _tool_base_budget = _tool_result_budget(_ctx_len)
        _tool_round_left = _tool_round_budget(_ctx_len)   # 单轮剩余配额（每轮重置）
        _est_used_cache = -1                              # 轮内 token 估算缓存（多条工具共用一次）

        # ★ 上下文统计：工具分支共用的 usage 构造（多个 MESSAGE_END 出口复用，避免重复代码）
        def _make_usage(llm_usage: Optional[Dict]) -> Dict:
            _hist = messages[:-1] if len(messages) > 1 else []
            _cur = messages[-1].get("content", "") if messages else ""
            _tool_res = [m for m in chat_messages if m.get("role") == "tool"]
            return self._compose_usage(
                llm_usage,
                system_prompt + (tool_constraint if tools_schema else ""),
                memory_context_text,
                skill_context.get("prompt", ""),
                tools_schema,
                _hist, _cur, _tool_res,
                getattr(self.llm_adapter, "context_length", DEFAULT_CONTEXT_LENGTH),
                getattr(self.llm_adapter, "model_name", ""),
            )

        # ★ 进展便签（批次11-C2）：记录已执行轮次的程序化摘要，轮首注入 system 供模型接续
        _scratch_lines: List[str] = []

        # ★ P0-2: 重复工具调用检测 — 同一工具同一参数第 2 次直接跳过
        _called_tool_signatures: List[str] = []
        llm_result = {"content": "", "tool_calls": [], "finish_reason": "stop", "usage": {}}  # 超时兜底
        # ★ v4.1: message_start 是否已发出（每轮重置；保证 message_start 在首个 message chunk 之前）
        _message_started = False
        # ★ required 首轮兜底重试标志（第 1 轮强制调工具失败时只允许降级/重试一次）
        _round0_forced_retried = False
        # ★ 直答标志：直答工具成功返回后置 True，循环直接收尾（不再走模型收尾轮）
        _direct_answered = False
        _empty_retries = 0        # ★ 空回复兜底：本请求已注入的空回复重试次数（防死循环）
        _react_compacted = False  # ★ ReAct 内 AutoCompact：每请求至多压缩一次，避免反复触发
        # ★ answer gate（步骤2）：仅当启用 + 有工具 + 允许重试时生效
        _answer_gate_on = bool(
            _ANSWER_GATE_ENABLED and _ANSWER_GATE_MAX_RETRY > 0 and tools_schema
        )
        _gate_retries = 0          # 本次请求已触发的门控重试次数（防死循环）

        # 3. ReAct 循环（单轮超时见 _llm_timeout；外层 _loop_timeout 仅兜底工具执行/其它卡死）
        try:
            async with asyncio.timeout(_loop_timeout):
                for iteration in range(self.max_iterations):
                    # ★ 工具结果预算每轮重置（批次8 事前配额）
                    _tool_round_left = _tool_round_budget(_ctx_len)
                    _est_used_cache = -1
                    # ★ answer gate：已用过工具后（候选最终回复轮）正文先缓存、验证通过再流式；
                    #   纯聊天/首轮未用工具不缓存（保持逐 token 实时性）
                    _buf_mode = bool(_answer_gate_on and used_tools)
                    _final_buf: List[str] = []
                    # ★ 上下文裁剪（对标 LangGraph：完整历史 + 永不丢任务锚点）：
                    #   超过 _MAX_CONTEXT_MESSAGES 时，优先丢最老的 tool 结果、其次中间轮 assistant；
                    #   system 与第一条 user（原始任务）永远保留——避免"思考重启"式失忆。
                    while len(chat_messages) > _MAX_CONTEXT_MESSAGES:
                        _protected = {i for i, m in enumerate(chat_messages) if m.get("role") == "system"}
                        for i, m in enumerate(chat_messages):
                            if m.get("role") != "system":
                                _protected.add(i)   # 第一条非 system = 原始用户任务
                                break
                        _drop = None
                        for i, m in enumerate(chat_messages):
                            if i not in _protected and m.get("role") == "tool":
                                _drop = i          # 优先丢最老工具结果
                                break
                        if _drop is None:
                            _drop = next((i for i, m in enumerate(chat_messages) if i not in _protected), None)
                        if _drop is None:
                            break
                        chat_messages.pop(_drop)

                    # ★ ReAct 内 AutoCompact：上下文占用接近窗口阈值时，把旧轮压缩为进展摘要
                    #   （对标 Claude Code AutoCompact / LibreChat summarization；每请求至多一次，
                    #    摘要失败静默降级，不阻塞循环）
                    _ctx_len = getattr(self.llm_adapter, "context_length", 0) or 0
                    if (not _react_compacted and _ctx_len > 0
                            and self.llm_adapter._estimate_input_tokens(chat_messages) > int(_ctx_len * _AUTO_COMPACT_THRESHOLD)):
                        try:
                            async with asyncio.timeout(min(60, _llm_timeout)):
                                _new_msgs = await _react_compact_history(
                                    self.llm_adapter, chat_messages, _COMPACT_KEEP_RECENT)
                            if _new_msgs:
                                chat_messages = _new_msgs
                                _react_compacted = True
                                logger.info(f"[ReAct] AutoCompact 触发：旧轮已压缩为进展摘要 (msgs={len(chat_messages)})")
                        except Exception:
                            logger.debug("[ReAct] AutoCompact 跳过（异常）", exc_info=True)

                    # ★ 批次11-C2：注入"已执行进展"便签（程序化摘要，供模型接续不重述）。
                    #   先移除上一轮注入的旧便签，再在末尾追加最新版；有便签内容才注入。
                    if _SCRATCHPAD_ENABLED and _scratch_lines:
                        _scratch_text = _scratchpad_text(_scratch_lines, _SCRATCHPAD_MAX_CHARS)
                        chat_messages = [
                            m for m in chat_messages
                            if not (m.get("role") == "system"
                                    and str(m.get("content", "")).startswith(_SCRATCH_MARKER))
                        ]
                        chat_messages.append({"role": "system", "content": _scratch_text})
                        logger.debug(f"[ReAct] 进展便签已注入 ({len(_scratch_lines)} 轮)")

                    logger.info(f"[ReAct] 第 {iteration + 1}/{self.max_iterations} 轮")
                    # ★ v4.0: 每轮思考流开始（三段式：think_start → think → think_end）
                    yield make_event(ReactEventType.THINK_START, phase="worker", iteration=iteration + 1)
                    _message_started = False  # ★ v4.1: 每轮重置 message_start 标志
                    _think_end_sent = False   # ★ v4.1: 每轮重置 think_end 标志（思考结束即首个 token 时发出）

                    # ★ required 语义：仅约束第 1 轮（保证先调工具取数）；拿到工具结果后
                    #   第 2 轮起回到 auto，允许模型基于真实结果自主收尾，避免被强制重复调工具。
                    if tool_choice == "required":
                        round_tool_choice = "required" if iteration == 0 else "auto"
                    else:
                        round_tool_choice = tool_choice
                    # ★ required 第 1 轮正文不实时转发：强制轮若被后端静默忽略而直接输出文本，
                    #   会先向用户展示一段"幻觉直答"，再触发重试造成双重输出。故首轮正文先缓冲，
                    #   待确认有工具调用/进入后续轮次后再正常流式转发。
                    _suppress_round0_text = bool(tool_choice == "required" and iteration == 0)

                    # 3.1 调用 LLM（带工具，流式输出 worker 思考）
                    llm_result = {"content": "", "tool_calls": [], "finish_reason": "stop", "usage": {}}
                    _iter_reasoning = ""
                    try:
                        # ★ 每轮 LLM 调用独立超时（_llm_timeout，默认 180s）：单轮慢不拖死整个循环
                        async with asyncio.timeout(_llm_timeout):
                            async for event in self.llm_adapter.chat_with_tools_stream(
                                messages=chat_messages,
                                tools=tools_schema,
                                tool_choice=round_tool_choice,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                # ★ 取消 no_think：每一轮都保留完整思考链（含工具结果整理轮），
                                #   避免历史接口出现空 thinking（如 "\n\n"）。参考成熟平台完整展示推理。
                                no_think=False,
                            ):
                                etype = event.get("type")
                                if etype == "think":
                                    _chunk = event.get("content", "")
                                    _iter_reasoning += _chunk
                                    yield make_event(ReactEventType.THINK, chunk=_chunk, phase="worker", iteration=iteration + 1)
                                elif etype == "token":
                                    _tok = event.get("content", "")
                                    llm_result["content"] += _tok
                                    # ★ required 第 1 轮：正文先缓冲不转发（见 _suppress_round0_text 说明），
                                    #   避免"幻觉直答先展示、再触发重试"的双重输出；think_end 由下方兜底补发。
                                    if _suppress_round0_text:
                                        continue
                                    # ★ answer gate：工具型候选最终回复正文先缓存，验证通过后才流式；
                                    #   验证失败时丢弃缓存重试，避免把"带占位/估算/答非所问"的草稿展示给用户。
                                    if _buf_mode:
                                        _final_buf.append(_tok)
                                        continue
                                    # ★ v4.1: 正文 token 实时流式 yield 给前端
                                    #   之前仅累加到 llm_result 不转发，前端在思考结束后的静默期(5.4s+)
                                    #   看不到正文，直至 message_end 一次性收到完整内容。现逐 token 转发。
                                    #   思考结束（首个 token）时立即发出 think_end，再进入正文流式。
                                    if not _think_end_sent:
                                        yield make_event(ReactEventType.THINK_END, full_reasoning=_iter_reasoning, phase="worker", iteration=iteration + 1)
                                        _think_end_sent = True
                                    if not _message_started:
                                        yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                                        _message_started = True
                                    yield make_event(ReactEventType.MESSAGE, chunk=_tok, iteration=iteration + 1)
                                elif etype == "tool_calls":
                                    llm_result["tool_calls"] = event.get("tool_calls", [])
                                elif etype == "usage":
                                    # ★ 上下文统计：记录本轮 LLM usage（最后一轮即最终上下文占用）
                                    llm_result["usage"] = event.get("usage", {})
                                elif etype == "done":
                                    llm_result["finish_reason"] = event.get("finish_reason", "stop")
                                elif etype == "error":
                                    raise RuntimeError(event.get("content", "LLM 调用失败"))
                    except asyncio.TimeoutError:
                        # ★ 单轮 LLM 超时：用已收集内容兜底返回，不再拖死整个循环
                        logger.warning(f"[ReAct] 第 {iteration + 1} 轮 LLM 超时（>60s），基于已有结果直接返回")
                        summary_content = (llm_result.get("content") or "").strip() or "（执行超时，未能生成完整回复）"
                        if not _think_end_sent:
                            yield make_event(ReactEventType.THINK_END, full_reasoning=_iter_reasoning, phase="worker", iteration=iteration + 1)
                        if not _message_started:
                            yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                        yield make_event(
                            ReactEventType.MESSAGE_END,
                            full_response=summary_content, iterations=iteration + 1,
                            tools_used=list(used_tools),
                            usage=_make_usage(llm_result.get("usage")),
                        )
                        return
                    except Exception as e:
                        logger.error(f"[ReAct] LLM 调用失败: {e}")
                        # ★ required 兼容降级：旧版 vLLM 等后端可能不支持 tool_choice="required"，
                        #   该类错误发生在请求发前（尚未产出流式内容，可安全重试）：降级 auto + 强提示
                        _err_text = str(e)
                        if (
                            iteration == 0
                            and tool_choice == "required"
                            and not _round0_forced_retried
                            and tools_schema
                            and (
                                "tool_choice" in _err_text
                                or "required" in _err_text
                                or "400" in _err_text
                                or "bad request" in _err_text.lower()
                            )
                        ):
                            _round0_forced_retried = True
                            _names = ", ".join(t["function"]["name"] for t in tools_schema)
                            logger.warning(f"[ReAct] required 不支持/调用失败，降级 auto 并追加强提示重试: {e}")
                            chat_messages.append({
                                "role": "system",
                                "content": (
                                    f"你必须调用以下工具之一完成查询：{_names}\n"
                                    "禁止凭记忆或想象编造数据，必须先取得工具返回结果再作答。"
                                ),
                            })
                            if not _think_end_sent:
                                yield make_event(ReactEventType.THINK_END, full_reasoning=_iter_reasoning, phase="worker", iteration=iteration + 1)
                            continue
                        yield make_event(ReactEventType.ERROR, message=str(e), iteration=iteration + 1)
                        break

                    # ★ v4.0: 本轮思考流结束（grpc_server 依赖此事件收集 worker_reasoning；非流式模式依赖它展示思考）
                    #   ★ v4.1: 已产出正文 token 时 think_end 已在首个 token 前发出，此处仅兜底（纯思考无正文轮）
                    if not _think_end_sent:
                        yield make_event(ReactEventType.THINK_END, full_reasoning=_iter_reasoning, phase="worker", iteration=iteration + 1)
                    logger.info(
                        f"[ReAct] 第 {iteration + 1} 轮思考完成 | reasoning_len={len(_iter_reasoning)} | "
                        f"reasoning={_iter_reasoning[:200]}"
                    )

                    # 3.3 检查是否有工具调用
                    tool_calls = llm_result.get("tool_calls", [])
                    # ★ 修复：以 tool_calls 为准判断。原条件含 finish_reason=="stop"，若后端在带
                    #   tool_calls 时仍返回 stop（部分兼容层行为），会把工具调用误判为最终回复，
                    #   导致"模型发了调用请求却不执行"。故只要存在工具调用就先执行工具。
                    if not tool_calls:
                        # ★ required 首轮兜底：若强制轮仍未产生工具调用（后端静默忽略 required /
                        #   模型直接输出文本），追加"必须先调工具"提示重试一轮，杜绝不调技能直接编造
                        if (
                            iteration == 0
                            and tool_choice == "required"
                            and not _round0_forced_retried
                            and tools_schema
                        ):
                            _round0_forced_retried = True
                            _names = ", ".join(t["function"]["name"] for t in tools_schema)
                            logger.warning(
                                "[ReAct] 第 1 轮 required 未产生工具调用，追加强制调工具提示重试"
                            )
                            chat_messages.append({
                                "role": "system",
                                "content": (
                                    "你刚才的回复没有调用任何工具，但当前任务必须先通过工具获取真实数据。\n"
                                    f"请立即调用以下可用工具之一完成查询：{_names}\n"
                                    "禁止凭记忆或想象编造数据，必须先取得工具返回结果再作答。"
                                ),
                            })
                            continue
                        # LLM 返回最终回复
                        final_content = llm_result.get("content", "")
                        # ★ 空回复兜底：模型/推理网关偶发返回空补全（无 reasoning/content/tool_calls，
                        #   典型表现是工具多轮后"秒回"结束）。绝不把空字符串当最终答案发给前端：
                        #   已用过工具 → 注入提示重试（至多 _EMPTY_REPLY_MAX_RETRY 次）；
                        #   仍为空 → 降级为明确的占位提示，方便用户感知并重试。
                        if not final_content.strip():
                            if used_tools and _empty_retries < _EMPTY_REPLY_MAX_RETRY:
                                _empty_retries += 1
                                logger.warning(
                                    f"[ReAct] 第 {iteration + 1} 轮空回复 "
                                    f"(finish_reason={llm_result.get('finish_reason')})，"
                                    f"注入提示重试 {_empty_retries}/{_EMPTY_REPLY_MAX_RETRY}"
                                )
                                chat_messages.append({
                                    "role": "system",
                                    "content": (
                                        "你刚才的回复内容为空。请直接基于本轮已有的工具返回结果，"
                                        "组织并输出完整的最终答案，不要再调用任何工具。"
                                    ),
                                })
                                continue
                            final_content = (
                                "（模型本次返回了空回复，未能生成有效答案，"
                                "请重新发送问题或稍后重试。）"
                            )
                            logger.warning(
                                f"[ReAct] 第 {iteration + 1} 轮空回复且重试未恢复，降级为占位提示"
                            )

                        logger.info(
                            f"[ReAct] LLM 最终回复 (iteration={iteration+1}) | "
                            f"finish_reason={llm_result.get('finish_reason')} | "
                            f"tools_used={list(used_tools)} | content_len={len(final_content)} | "
                            f"content={final_content[:200]}"
                        )
                        if llm_result.get("finish_reason") == "length":
                            logger.warning(
                                f"[ReAct] 最终回复可能被 max_tokens 截断 (finish_reason=length, "
                                f"content_len={len(final_content)})；若正文明显不完整请调大输出预算"
                            )

                        # ★ answer gate：候选最终回复经语义验证（Assessor.verify），不通过则带反馈重试。
                        #   仅门控「用过工具后」的回复（_buf_mode）；验证异常/超时默认放行，不阻塞主流程。
                        if _buf_mode and final_content.strip() and _gate_retries < _ANSWER_GATE_MAX_RETRY:
                            _vpassed, _vfb = True, ""
                            try:
                                async with asyncio.timeout(_ANSWER_GATE_TIMEOUT):
                                    _vpassed, _vfb = await self._verify_final_answer(
                                        user_text=user_text,
                                        final_content=final_content,
                                        tool_names=list(used_tools),
                                    )
                            except Exception as _ve:
                                logger.debug(f"[AnswerGate] 验证超时/异常，默认放行: {_ve}")
                            if not _vpassed:
                                _gate_retries += 1
                                logger.warning(
                                    f"[AnswerGate] 未通过，第 {_gate_retries}/{_ANSWER_GATE_MAX_RETRY} 次带反馈重试 "
                                    f"| reason={str(_vfb)[:120]}"
                                )
                                chat_messages.append({
                                    "role": "system",
                                    "content": (
                                        "你刚才的最终回复未通过质检，问题：" + str(_vfb)[:400]
                                        + "\n请先调用相应工具核实数据 / 修正分析对象后重新回答；"
                                          "禁止保留'待确认 / 需调用工具'类占位描述、估算的量化数据，"
                                          "或与用户请求对象不一致的内容。"
                                    ),
                                })
                                continue

                        # ★ answer gate：验证通过后，把此前缓存的候选正文统一流式补发
                        if _final_buf:
                            if not _message_started:
                                yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                                _message_started = True
                            for _tok in _final_buf:
                                yield make_event(ReactEventType.MESSAGE, chunk=_tok, iteration=iteration + 1)
                            _final_buf = []

                        # ★ v4.1: Assessor + Reflector 合并为后台任务，不再阻塞 message_end
                        #   原为同步 await（一次独立 LLM 调用），慢模型下挤占 60s 超时窗口，
                        #   导致 think_end 后 30s+ 才出 message_start。现在评估/反思都后台跑。
                        #   注意：HelpSeeker 的 retry/human 路径随之失效（回复已发送），
                        #   评估结果仅作为 Reflector 反思输入沉淀教训。
                        asyncio.create_task(
                            self._assess_in_background(
                                user_text=user_text,
                                final_content=final_content,
                                used_tools=list(used_tools),
                                iteration=iteration + 1,
                                agent_id=agent_id,
                                user_id=user_id,
                            )
                        )

                        # ★ v4.1: 正文 token 已实时转发（可能已发过 message_start），未发则在此补发
                        if not _message_started:
                            yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                        yield make_event(
                            ReactEventType.MESSAGE_END,
                            full_response=final_content,
                            iterations=iteration + 1,
                            tools_used=list(used_tools),
                            assessment=None,  # ★ v4.1: 评估已后台化，不再同步返回
                            usage=_make_usage(llm_result.get("usage")),
                        )
                        break

                    # 3.4 处理工具调用
                    _final_buf = []  # ★ answer gate：工具轮不展示候选正文，丢弃缓存（内容已进历史）
                    logger.info(f"[ReAct] LLM 请求调用 {len(tool_calls)} 个工具")

                    assistant_message = {
                        "role": "assistant",
                        "content": llm_result.get("content"),
                        "tool_calls": []
                    }

                    for tc in tool_calls:
                        if isinstance(tc, dict):
                            tc_id = tc.get("id", f"call_{iteration}_{len(chat_messages)}")
                            tc_function = tc.get("function", {})
                            tc_name = tc_function.get("name", "")
                            tc_arguments = tc_function.get("arguments", "{}")
                        else:
                            tc_id = getattr(tc, 'id', f"call_{iteration}_{len(chat_messages)}")
                            tc_name = getattr(tc, 'name', '') or getattr(tc, 'function', {}).get('name', '')
                            tc_arguments = getattr(tc, 'arguments', '{}')

                        assistant_message["tool_calls"].append({
                            "id": tc_id, "type": "function",
                            "function": {"name": tc_name, "arguments": tc_arguments}
                        })

                    chat_messages.append(assistant_message)

                    for tc_info in assistant_message["tool_calls"]:
                        tc_id = tc_info["id"]
                        tc_name = tc_info["function"]["name"]
                        tc_arguments = tc_info["function"]["arguments"]

                        try:
                            arguments = json.loads(tc_arguments) if isinstance(tc_arguments, str) else tc_arguments
                        except json.JSONDecodeError:
                            arguments = {"_raw_input": tc_arguments}

                        # ★ ParamGuard：执行前参数校验 + 代码兜底修复（弱模型参数填充兜底）。
                        #   放在 TOOL_CALL 事件之前 → 前端与重复调用检测看到的都是修复后参数；
                        #   强模型参数全过时零干预（返回 info 为空）。
                        if _PARAM_GUARD_ENABLED and isinstance(arguments, dict):
                            try:
                                from src.skill.param_guard import validate_and_repair
                                arguments, _pg_info = validate_and_repair(
                                    tc_name,
                                    arguments,
                                    ctx={"user_message": user_text, "agent_id": agent_id},
                                    registry=self.tool_registry,
                                )
                                # ★ 修复后的参数同步回 assistant 历史：下一轮模型看到的是
                                #   实际执行的参数（否则历史里仍是空参/坏参，影响后续生成，
                                #   现场实测会诱导模型反复重调/跑偏）
                                if _pg_info and "_raw_input" not in arguments:
                                    tc_info["function"]["arguments"] = json.dumps(arguments, ensure_ascii=False)
                            except Exception as _pg_err:
                                logger.debug(f"[ParamGuard] 跳过: tool={tc_name} err={_pg_err}")

                        yield make_event(ReactEventType.TOOL_CALL, tool_name=tc_name, tool_args=arguments, tool_call_id=tc_id, iteration=iteration + 1)

                        # 重复工具调用检测
                        _tool_sig = f"{tc_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
                        if _tool_sig in _called_tool_signatures:
                            logger.warning(f"[ReAct] 重复调用跳过: {tc_name}({_tool_sig})")
                            # ★ OpenAI 协议要求：assistant 里每个 tool_call 都必须有对应的
                            #   tool 结果消息。原实现回的是 user 消息，导致"2 个 tool_call 只
                            #   回 1 条 tool 结果"→ 下一轮请求被 vLLM 直接 400（现场实测：
                            #   数据已查到却拿不到回答）。
                            chat_messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": json.dumps(
                                    {"status": "skipped", "message": "重复调用（与上一次参数相同），请直接基于已有工具结果作答，不要再次调用。"},
                                    ensure_ascii=False,
                                ),
                            })
                            continue

                        logger.info(f"[ReAct] 执行工具: {tc_name}({arguments})")
                        used_tools.append(tc_name)
                        _called_tool_signatures.append(_tool_sig)

                        # ★ S3: tool_start 事件 — 标记工具执行开始（含时间戳）
                        _tool_start_time = time.time()
                        yield make_event(ReactEventType.TOOL_START, tool_name=tc_name, tool_args=arguments, tool_call_id=tc_id, iteration=iteration + 1, start_time=_tool_start_time)

                        # 耗时长的工具，先发一个进度提示（asyncio 已在文件顶部导入）
                        if tc_name in ("weather", "web_fetch", "excel_read"):
                            yield make_event(ReactEventType.TOOL_PROGRESS, tool_name=tc_name, tool_call_id=tc_id, iteration=iteration + 1, progress="正在执行，请稍候...")
                            await asyncio.sleep(0)

                        tool_result = await self.tool_registry.execute_tool(tc_name, **arguments)
                        _tool_elapsed_ms = int((time.time() - _tool_start_time) * 1000)
                        correction_attempted = False

                        # ★ 日志：工具执行结果（传参已在上文记录）
                        _result_preview = str(tool_result.to_dict().get("content", ""))[:200]
                        logger.info(
                            f"[ReAct] 工具结果: {tc_name} | status={tool_result.status} | "
                            f"elapsed={_tool_elapsed_ms}ms | result={_result_preview}"
                        )

                        # L1: 补默认参数重试
                        if tool_result.status == "error":
                            defaults = self.tool_registry.get_tool_defaults(tc_name)
                            missing = {k: v for k, v in defaults.items() if k not in arguments}
                            if missing:
                                filled_args = {**arguments, **missing}
                                tool_result = await self.tool_registry.execute_tool(tc_name, **filled_args)
                                correction_attempted = True
                                if tool_result.status == "success":
                                    logger.info(f"[ReAct] L1 修正成功: {tc_name}")

                        # L2: 替代工具
                        if tool_result.status == "error":
                            alt_tool_name = self.tool_registry.find_alternative_tool(tc_name)
                            if alt_tool_name:
                                alt_result = await self.tool_registry.execute_tool(alt_tool_name, **arguments)
                                if alt_result.status == "success":
                                    tool_result = alt_result
                                    used_tools[-1] = alt_tool_name
                                    correction_attempted = True

                        # L3: 用户澄清
                        if tool_result.status == "error":
                            error_msg = tool_result.error or "未知错误"
                            # ★ 查询/读类工具免人工确认：失败直接把错误回填给模型重试，
                            #   不再弹确认白等 30s（现场前端未实现确认 UI 时尤为致命）。
                            if _is_confirm_exempt(tc_name):
                                logger.info(f"[ReAct] 查询类工具失败免确认，回填错误交模型重试: {tc_name}")
                                chat_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc_id,
                                    "content": json.dumps({"status": "error", "error": error_msg}, ensure_ascii=False),
                                })
                                continue
                            from src.agent.multi.confirmation import get_confirmation_manager
                            cm = get_confirmation_manager()
                            cm.add(session_id=agent_id, message=f"工具 '{tc_name}' 执行失败: {error_msg}", tool_name=tc_name, options=["继续", "跳过"], timeout_sec=30)
                            yield make_event(ReactEventType.CONFIRMATION, message=f"工具 '{tc_name}' 执行失败: {error_msg}", options=["继续", "跳过"], timeout_sec=30, iteration=iteration + 1, tool_name=tc_name, error=error_msg)
                            status = await cm.wait_for_response(agent_id, timeout_sec=30)
                            if status == ConfirmStatus.APPROVED:
                                chat_messages.append({"role": "tool", "tool_call_id": tc_id, "content": json.dumps({"status": "error", "error": error_msg, "user_approved_retry": True}, ensure_ascii=False)})
                                continue
                            else:
                                chat_messages.append({"role": "tool", "tool_call_id": tc_id, "content": json.dumps({"status": "error", "error": error_msg, "user_decision": status.value}, ensure_ascii=False)})
                                continue

                        yield make_event(ReactEventType.TOOL_RESULT, tool_name=used_tools[-1], result=tool_result.to_dict(), success=(tool_result.status == "success"), tool_call_id=tc_id, iteration=iteration + 1, elapsed_ms=_tool_elapsed_ms, corrected=correction_attempted)
                        # ★ 批次8：展平多层协议包装（模型只见服务端数据本体）→ 三层预算截断
                        #   （单条基础 / 轮内剩余配额 / 剩余上下文空间；对齐 LibreChat/Claude 的
                        #   窗口预算管理，避免 16K 等小窗口现场一轮多工具直接撞窗）
                        _flat = _flatten_tool_result(tool_result)
                        _result_content = json.dumps(_flat, ensure_ascii=False, default=str)
                        if _est_used_cache < 0 and _ctx_len:
                            try:
                                _est_used_cache = self.llm_adapter._estimate_input_tokens(chat_messages)
                            except Exception:
                                _est_used_cache = 0
                        _budgets = [_tool_base_budget]
                        if _tool_round_left > 0:
                            _budgets.append(max(1500, _tool_round_left))
                        if _ctx_len:
                            _budgets.append(max(1500, int(_ctx_len * _AUTO_COMPACT_THRESHOLD) - _est_used_cache))
                        _eff_budget = max(1500, min(_budgets))
                        if len(_result_content) > _eff_budget:
                            _result_content = _smart_truncate_json_text(_result_content, _eff_budget)
                        _tool_round_left -= len(_result_content)

                        chat_messages.append({"role": "tool", "tool_call_id": tc_id, "content": _result_content})

                        # ★ 批次11-C2：记录本行便签（工具名 + 参数定位条件 + 状态；纯程序化）
                        if _SCRATCHPAD_ENABLED:
                            _line = (
                                f"第{iteration + 1}轮 调用 {used_tools[-1]}"
                                f"({_scratch_compact_args(arguments)}) → {tool_result.status}"
                            )
                            if tool_result.status == "error" and getattr(tool_result, "error", None):
                                _line += f" | err: {str(tool_result.error)[:80]}"
                            _scratch_lines.append(_line)

                        # ★ 直答工具（如昆明 kunming_api）：数据已查到 → 直接把数据作为
                        #   message 输出并收尾，不再让弱模型组织第二轮回答（现场实测：弱模型
                        #   收尾轮易跑偏/400，导致"查到数据却答不出"）。仅对配置工具生效。
                        if tc_name in _DIRECT_ANSWER_TOOLS and tool_result.status == "success":
                            _direct_text = _direct_answer_text(_flat) or "（未查询到数据）"
                            logger.info(
                                f"[ReAct] 直答工具命中，跳过模型收尾轮: {tc_name} | chars={len(_direct_text)}"
                            )
                            if not _message_started:
                                yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                                _message_started = True
                            yield make_event(ReactEventType.MESSAGE, chunk=_direct_text, iteration=iteration + 1)
                            yield make_event(
                                ReactEventType.MESSAGE_END,
                                full_response=_direct_text,
                                iterations=iteration + 1,
                                tools_used=list(used_tools),
                                usage=_make_usage(llm_result.get("usage")),
                            )
                            _direct_answered = True
                            break

                    # ★ 直答已输出 → 跳出轮次循环，直接收尾（不再发起模型收尾轮）
                    if _direct_answered:
                        break

                # ★ P0-3: 达到最大迭代次数时强制生成 final（直答已输出则不重复）
                if not _direct_answered and iteration >= self.max_iterations - 1:
                    logger.warning(f"[ReAct] 达到最大循环次数 ({self.max_iterations})，强制生成总结")
                    try:
                        summary_result = await self.llm_adapter.chat_with_tools(
                            messages=chat_messages, tools=tools_schema, tool_choice="none",
                            temperature=temperature, max_tokens=max_tokens
                        )
                        summary_content = summary_result.get("content", "") or "（已达到最大工具调用次数，基于已有结果总结）"
                        if not _message_started:
                            yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
                        yield make_event(
                            ReactEventType.MESSAGE_END, full_response=summary_content, iterations=self.max_iterations, tools_used=list(used_tools),
                            usage=_make_usage(summary_result.get("usage")),
                        )
                    except Exception as e:
                        logger.error(f"[ReAct] 强制 final 生成失败: {e}")
                        yield make_event(ReactEventType.ERROR, message=f"已达到最大工具调用次数 ({self.max_iterations}) 且总结生成失败: {e}", iteration=self.max_iterations, recoverable=False)

        except asyncio.TimeoutError:
            # ★ 优化：超时后不再调 LLM（省 30-60s），直接用已收集内容拼贴返回
            logger.warning(f"[ReAct] 60s 超时，基于已有结果直接返回")
            summary_content = (llm_result.get("content") or "").strip()
            if not summary_content:
                summary_content = "（执行超时，未能生成完整回复）"
            if not _message_started:
                yield make_event(ReactEventType.MESSAGE_START, agent_id=agent_id)
            yield make_event(
                ReactEventType.MESSAGE_END, full_response=summary_content, iterations=self.max_iterations, tools_used=list(used_tools),
                usage=_make_usage(llm_result.get("usage")),
            )

        # ★ P0-2: 循环结束后沉淀对话记忆（best-effort，不影响主流程）
        try:
            asyncio.create_task(self._persist_memory(user_text, used_tools, agent_id, user_id))
        except Exception:
            pass  # 事件循环不可用时静默忽略

    async def _persist_memory(
        self, user_text: str, used_tools: List[str], agent_id: str, user_id: str = ""
    ) -> None:
        """异步记忆沉淀（fire-and-forget，失败静默）"""
        try:
            from src.memory.unified_manager import get_unified_manager
            from src.memory.types import MemoryType, MemoryCategory
            memory_mgr = get_unified_manager()
            text_short = user_text[:300] if len(user_text) > 300 else user_text
            tools_str = ", ".join(used_tools) if used_tools else "无工具调用"
            await memory_mgr.add_memory(
                content=f"[对话] 用户: {text_short} | 使用了工具: {tools_str}",
                memory_type=MemoryType.AGENT_PRIVATE,
                agent_id=agent_id,
                category=MemoryCategory.CONVERSATION,
                user_id=user_id or None,
            )
            logger.info(f"[ReAct] 已沉淀对话记忆 (agent={agent_id})")
        except Exception:
            pass  # 静默忽略

    async def _assess_in_background(
        self,
        user_text: str,
        final_content: str,
        used_tools: List[str],
        iteration: int,
        agent_id: str,
        user_id: str = "",
    ) -> None:
        """★ v4.1: 后台评估 + 反思（fire-and-forget，失败静默）

        将原本同步阻塞的 Assessor 评估迁移到后台，并把评估结果传给 Reflector 沉淀教训。
        由于评估时回复已发送给前端，HelpSeeker 的 retry/human 路径不再触发；
        此处仅做离线评价与自省，不阻塞 message_end，慢模型下不再挤占超时窗口。
        """
        try:
            assessment = await self._assess_response(
                content=final_content,
                ctx={
                    "tools_used": len(used_tools),
                    "iterations": iteration,
                    "message": user_text,
                },
            )
            logger.info(
                f"[Assessor/Background] 评估完成 | score={assessment.quality_score:.2f}, "
                f"need_help={assessment.need_help}, reason={assessment.reason[:50]}"
            )
            # 将评估结果传给 Reflector 作为反思输入（失败静默，不影响评估流程）
            try:
                await self._reflect_in_background(
                    user_text=user_text,
                    final_content=final_content,
                    used_tools=used_tools,
                    iteration=iteration,
                    assessment=assessment,
                    agent_id=agent_id,
                    user_id=user_id,
                )
            except Exception as e:
                logger.debug(f"[Assessor/Background] 反思失败（静默）: {e}")
        except Exception as e:
            logger.debug(f"[Assessor/Background] 后台评估失败（静默）: {e}")

    async def _reflect_in_background(
        self,
        user_text: str,
        final_content: str,
        used_tools: List[str],
        iteration: int,
        assessment: Optional[Any],
        agent_id: str,
        user_id: str = "",
    ) -> None:
        """★ 后台反思：不阻塞对话流，失败静默（fire-and-forget）

        反思是旁路任务，用户无感知；慢模型下不会挤占对话超时窗口。
        通过 asyncio.create_task() 调度为独立后台协程。
        """
        try:
            # ★ 失败回答不沉淀教训：Assessor 判失败时，回复本身可能就是错的，
            #   反思结论会把错误当成"经验"写进长期记忆，形成
            #   「错误回答 → 错误教训 → 下一轮跑偏」的恶性循环（现场实测案例）。
            if assessment is not None and (
                getattr(assessment, "need_help", False)
                or float(getattr(assessment, "quality_score", 1.0) or 0.0) < 0.6
            ):
                logger.info(
                    "[Reflector] 评估未通过，跳过教训沉淀（防脏记忆回流）"
                    f" | score={getattr(assessment, 'quality_score', None)}"
                    f" | need_help={getattr(assessment, 'need_help', None)}"
                )
                return

            from src.agent.multi.reflector import get_reflector
            reflector = get_reflector()
            reflector.set_llm_adapter(self.llm_adapter)

            reflection = await reflector.reflect(
                user_message=user_text,
                response=final_content,
                tools_used=used_tools,
                iterations=iteration,
                assessment=assessment,
                agent_id=agent_id,
            )

            if reflection.lessons or reflection.improvements:
                from src.memory.long_term import MemoryManager
                mm = MemoryManager(agent_id=agent_id, user_id=user_id or None)

                # ★ 写入前去重：同一句教训会随每次对话反复 append，
                #   导致 lessons 列表无限膨胀；而消费侧（unified_manager）只读最近几条，
                #   重复项纯属噪音。这里与已有内容比对后跳过重复项。
                try:
                    existing = (mm.long_term_memory.get("long_term") or {}).get("lessons") or []
                    known = {
                        " ".join(
                            str(e.get("content", "") if isinstance(e, dict) else e).split()
                        )
                        for e in existing
                    }
                except Exception:
                    known = set()

                written = 0

                def _write_unique(text: str, tag: str) -> None:
                    nonlocal written
                    body = " ".join(str(text or "").split()).strip()
                    if len(body) < 4 or body in known:
                        return
                    mm.add_to_long_term("lessons", body, tags=["reflector", agent_id, tag])
                    known.add(body)
                    written += 1

                for lesson in reflection.lessons:
                    _write_unique(lesson, "lesson")
                for imp in reflection.improvements:
                    _write_unique(f"[改进] {imp}", "improvement")

                logger.info(
                    f"[Reflector] {written} 条经验已写入长期记忆"
                    f"（候选 {len(reflection.lessons) + len(reflection.improvements)} 条，去重后）"
                )
        except Exception as e:
            logger.debug(f"[Reflector] 后台反思失败（静默）: {e}")


async def run_react_loop(
    llm_adapter: LLMAdapter,
    messages: List[Dict],
    agent_id: str = "dfecrab",
    enabled_skills: Optional[List[str]] = None,
    system_prompt: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_iterations: int = 5,
    tool_choice: str = "auto",
    user_id: str = "",
) -> AsyncGenerator[Dict[str, Any], None]:
    """便捷函数：运行 ReAct 循环
    
    Args:
        llm_adapter: LLM 适配器
        messages: 消息列表
        agent_id: Agent ID
        enabled_skills: 启用的技能列表
        system_prompt: 系统提示
        temperature: 温度
        max_tokens: 最大 token 数
        max_iterations: 最大循环次数
        tool_choice: 工具选择策略 (auto/required/none)
        
    Yields:
        事件字典
    """
    loop = ReActLoop(
        llm_adapter=llm_adapter,
        max_iterations=max_iterations
    )
    
    async for event in loop.run(
        messages=messages,
        agent_id=agent_id,
        enabled_skills=enabled_skills,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        tool_choice=tool_choice,
        user_id=user_id,
    ):
        yield event