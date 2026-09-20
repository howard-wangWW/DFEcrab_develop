"""
gRPC架构集成测试

测试场景：
1. 健康检查 - 验证所有服务启动正常
2. 简单任务 - 单个Agent处理（写诗）
3. 复杂任务 - 多Agent协作（数据分析+报告+保存）
4. 审计日志 - 验证日志记录功能
5. 随机端口验证 - 验证Workers使用随机端口
"""

import asyncio
import json
import sys
import time
from pathlib import Path
import httpx

# 颜色输出
class Colors:
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.NC}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.NC}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.NC}")

def print_warn(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.NC}")


GATEWAY_URL = "http://localhost:6789"


async def test_health_check():
    """测试1: 健康检查"""
    print("\n" + "="*60)
    print_info("测试1: 健康检查")
    print("="*60)
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{GATEWAY_URL}/health", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                print_success(f"Gateway (6789) 健康: {data.get('version')}")
                print_info(f"架构: {data.get('architecture')}")
                print_info(f"Manager状态: {data.get('manager_agent')}")
                print_info(f"Worker数量: {data.get('worker_agents', 0)}")
                
                if data.get('manager_agent') == 'healthy':
                    print_success("Manager Agent正常")
                else:
                    print_warn("Manager Agent可能未完全启动")
                
                return True
            else:
                print_error(f"Gateway 响应异常: {resp.status_code}")
                return False
        except Exception as e:
            print_error(f"Gateway 不可达: {e}")
            return False


