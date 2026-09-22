"""对话意图 / 信号解析工具（纯函数，无状态、无 IO）

从 `grpc_server.py` 抽出，消除类内重复实现：

- 告警 JSON 信号识别：`looks_like_alert_json`（快速预检，不解析）与
  `is_alert_signal_json`（严格判定，解析 JSON 且命中 ≥2 个特征字段）；
  两者语义**不同**，不是重复函数，分别用于"路由预检"和"最终判定"。
- 模型输出 JSON 提取：`extract_json_object`（取最后一段 {..}，多策略容错）
  与 `extract_json_fragment`（宽松扫描任意 {..} 片段）；
  二者共用 `normalize_target_agent` 做字段别名归一，避免重复代码。
- 系统提示词截断：`truncate_system_prompt`。

被对话链路（_run_chat_pipeline / _react_chat_generator / 告警直连 /
Manager 决策解析）共用。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

#: 电力告警 JSON 的特征字段（4 个中命中 ≥2 即判定为告警信号）
ALERT_JSON_FIELDS = ("station_inside_outer", "throbNum", "alert_content", "signal_package")

#: 目标智能体字段的常见别名（模型输出不稳定，统一归一化到 target_agent）
_TARGET_AGENT_ALIASES = ("target", "agent", "agent_id")


# ──────────────────────────────────────────────────────────────
# 告警 JSON 识别
# ──────────────────────────────────────────────────────────────

def looks_like_alert_json(message: Any) -> bool:
    """快速预检（不解析 JSON，用于路由判断）。

    规则：字符串以 `{` 开头，且包含任一告警特征字段。
    """
    if not message or not isinstance(message, str):
        return False
    msg = message.strip()
    if not msg.startswith("{"):
        return False
    return any(f in msg for f in ALERT_JSON_FIELDS)


def is_alert_signal_json(message: Any) -> bool:
    """严格判定：可解析为 JSON 对象且命中 ≥2 个告警特征字段。

    兼容数组形式的多条告警（如 `{"alerts": [{...}, {...}]}`）。
    """
    if not message or not isinstance(message, str):
        return False
    msg = message.strip()
    if not msg.startswith("{"):
        return False
    try:
        obj = json.loads(msg)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False

    hits = sum(1 for f in ALERT_JSON_FIELDS if f in obj)
    if hits >= 2:
        return True

    # 兼容：数组形式的多条告警
    for _f, v in obj.items():
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict) and sum(1 for ff in ALERT_JSON_FIELDS if ff in first) >= 2:
                return True
    return False


# ──────────────────────────────────────────────────────────────
# JSON 提取（共用字段别名归一）
# ──────────────────────────────────────────────────────────────

def normalize_target_agent(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """把 target/agent/agent_id 别名统一成 `target_agent`（原地补写后返回）。"""
    if "target_agent" not in parsed:
        for alias in _TARGET_AGENT_ALIASES:
            if alias in parsed:
                parsed["target_agent"] = parsed[alias]
                break
    return parsed


def _parse_json_dict(fragment: str) -> Optional[Dict]:
    """把一段候选文本按多种容错策略解析成 dict（失败返回 None）。

    策略依次尝试：原文 / 单引号转双引号 / 去尾逗号 / 中文标点转半角 / 补 key 引号。
    """
    attempts = [
        fragment,
        fragment.replace("'", '"'),
        re.sub(r",(\s*[}\]])", r"\1", fragment),
        fragment.replace("，", ",").replace("：", ":").replace("“", '"').replace("”", '"'),
        re.sub(r"(\w+)\s*:", r'"\1":', fragment),
    ]
    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return normalize_target_agent(parsed)
    return None


def extract_json_object(text: str) -> Optional[Dict]:
    """从文本中提取 JSON 对象并解析（多策略容错）。

    取「最靠后的 `}`」为右边界，**由后向前**尝试每个 `{` 作为左边界，
    返回首个能解析成 dict 的候选。

    这样可正确解析末尾为嵌套对象的输出（如 `{"a":{"b":1}}`、含 `data:{...}` 的决策），
    而旧实现只试「最后一个 `{`」，对上述输入会误判为"无 JSON"直接丢弃一次决策解析。
    """
    if not text:
        return None
    last_brace_end = text.rfind("}")
    if last_brace_end == -1:
        return None
    for m in reversed(list(re.finditer(r"\{", text))):
        if m.start() > last_brace_end:
            continue
        parsed = _parse_json_dict(text[m.start():last_brace_end + 1])
        if parsed is not None:
            return parsed
    return None


def extract_json_fragment(text: str) -> Optional[Dict]:
    """宽松模式：扫描文本中任意 `{..}` 片段，取能解析且像决策结果的字典。"""
    if not text:
        return None
    brace_starts = [m.start() for m in re.finditer("{", text)]
    brace_ends = [m.start() for m in re.finditer("}", text)]
    for s in reversed(brace_starts):
        for e in brace_ends:
            if e > s:
                fragment = text[s:e + 1]
                try:
                    parsed = json.loads(fragment)
                except Exception:
                    continue
                if isinstance(parsed, dict) and (
                    "type" in parsed or "target_agent" in parsed or "agent" in parsed
                ):
                    return normalize_target_agent(parsed)
    return None


# ──────────────────────────────────────────────────────────────
# 提示词工具
# ──────────────────────────────────────────────────────────────

def truncate_system_prompt(prompt: str, max_chars: int = 2000) -> str:
    """截断系统提示词中的 Agent 列表（保留头 70% + 尾 30%，中间省略）。

    与 Manager 的 `_truncate_agent_list` 行为一致。
    """
    if not prompt or len(prompt) <= max_chars:
        return prompt
    head_len = int(max_chars * 0.7)
    tail_len = max_chars - head_len
    omitted = len(prompt) - max_chars
    return prompt[:head_len] + f"\n...(Agent列表中间省略，共省略{omitted}字符)...\n" + prompt[-tail_len:]


# ──────────────────────────────────────────────────────────────
# 实例侧封装（Mixin）：供 GatewayV2GRPC 继承，内部直调上面的纯函数
# ──────────────────────────────────────────────────────────────

class IntentMixin:
    """意图解析入口（方法实现逐字自 grpc_server 迁出；纯函数逻辑见本模块上半部分）"""

    def _parse_intent_from_json(self, text: str) -> Optional[Dict]:
        """从 LLM 输出的文本中解析意图 JSON

        兼容多种格式：
        - 标准完整 JSON
        - 被 max_tokens 截断的 JSON（缺前或后）
        - JSON 在思考文本中被包裹
        - 无 JSON 时尝试从 thinking 提取 agent
        """
        if not text:
            return None
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', text, flags=re.DOTALL)
        # ★ 尝试多种策略提取 JSON
        strategies = [
            # 策略1：找最后一个完整的 {...} 对象
            self._try_extract_json(text),
            # 策略2：如果被截断缺了 {，补上 { 再试
            self._try_extract_json('{' + text) if not text.strip().startswith('{') else None,
            # 策略3：只保留从 { 到 } 的部分（兼容多余文字）
            self._try_extract_json_loose(text),
        ]
        for result in strategies:
            if result is not None:
                return result
        return None

    def _try_extract_json(self, text: str) -> Optional[Dict]:
        """提取最后一段 JSON 对象（实现见 chat/intent.py:extract_json_object）"""
        return extract_json_object(text)

    def _try_extract_json_loose(self, text: str) -> Optional[Dict]:
        """宽松扫描任意 JSON 片段（实现见 chat/intent.py:extract_json_fragment）"""
        return extract_json_fragment(text)

    def _truncate_system_prompt(self, prompt: str, max_chars: int = 2000) -> str:
        """截断系统提示词中的 Agent 列表（实现见 chat/intent.py:truncate_system_prompt）"""
        return truncate_system_prompt(prompt, max_chars)

    def _is_alert_signal_json(self, message: str) -> bool:
        """电力告警 JSON 严格判定（实现见 chat/intent.py:is_alert_signal_json）"""
        return is_alert_signal_json(message)

    def _match_gateway_rule_based_intent(self, message: str) -> Optional[Dict]:
        """基于 Agent 配置关键词做动态短路路由。

        这里只处理高置信度 simple/query 场景。关键词来自各 Agent 的
        `config.json`，因此是配置驱动而不是写死在代码里。
        """
        clean_message = (message or "").strip()
        if not clean_message:
            return None

        candidates = []
        for agent_id, info in self._scan_agent_descriptions().items():
            for keyword in info.get("keywords", []) or []:
                kw = str(keyword).strip()
                if not kw or len(kw) < 2:
                    continue
                pos = clean_message.find(kw)
                if pos >= 0:
                    candidates.append((len(kw), -pos, agent_id, kw))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        _, _, agent_id, keyword = candidates[0]
        return {
            "type": "simple",
            "category": "query",
            "target_agent": agent_id,
            "reason": f"命中Agent关键词规则: {keyword}"
        }
