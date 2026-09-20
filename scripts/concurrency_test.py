#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DFEcrab 对话接口并发压力测试脚本

目的：验证「同一时间段很多人同时对话」时，网关是否支持并发（不互相阻塞、不串台）。

原理：
- 网关 HTTP 服务基于 asyncio 事件循环（asyncio.start_server），
  对话 handler 是 async 协程，核心走 await gRPC/LLM 的异步生成器。
  理论上多个连接会各自成为一个 task，在 await 阻塞点被事件循环切换调度，
  从而实现并发。本脚本用 asyncio.gather 同时发起 N 个请求来模拟「多人同时对话」，
  并通过「并发比」(串行理论总耗时 / 实际墙钟耗时) 量化并行程度。

依赖：httpx (已在 requirements.txt)
    pip install "httpx>=0.27.0"

用法：
    # 先启动网关（确保 6789 端口可用）
    python scripts/concurrency_test.py --users 20
    python scripts/concurrency_test.py --users 50 --mode stream --message "今天保供电跳闸情况" --agent-id kunming
    python scripts/concurrency_test.py --users 30 --mode both --host 192.168.1.10 --port 6789
"""

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

import httpx


@dataclass
class ReqResult:
    user_index: int
    session_id: str
    user_id: str
    agent_id: str = ""
    success: bool = False
    status: int = 0
    error: str = ""
    latency_ms: float = 0.0
    response_len: int = 0
    full_response: str = ""
    start_ts: float = 0.0
    end_ts: float = 0.0


# 预置任务池：每个并发用户按 index 轮询取一个（不同问题 + 绑定不同智能体）。
# 覆盖 dfecrab / code_writer / knowledge_agent 三条业务线，验证并发下路由与会话隔离。
# 注意：kunming 在本环境不可用，此处不纳入。
TASK_POOL = [
    {"agent_id": "dfecrab",       "message": "请你制定F19地王一线的转电预案"},
    {"agent_id": "code_writer",   "message": "编写个二分查找的代码执行下看看效果"},
    {"agent_id": "knowledge_agent", "message": "知识库里关于配网故障处理的标准流程有哪些？"},
    {"agent_id": "code_writer",   "message": "用 python 写个快速排序并运行验证正确性"},
    {"agent_id": "dfecrab",       "message": "今天有哪些保供电任务？做个简要研判"},
    {"agent_id": "knowledge_agent", "message": "检索一下设备巡视的相关规定与周期要求"},
    {"agent_id": "dfecrab",       "message": "帮我查一下昆明近期天气，适不适合户外巡检"},
]


def _resolve_tasks(users: int, override_msg: str, override_agent: str):
    """返回长度为 users 的任务列表 [(message, agent_id), ...]。

    若传了 --message 则全员同问题（兼容旧用法，agent 默认 default）；
    否则从 TASK_POOL 轮询，模拟不同人问不同业务。
    """
    if override_msg:
        return [(override_msg, override_agent or "default") for _ in range(users)]
    return [(t["message"], t["agent_id"]) for t in (TASK_POOL[i % len(TASK_POOL)]
                                                     for i in range(users))]


async def _one_chat(client: httpx.AsyncClient, base_url: str, user_index: int,
                    message: str, agent_id: str, timeout: float,
                    user_id: str = "") -> ReqResult:
    """非流式 /api/v2/chat 单次请求。"""
    session_id = f"conv_test_{uuid.uuid4().hex[:12]}"
    if not user_id:
        user_id = f"concurrent_user_{user_index}"
    payload = {
        "message": message,
        "session_id": session_id,
        "user_id": user_id,
        "agent_id": agent_id,
    }
    headers = {"Content-Type": "application/json", "X-User-Id": user_id}
    res = ReqResult(user_index=user_index, session_id=session_id, user_id=user_id,
                    agent_id=agent_id)
    start = time.perf_counter()
    res.start_ts = start
    try:
        r = await client.post(f"{base_url}/api/v2/chat", json=payload,
                              headers=headers, timeout=timeout)
        end = time.perf_counter()
        res.end_ts = end
        res.latency_ms = (end - start) * 1000
        res.status = r.status_code
        try:
            body = r.json()
        except Exception:
            body = {}
        if r.status_code == 200 and body.get("success"):
            data = body.get("data", {})
            fr = data.get("response") or ""
            res.full_response = fr
            res.response_len = len(fr)
            res.success = bool(fr)
        else:
            res.success = False
            res.error = json.dumps(body, ensure_ascii=False)[:200]
    except Exception as e:
        end = time.perf_counter()
        res.end_ts = end
        res.latency_ms = (end - start) * 1000
        res.success = False
        res.error = repr(e)
    return res


async def _one_stream(client: httpx.AsyncClient, base_url: str, user_index: int,
                      message: str, agent_id: str, timeout: float,
                      user_id: str = "") -> ReqResult:
    """SSE 流式 /api/v2/chat/stream 单次请求，读取直到 message_end。"""
    session_id = f"conv_test_{uuid.uuid4().hex[:12]}"
    if not user_id:
        user_id = f"concurrent_user_{user_index}"
    payload = {
        "message": message,
        "session_id": session_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "correlation_id": f"conv_{user_index}_{uuid.uuid4().hex[:8]}",
    }
    headers = {"Content-Type": "application/json", "X-User-Id": user_id}
    res = ReqResult(user_index=user_index, session_id=session_id, user_id=user_id,
                    agent_id=agent_id)
    start = time.perf_counter()
    res.start_ts = start
    full = []
    try:
        async with client.stream("POST", f"{base_url}/api/v2/chat/stream",
                                 json=payload, headers=headers, timeout=timeout) as r:
            res.status = r.status_code
            if r.status_code != 200:
                res.success = False
                res.error = f"HTTP {r.status_code}"
                res.end_ts = time.perf_counter()
                res.latency_ms = (res.end_ts - start) * 1000
                return res
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if not raw:
                    continue
                try:
                    evt = json.loads(raw)
                except Exception:
                    continue
                ed = evt.get("data", {}) or {}
                # SSE/WS 事件带信封：业务字段在 ed["data"]，与 event_type 同层
                edata = ed.get("data", {}) if isinstance(ed.get("data"), dict) else {}
                if ed.get("event_type") == "message_end":
                    fr = (edata.get("full_response") or edata.get("content")
                          or ed.get("full_response") or ed.get("content") or "")
                    full.append(str(fr))
                    break
                elif ed.get("event_type") == "error":
                    res.error = str(edata.get("message") or ed.get("message") or "")
        end = time.perf_counter()
        res.end_ts = end
        res.latency_ms = (end - start) * 1000
        res.full_response = "".join(full)
        res.response_len = len(res.full_response)
        res.success = bool(res.full_response) and not res.error
    except Exception as e:
        end = time.perf_counter()
        res.end_ts = end
        res.latency_ms = (end - start) * 1000
        res.success = False
        res.error = repr(e)
    return res


def _summarize(results: list, mode: str, wall_time: float):
    total = len(results)
    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]
    latencies = [r.latency_ms for r in results]
    latencies.sort()
    avg = sum(latencies) / total if total else 0.0
    p50 = latencies[total // 2] if total else 0.0
    p95 = latencies[int(total * 0.95)] if total else 0.0
    max_l = latencies[-1] if total else 0.0
    min_l = latencies[0] if total else 0.0
    seq_total = sum(latencies)  # 若完全串行，理论总耗时
    concurrency_ratio = (seq_total / (wall_time * 1000)) if wall_time > 0 else 0.0

    print("\n" + "=" * 64)
    print(f"  并发测试结果 [{mode}]  并发用户数 = {total}")
    print("=" * 64)
    print(f"  墙钟总耗时        : {wall_time*1000:.1f} ms")
    print(f"  成功 / 失败        : {len(ok)} / {len(fail)}  (成功率 {len(ok)/total*100:.1f}%)")
    print(f"  吞吐(请求/秒)      : {total/wall_time:.2f}")
    print(f"  单请求延迟 平均    : {avg:.1f} ms")
    print(f"  单请求延迟 P50/P95 : {p50:.1f} / {p95:.1f} ms")
    print(f"  单请求延迟 最小/最大: {min_l:.1f} / {max_l:.1f} ms")
    print(f"  串行理论总耗时      : {seq_total:.1f} ms")
    print(f"  ★ 并发比            : {concurrency_ratio:.2f}x  "
          f"(接近并发用户数={total} 说明真正并行)")
    # 按智能体分组，验证不同 agent 并发下各自成功率（路由/会话隔离）
    by_agent: dict = {}
    for r in results:
        by_agent.setdefault(r.agent_id, []).append(r)
    print("-" * 64)
    print(f"  按智能体分组 (agent_id -> 成功/总数, 平均延迟ms):")
    for ag, rs in by_agent.items():
        a_ok = sum(1 for x in rs if x.success)
        a_avg = sum(x.latency_ms for x in rs) / len(rs) if rs else 0.0
        print(f"    {ag:<16} {a_ok}/{len(rs)}   avg={a_avg:.1f}")
    if fail:
        print(f"  失败明细(前 {min(5, len(fail))} 条):")
        for r in fail[:5]:
            print(f"    user#{r.user_index} agent={r.agent_id} status={r.status} err={r.error[:120]}")
    verdict = "✅ 网关支持并发：请求并行处理，无互相阻塞/串台" \
        if concurrency_ratio >= total * 0.6 and len(fail) == 0 \
        else ("⚠️ 部分并发/存在失败：可能存在串行瓶颈或资源竞争" if len(fail) else
              "⚠️ 并发度偏低：请求疑似被串行化（存在全局锁/单worker限制）")
    print(f"  结论: {verdict}")
    print("=" * 64 + "\n")
    return {
        "mode": mode,
        "wall_time_ms": wall_time * 1000,
        "total": total,
        "success": len(ok),
        "fail": len(fail),
        "success_rate": len(ok) / total * 100 if total else 0.0,
        "throughput": total / wall_time if wall_time > 0 else 0.0,
        "latency_avg_ms": avg,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_min_ms": min_l,
        "latency_max_ms": max_l,
        "seq_total_ms": seq_total,
        "concurrency_ratio": concurrency_ratio,
        "by_agent": {ag: {
            "success": sum(1 for x in rs if x.success),
            "total": len(rs),
            "avg_latency_ms": sum(x.latency_ms for x in rs) / len(rs) if rs else 0.0,
        } for ag, rs in by_agent.items()},
        "verdict": verdict,
    }


async def run_concurrency(base_url: str, users: int, message: str, agent_id: str,
                          mode: str, timeout: float, user_ids: list, output: str = ""):
    """output: 结果文件路径。为空则自动生成带时间戳的文件(同目录 .txt + .json)。"""
    import io
    from contextlib import redirect_stdout
    from datetime import datetime

    # 解析每个并发用户的任务（不同问题 + 绑定不同 agent，或全员同问题）
    tasks_cfg = _resolve_tasks(users, message, agent_id)
    # 每个并发用户分配 X-User-Id：在 user_ids 列表中轮询（模拟不同的人）
    # 必须是 config/permissions.json 中已注册且具备 write 权限的用户（如 alice/admin），
    # 否则网关按 default_role=guest 拦截，返回 403「无权限」。
    assigned_users = [user_ids[i % len(user_ids)] for i in range(users)]
    limits = httpx.Limits(max_connections=users + 10, max_keepalive_connections=users + 10)
    async with httpx.AsyncClient(limits=limits) as client:
        # 先发 1 个请求做连通性/基线探测（用第一个任务）
        pm, pa = tasks_cfg[0]
        pu = assigned_users[0]
        probe = await _one_chat(client, base_url, 0, pm, pa, timeout, user_id=pu) \
            if mode in ("chat", "both") else \
            await _one_stream(client, base_url, 0, pm, pa, timeout, user_id=pu)
        if not probe.success:
            print(f"❌ 基线探测失败(单请求都不通)，请确认网关已启动且地址正确：")
            print(f"   status={probe.status} err={probe.error}")
            print(f"   提示: 若 403 无权限，请确认 --user-ids 里的用户在"
                  f" config/permissions.json 有 write 权限(如 alice/admin)")
            return
        print(f"✅ 基线探测通过：单请求延迟 {probe.latency_ms:.1f} ms，"
              f"回复长度 {probe.response_len} 字符")
        # 任务分布预览
        from collections import Counter
        dist = Counter(a for _, a in tasks_cfg)
        dist_str = ", ".join(f"{a}×{n}" for a, n in dist.items())
        u_dist = Counter(assigned_users)
        u_str = ", ".join(f"{u}×{n}" for u, n in u_dist.items())
        print(f"▶ 本轮并发任务分布: {dist_str}")
        print(f"▶ 本轮用户分布(X-User-Id): {u_str}")

        report_parts = []          # 各 mode 的文本报告（用于落盘 txt）
        all_stats = []             # 各 mode 的结构化统计
        all_records = []           # 每个请求的明细
        for m in (["chat", "stream"] if mode == "both" else [mode]):
            coro = _one_chat if m == "chat" else _one_stream
            tasks = [asyncio.create_task(coro(client, base_url, i, msg, ag, timeout,
                                               user_id=uid))
                     for i, ((msg, ag), uid) in enumerate(zip(tasks_cfg, assigned_users), start=1)]
            t0 = time.perf_counter()
            results = await asyncio.gather(*tasks)
            t1 = time.perf_counter()
            buf = io.StringIO()
            with redirect_stdout(buf):
                stats = _summarize(list(results), m, t1 - t0)
            text = buf.getvalue()
            print(text, end="")
            report_parts.append(text)
            all_stats.append(stats)
            for r in results:
                all_records.append({
                    "user_index": r.user_index,
                    "user_id": r.user_id,
                    "agent_id": r.agent_id,
                    "session_id": r.session_id,
                    "success": r.success,
                    "status": r.status,
                    "latency_ms": round(r.latency_ms, 1),
                    "response_len": r.response_len,
                    "error": r.error[:200],
                })

        # ===== 结果落盘 =====
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not output:
            output = f"concurrency_result_{ts}"
        base_path = output
        # 去掉可能误带的扩展名，统一生成 .txt 和 .json
        for ext in (".txt", ".json"):
            if base_path.endswith(ext):
                base_path = base_path[: -len(ext)]
        txt_path = base_path + ".txt"
        json_path = base_path + ".json"
        header = (
            f"DFEcrab 对话并发测试报告\n"
            f"生成时间 : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"目标网关 : {base_url}\n"
            f"并发用户 : {users}   模式: {mode}\n"
            f"任务来源 : {'自定义同问题: '+message if message else '预置任务池(轮询不同问题+不同agent)'}\n"
            f"用户池   : {user_ids}\n"
            f"单请求超时: {timeout}s\n"
            f"{'=' * 64}\n"
        )
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write("\n".join(report_parts))
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "meta": {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "base_url": base_url,
                    "users": users,
                    "mode": mode,
                    "message": message or None,
                    "agent_id": agent_id if message else None,
                    "user_ids": user_ids,
                    "timeout": timeout,
                },
                "summary": all_stats,
                "records": all_records,
            }, f, ensure_ascii=False, indent=2)
        print(f"💾 结果已保存:\n   {txt_path}\n   {json_path}")


def main():
    p = argparse.ArgumentParser(description="DFEcrab 对话并发测试")
    p.add_argument("--host", default="127.0.0.1", help="网关地址 (默认 127.0.0.1)")
    p.add_argument("--port", type=int, default=6789, help="网关 HTTP 端口 (默认 6789)")
    p.add_argument("--users", type=int, default=20, help="并发用户数 (默认 20)")
    p.add_argument("--message", default="",
                   help="自定义全员同一问题；不传则按预置任务池轮询不同问题+不同agent")
    p.add_argument("--agent-id", default="dfecrab",
                   help="配合 --message 使用：全员统一的智能体 (默认 dfecrab)")
    p.add_argument("--user-ids", default="admin",
                   help="X-User-Id 列表(逗号分隔)，在已注册且有 write 权限的用户间轮询，"
                        "模拟不同的人；默认 admin。如 'admin,alice'")
    p.add_argument("--mode", choices=["chat", "stream", "both"], default="both",
                   help="测试模式: chat=非流式, stream=SSE流式, both=两者 (默认 both)")
    p.add_argument("--timeout", type=float, default=300.0,
                   help="单请求超时秒 (默认 300，单次对话实测可达数十秒，建议>=300)")
    p.add_argument("--output", default="",
                   help="结果保存路径(不含扩展名)；为空则自动生成 "
                        "concurrency_result_<时间戳>.txt/.json 到当前目录")
    args = p.parse_args()

    user_ids = [u.strip() for u in args.user_ids.split(",") if u.strip()] or ["alice"]
    base_url = f"http://{args.host}:{args.port}"
    if args.message:
        print(f"▶ 目标网关: {base_url}  并发用户: {args.users}  模式: {args.mode}")
        print(f"▶ 全员同问题: {args.message}  agent_id: {args.agent_id}")
    else:
        print(f"▶ 目标网关: {base_url}  并发用户: {args.users}  模式: {args.mode}")
        print(f"▶ 任务来源: 预置任务池(轮询不同问题+不同agent)")
    print(f"▶ 用户标识(X-User-Id)池: {user_ids}")
    asyncio.run(run_concurrency(base_url, args.users, args.message,
                                args.agent_id, args.mode, args.timeout, user_ids,
                                args.output))


if __name__ == "__main__":
    main()