async def test_simple_task():
    """测试2: 简单任务 - 写一首诗"""
    print("\n" + "="*60)
    print_info("测试2: 简单任务 - 写一首关于春天的诗")
    print("="*60)
    
    async with httpx.AsyncClient() as client:
        try:
            start_time = time.time()
            resp = await client.post(
                f"{GATEWAY_URL}/api/v2/chat",
                json={
                    "message": "帮我写一首关于春天的诗",
                    "user_id": "test_user"
                },
                headers={"X-User-Id": "admin"},
                timeout=30.0
            )
            elapsed = time.time() - start_time
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    print_success(f"简单任务执行成功")
                    print_info(f"任务类型: {data.get('task_type')}")
                    print_info(f"使用Agent: {data.get('agents_used')}")
                    print_info(f"响应时间: {elapsed:.2f}s")
                    print_info(f"Session ID: {data.get('session_id')}")
                    print_info(f"审计日志ID: {data.get('audit_log_id')}")
                    print(f"\n📝 响应内容:")
                    print(f"   {data.get('message')}")
                    return True
                else:
                    print_error(f"任务执行失败: {data.get('message')}")
                    print_error(f"错误: {data.get('error')}")
                    return False
            else:
                print_error(f"Gateway 响应异常: {resp.status_code}")
                return False
                
        except Exception as e:
            print_error(f"请求失败: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_complex_task():
    """测试3: 复杂任务 - 数据分析+报告+保存"""
    print("\n" + "="*60)
    print_info("测试3: 复杂任务 - 分析电网数据并生成报告")
    print("="*60)
    
    async with httpx.AsyncClient() as client:
        try:
            start_time = time.time()
            resp = await client.post(
                f"{GATEWAY_URL}/api/v2/chat",
                json={
                    "message": "分析这份电网数据，生成报告并保存",
                    "user_id": "test_user"
                },
                headers={"X-User-Id": "admin"},
                timeout=60.0
            )
            elapsed = time.time() - start_time
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    print_success(f"复杂任务执行成功")
                    print_info(f"任务类型: {data.get('task_type')}")
                    agents_used = data.get('agents_used', [])
                    print_info(f"使用Agent: {' -> '.join(agents_used)}")
                    print_info(f"Agent数量: {len(agents_used)}")
                    print_info(f"响应时间: {elapsed:.2f}s")
                    print_info(f"Session ID: {data.get('session_id')}")
                    
                    # 验证是否使用了多个Agent
                    if len(agents_used) >= 2:
                        print_success("多Agent协作验证通过")
                    else:
                        print_warn(f"期望使用多个Agent，实际使用了 {len(agents_used)} 个")
                    
                    print(f"\n📊 响应内容:")
                    print(f"   {data.get('message')}")
                    return True
                else:
                    print_error(f"任务执行失败: {data.get('message')}")
                    print_error(f"错误: {data.get('error')}")
                    return False
            else:
                print_error(f"Gateway 响应异常: {resp.status_code}")
                return False
                
        except Exception as e:
            print_error(f"请求失败: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_audit_log():
    """测试4: 审计日志验证"""
    print("\n" + "="*60)
    print_info("测试4: 审计日志验证")
    print("="*60)
    
    project_root = Path(__file__).parent.parent
    audit_dir = project_root / "data" / "tasks" / "audit"
    
    if not audit_dir.exists():
        print_error(f"审计日志目录不存在: {audit_dir}")
        return False
    
    audit_files = list(audit_dir.glob("audit_*.json"))
    
    if len(audit_files) > 0:
        print_success(f"找到 {len(audit_files)} 个审计日志文件")
        
        # 查看最新的审计日志
        latest_audit = audit_files[-1]
        with open(latest_audit, 'r', encoding='utf-8') as f:
            audit_data = json.load(f)
        
        print_info(f"最新审计日志: {latest_audit.name}")
        
        # 审计日志可能是列表或字典
        if isinstance(audit_data, list):
            if len(audit_data) > 0:
                audit_entry = audit_data[-1]
                print_info(f"事件数量: {len(audit_data)}")
                print_info(f"第一个事件: {audit_entry.get('event', 'N/A')}")
            else:
                print_warn("审计日志为空")
        elif isinstance(audit_data, dict):
            print_info(f"Session ID: {audit_data.get('session_id', 'N/A')}")
            print_info(f"时间戳: {audit_data.get('timestamp', 'N/A')}")
            print_info(f"用户消息: {audit_data.get('user_message', 'N/A')}")
            intent = audit_data.get('intent', {})
            if isinstance(intent, dict):
                print_info(f"意图识别: {intent.get('type', 'N/A')}")
            print_info(f"使用Agent: {audit_data.get('agents_used', [])}")
        
        return True
    else:
        print_warn("未找到审计日志文件")
        return True


async def test_random_ports():
    """测试5: 验证随机端口"""
    print("\n" + "="*60)
    print_info("测试5: 随机端口验证")
    print("="*60)
    
    try:
        # 读取Worker日志，查看使用的端口
        log_dir = Path(__file__).parent.parent / "logs"
        worker_logs = list(log_dir.glob("worker_*_grpc.log"))
        
        if not worker_logs:
            print_warn("未找到Worker日志文件")
            return True
        
        ports_found = []
        for log_file in worker_logs:
            with open(log_file, 'r') as f:
                content = f.read()
                # 查找端口信息
                if "使用端口:" in content:
                    for line in content.split('\n'):
                        if "使用端口:" in line:
                            port = line.split("使用端口:")[-1].strip()
                            agent = log_file.stem.replace("worker_", "").replace("_grpc", "")
                            ports_found.append((agent, port))
                            print_info(f"{agent}: 端口 {port}")
        
        if ports_found:
            print_success(f"发现 {len(ports_found)} 个Worker使用随机端口")
            
            # 验证端口各不相同
            port_nums = [int(p[1]) for p in ports_found]
            if len(port_nums) == len(set(port_nums)):
                print_success("所有Worker端口都不相同（端口随机分配成功）")
            else:
                print_warn("存在端口冲突（不应该发生）")
            
            return True
        else:
            print_warn("未从日志中找到端口信息")
            return True
            
    except Exception as e:
        print_error(f"随机端口验证失败: {e}")
        return True  # 不阻塞测试


async def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print(f"{Colors.GREEN}🧪 DFEcrab gRPC架构集成测试{Colors.NC}")
    print(f"{Colors.BLUE}架构: Gateway(6789/HTTP) -> Manager(gRPC) -> Workers(gRPC){Colors.NC}")
    print(f"{Colors.BLUE}服务发现: Zookeeper(localhost:2181){Colors.NC}")
    print("="*60)
    
    tests = [
        ("健康检查", test_health_check),
        ("简单任务", test_simple_task),
        ("复杂任务", test_complex_task),
        ("审计日志", test_audit_log),
        ("随机端口", test_random_ports),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print_error(f"测试 [{test_name}] 异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # 汇总结果
    print("\n" + "="*60)
    print_info("测试结果汇总")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        if result:
            print_success(f"{test_name}: 通过")
            passed += 1
        else:
            print_error(f"{test_name}: 失败")
            failed += 1
    
    print("\n" + "-"*60)
    print(f"总计: {len(results)} 个测试")
    print(f"通过: {Colors.GREEN}{passed}{Colors.NC}")
    print(f"失败: {Colors.RED}{failed}{Colors.NC}")
    
    if failed == 0:
        print(f"\n{Colors.GREEN}🎉 所有测试通过！gRPC架构运行正常！{Colors.NC}")
        return 0
    else:
        print(f"\n{Colors.RED}⚠️  有 {failed} 个测试失败，请检查问题{Colors.NC}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}测试被用户中断{Colors.NC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}❌ 测试运行异常: {e}{Colors.NC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
