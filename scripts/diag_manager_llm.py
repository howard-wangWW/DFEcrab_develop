# -*- coding: utf-8 -*-
"""复现 Manager 编排的 LLM 调用，打印模型原始输出，定位 JSON 解析失败原因"""
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))


def build_manager_prompt() -> str:
    cfg_path = PROJECT_ROOT / "agents" / "manager_agent" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    prompt = cfg.get("system_prompt", "")
    agent_list = (
        "- dfecrab（东方电子小螃蟹）: 通用问答\n"
        "- kunming（昆明配网数据专家）: 配网数据查询与知识问答\n"
        "- knowledge_agent（知识库检索专家）: 知识库问答\n"
        "- code_writer（代码撰写与执行师）: 写代码/运行程序\n"
        "- alert_judge（电力告警研判专家）: 仅处理JSON告警"
    )
    prompt = prompt.replace("{{AGENT_LIST}}", agent_list)
    prompt = prompt.replace("{{USER_PROFILE}}", "（诊断：无用户画像）")
    return prompt


async def main():
    message = sys.argv[1] if len(sys.argv) > 1 else "写一个python脚本二分查找并运行"

    from src.services.model_manager import model_manager
    llm_config = model_manager.get_provider_config("qwen3_32b_q4")
    if not llm_config:
        print("❌ qwen3_32b_q4 配置不存在")
        return

    manager_prompt = build_manager_prompt()
    merged_prompt = f"用户: {message}\n/no_think"

    print("=" * 70)
    print(f"模型: {llm_config.get('model_name')} @ {llm_config.get('api_base')}")
    print(f"用户消息: {message}")
    print("=" * 70)
    print("【SYSTEM PROMPT】前 600 字:")
    print(manager_prompt[:600])
    print("=" * 70)
    print("【USER PROMPT】:")
    print(merged_prompt)
    print("=" * 70)

    from src.agent.llm.adapter import LLMAdapter
    llm = LLMAdapter(llm_config)
    full_reasoning, full_response = "", ""
    print("调用 LLM（response_format=json_object, max_tokens=1024）...")
    try:
        async for ev in llm.call_stream(
            prompt=merged_prompt,
            system_prompt=manager_prompt,
            max_tokens=1024,
            response_format={"type": "json_object"},
        ):
            if ev["type"] == "reasoning":
                full_reasoning += ev["content"]
            elif ev["type"] == "token":
                full_response += ev["content"]
            elif ev["type"] == "error":
                print(f"❌ LLM 错误: {ev.get('content')}")
                return
    except Exception as e:
        print(f"❌ 调用异常: {e}")
        return

    print("=" * 70)
    print(f"【REASONING(思考)】len={len(full_reasoning)}:")
    print(repr(full_reasoning[:600]))
    print("-" * 70)
    print(f"【RESPONSE(正文)】len={len(full_response)}:")
    print(repr(full_response[:600]))
    print("-" * 70)
    try:
        parsed = json.loads(full_response)
        print(f"✅ 可解析为 JSON: {json.dumps(parsed, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"❌ 不可解析为 JSON: {e}")


asyncio.run(main())

