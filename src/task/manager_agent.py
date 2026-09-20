# src/core/task/manager_agent.py
"""Manager Agent - 智能体推荐和决策 (使用LLM判断执行模式)"""
import re
import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ManagerAgent:
    """Manager智能体 - 负责任务分析、智能体推荐和执行模式决策"""
    
    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).resolve().parent.parent.parent
        self.agent_capabilities = self._load_agents_from_directory()
        logger.info(f"✅ 加载了 {len(self.agent_capabilities)} 个真实智能体")
        for agent_id, info in self.agent_capabilities.items():
            logger.info(f"   - {agent_id}: {info.get('name', agent_id)}")
    
    def _load_agents_from_directory(self) -> Dict[str, Dict[str, Any]]:
        """从 agents/ 目录加载真实的智能体配置"""
        agents = {}
        agents_base = self.project_root / "agents"
        
        if not agents_base.exists():
            logger.warning(f"⚠️ agents 目录不存在: {agents_base}")
            return self._get_default_agents()
        
        for agent_dir in agents_base.iterdir():
            if not agent_dir.is_dir():
                continue
            
            config_path = agent_dir / "config.json"
            if not config_path.exists():
                continue
            
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                agent_id = config.get("agent_id", agent_dir.name)
                capabilities = config.get("capabilities", [])
                
                if not capabilities:
                    tools_path = agent_dir / "tools.json"
                    if tools_path.exists():
                        try:
                            with open(tools_path, 'r', encoding='utf-8') as f:
                                tools = json.load(f)
                            capabilities = tools.get("enabled_skills", [])
                            if not capabilities:
                                capabilities = tools.get("builtin_tools", [])
                            if not capabilities:
                                capabilities = tools.get("custom_tools", [])
                        except Exception:
                            pass
                
                if not capabilities:
                    capabilities = ["通用能力"]
                
                agents[agent_id] = {
                    "name": config.get("name", agent_id),
                    "capabilities": capabilities,
                    "description": config.get("description", ""),
                    "system_prompt": config.get("system_prompt", ""),
                    "agent_type": config.get("agent_type", "worker"),
                    "icon": config.get("icon", "🤖"),
                    "iconColor": config.get("iconColor", "#2196F3"),
                    "bgColor": config.get("bgColor", "#E3F2FD"),
                    "performance_score": config.get("performance_score", 0.8),
                    "avg_execution_time": config.get("avg_execution_time", 30)
                }
                
            except Exception as e:
                logger.warning(f"⚠️ 加载智能体 {agent_dir.name} 失败: {e}")
        
        if not agents:
            return self._get_default_agents()
        
        return agents
    
    def _get_default_agents(self) -> Dict[str, Dict[str, Any]]:
        """降级兜底清单（agents/ 目录不可用时的最小可用列表），仅应急用"""
        return {
            "dfecrab": {
                "name": "DFEcrab",
                "capabilities": ["对话", "文本生成"],
                "description": "DFEcrab 主智能体：通用问答，可装配 MCP 工具完成数据查询/方案制定",
                "system_prompt": "",
                "agent_type": "default",
                "icon": "🦀",
                "iconColor": "#FF6B6B",
                "bgColor": "#FFE5E5",
                "performance_score": 0.5,
                "avg_execution_time": 10
            }
        }
    
    def _get_llm_client(self):
        """获取 LLM 客户端"""
        try:
            from src.services.model_manager import model_manager
            return model_manager
        except ImportError:
            logger.warning("⚠️ model_manager 不可用")
            return None
    
    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        try:
            import requests
            
            llm = self._get_llm_client()
            if not llm:
                return ""
            
            config = llm.get_active_model_config()
            if not config:
                logger.warning("⚠️ 没有可用的模型配置")
                return ""
            
            api_base = config.get("api_base", "")
            model_name = config.get("model_name", "qwen3")
            api_key = config.get("api_key", "not-needed")
            
            url = f"{api_base}/chat/completions"
            
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "你是一个智能体任务调度专家。请根据用户的任务描述和可用智能体信息，做出最优的调度决策。只返回JSON格式结果。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 2048
            }
            
            headers = {"Content-Type": "application/json"}
            if api_key and api_key != "not-needed":
                headers["Authorization"] = f"Bearer {api_key}"
            
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json_match.group()
            return content
            
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return ""
    
    def recommend_agents(self, task_description: str, mode: str = "auto_select") -> Dict[str, Any]:
        """推荐智能体组合和执行模式 - 让LLM自主判断"""
        task_analysis = self._analyze_task_basic(task_description)
        
        agents_desc = []
        for agent_id, info in self.agent_capabilities.items():
            agents_desc.append({
                "agent_id": agent_id,
                "name": info.get("name", agent_id),
                "capabilities": info.get("capabilities", []),
                "description": info.get("description", ""),
                "agent_type": info.get("agent_type", "worker"),
                "avg_execution_time": info.get("avg_execution_time", 30)
            })
        
        prompt = self._build_recommendation_prompt(task_description, task_analysis, agents_desc)
        
        llm_response = self._call_llm(prompt)
        
        if llm_response:
            try:
                llm_result = json.loads(llm_response)
                logger.info("✅ LLM 推荐成功")
                return self._format_result(task_description, task_analysis, llm_result, agents_desc)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ LLM 响应解析失败: {e}")
                logger.debug(f"LLM 响应: {llm_response}")
        
        logger.warning("⚠️ LLM 不可用，使用规则匹配")
        return self._fallback_recommend(task_description, task_analysis, agents_desc)
    
    def _build_recommendation_prompt(self, task_description: str, task_analysis: Dict, agents_desc: List) -> str:
        """构建 LLM 推荐 Prompt"""
        agents_text = ""
        for i, agent in enumerate(agents_desc, 1):
            agents_text += f"""
{i}. agent_id: {agent['agent_id']}
   - 名称: {agent['name']}
   - 能力: {', '.join(agent['capabilities'])}
   - 描述: {agent['description']}
   - 类型: {agent['agent_type']}
   - 预估执行时间: {agent.get('avg_execution_time', 30)}秒
"""
        
        prompt = f"""请根据以下任务描述和可用智能体列表，做出最优的任务调度决策。

## 任务描述
{task_description}

## 任务初步分析
- 核心目标: {task_analysis.get('goal', '未指定')}
- 所需能力: {', '.join(task_analysis.get('skills', ['通用能力']))}
- 复杂度: {task_analysis.get('complexity', '中等')}
- 输出类型: {task_analysis.get('output_type', '数据')}

## 可用智能体列表
{agents_text}

## 请做出以下决策，并以JSON格式返回

### 1. 选择智能体
从上述列表中选择最适合完成此任务的智能体（1-5个），按优先级排序。

### 2. 执行模式
根据任务特点和智能体关系，选择最合适的执行模式：

- **sequential（串行）**: 任务步骤有依赖关系，必须按顺序执行（如：先查询数据，再分析数据，最后生成报告）
- **parallel（并行）**: 任务步骤相互独立，可以同时执行（如：同时查询多个数据源）
- **hybrid（混合）**: 部分步骤可以并行，部分需要串行（如：先并行获取多个数据，再串行分析和报告）

### 3. 执行说明
- 如果选择混合模式，请说明哪些步骤可以并行，哪些需要串行
- 说明各智能体的执行顺序和依赖关系

## 返回格式
```json
{{
    "reasoning": [
        "步骤1: 分析任务需求...",
        "步骤2: 匹配合适的智能体...",
        "步骤3: 确定执行模式...",
        "步骤4: 规划执行顺序..."
    ],
    "selected_agents": [
        {{
            "agent_id": "智能体ID",
            "reason": "选择原因",
            "order": 1
        }}
    ],
    "collaboration_mode": "sequential/parallel/hybrid",
    "execution_plan": {{
        "description": "执行计划描述",
        "parallel_groups": [
            {{
                "group_id": 1,
                "agents": ["agent1", "agent2"],
                "reason": "这些可以并行执行的原因"
            }}
        ],
        "sequential_steps": [
            {{
                "step": 1,
                "agent": "agent_id",
                "depends_on": []
            }}
        ]
    }},
    "estimated_duration": "预估时间"
}}
请只返回JSON，不要有其他内容。"""

        return prompt

    def _analyze_task_basic(self, description: str) -> Dict[str, Any]:
        """基础任务分析（作为LLM的输入）"""
        keyword_skills = {
            "故障": ["故障分析", "故障诊断", "根因分析", "异常检测", "风险分析"],
            "异常": ["异常检测", "故障分析", "监控", "风险分析"],
            "风险": ["风险分析", "数据查询", "异常检测"],
            "报告": ["报告生成", "文档撰写", "数据可视化", "内容总结"],
            "简报": ["报告生成", "数据可视化", "内容总结"],
            "日报": ["报告生成", "数据聚合", "数据可视化"],
            "周报": ["报告生成", "数据聚合", "数据可视化"],
            "分析": ["数据分析", "数据聚合", "异常检测", "根因分析", "风险分析"],
            "查询": ["数据查询", "API调用", "HTTP请求"],
            "数据": ["数据聚合", "数据分析", "数据可视化", "数据查询"],
            "生成": ["内容生成", "报告生成", "文本生成"],
            "日志": ["日志分析", "异常检测"],
            "文件": ["文件管理", "保存文件"],
            "保存": ["保存文件", "文件管理"],
            "电网": ["电网风险查询", "电网故障查询", "数据查询"],
            "馈线": ["数据查询", "电网风险查询"],
            "配变": ["数据查询", "电网风险查询"],
            "跳闸": ["电网故障查询", "数据查询"],
        }

        matched_skills = set()
        for word, skills in keyword_skills.items():
            if word.lower() in description.lower():
                matched_skills.update(skills)

        if not matched_skills:
            matched_skills = {"对话", "文本生成", "推理"}

        complexity = "简单"
        if len(matched_skills) > 4:
            complexity = "复杂"
        elif len(matched_skills) > 2:
            complexity = "中等"

        output_type = "数据"
        if any(kw in description for kw in ["报告", "简报", "日报", "周报"]):
            output_type = "报告"
        elif any(kw in description for kw in ["通知", "告警"]):
            output_type = "通知"
        elif any(kw in description for kw in ["分析", "统计", "风险"]):
            output_type = "分析结果"

        return {
            "goal": description[:50],
            "skills": list(matched_skills),
            "complexity": complexity,
            "output_type": output_type,
            "keywords": [word for word in keyword_skills.keys() if word in description]
        }

    def _format_result(self, task_description: str, task_analysis: Dict, llm_result: Dict, agents_desc: List) -> Dict[str, Any]:
        """格式化 LLM 返回结果"""
        selected = llm_result.get("selected_agents", [])
        mode = llm_result.get("collaboration_mode", "sequential")
        reasoning = llm_result.get("reasoning", [])

        full_agents = []
        for rec in selected:
            agent_id = rec.get("agent_id")
            agent_info = next((a for a in agents_desc if a["agent_id"] == agent_id), None)
            if agent_info:
                full_agents.append({
                    "agent_id": agent_id,
                    "name": agent_info.get("name", agent_id),
                    "score": 0.8,
                    "reason": rec.get("reason", "LLM推荐"),
                    "capabilities": agent_info.get("capabilities", []),
                    "description": agent_info.get("description", ""),
                    "agent_type": agent_info.get("agent_type", "worker"),
                    "icon": agent_info.get("icon", "🤖"),
                    "iconColor": agent_info.get("iconColor", "#2196F3"),
                    "bgColor": agent_info.get("bgColor", "#E3F2FD"),
                    "order": rec.get("order", 0)
                })

        if not full_agents:
            for agent in agents_desc[:3]:
                full_agents.append({
                    "agent_id": agent["agent_id"],
                    "name": agent.get("name", agent["agent_id"]),
                    "score": 0.5,
                    "reason": "默认推荐",
                    "capabilities": agent.get("capabilities", []),
                    "description": agent.get("description", ""),
                    "agent_type": agent.get("agent_type", "worker"),
                    "icon": agent.get("icon", "🤖"),
                    "iconColor": agent.get("iconColor", "#2196F3"),
                    "bgColor": agent.get("bgColor", "#E3F2FD")
                })

        full_agents.sort(key=lambda x: x.get("order", 0))

        return {
            "task_analysis": task_analysis,
            "reasoning": reasoning or ["LLM智能决策"],
            "recommended_agents": full_agents,
            "recommended_collaboration_mode": mode,
            "execution_plan": llm_result.get("execution_plan", {}),
            "estimated_duration": llm_result.get("estimated_duration", "约 2-3 分钟"),
            "alternative_configs": []
        }

    def _fallback_recommend(self, task_description: str, task_analysis: Dict, agents_desc: List) -> Dict[str, Any]:
        """降级方案：规则匹配"""
        keyword_agent_map = {
            "风险": "risk_query_agent",
            "故障": "risk_query_agent",
            "电网": "risk_query_agent",
            "查询": "risk_query_agent",
            "报告": "reporter_agent",
            "简报": "reporter_agent",
            "总结": "reporter_agent",
            "分析": "analyst_agent",
            "数据": "analyst_agent",
            "文件": "file_manager_agent",
            "保存": "file_manager_agent",
        }

        matched_agent_ids = []
        for keyword, agent_id in keyword_agent_map.items():
            if keyword in task_description:
                if agent_id not in matched_agent_ids:
                    matched_agent_ids.append(agent_id)

        if not matched_agent_ids:
            matched_agent_ids = [a["agent_id"] for a in agents_desc[:2]]

        full_agents = []
        for agent_id in matched_agent_ids[:3]:
            agent_info = next((a for a in agents_desc if a["agent_id"] == agent_id), None)
            if agent_info:
                full_agents.append({
                    "agent_id": agent_id,
                    "name": agent_info.get("name", agent_id),
                    "score": 0.6,
                    "reason": "关键词匹配",
                    "capabilities": agent_info.get("capabilities", []),
                    "description": agent_info.get("description", ""),
                    "agent_type": agent_info.get("agent_type", "worker"),
                    "icon": agent_info.get("icon", "🤖"),
                    "iconColor": agent_info.get("iconColor", "#2196F3"),
                    "bgColor": agent_info.get("bgColor", "#E3F2FD")
                })

        if task_analysis.get("complexity") == "复杂":
            mode = "hybrid"
        elif task_analysis.get("output_type") == "报告":
            mode = "sequential"
        elif len(full_agents) >= 3:
            mode = "parallel"
        else:
            mode = "sequential"

        return {
            "task_analysis": task_analysis,
            "reasoning": [
                "📋 步骤1: 分析任务描述",
                f"🔧 步骤2: 匹配到 {len(full_agents)} 个智能体",
                f"🎯 步骤3: 建议使用 {mode} 模式"
            ],
            "recommended_agents": full_agents,
            "recommended_collaboration_mode": mode,
            "execution_plan": {},
            "estimated_duration": "约 2-3 分钟",
            "alternative_configs": []
        }

